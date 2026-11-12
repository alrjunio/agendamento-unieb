import csv
import hmac
import io
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("DATABASE_PATH", str(BASE_DIR.parent / "data" / "agendamentos.db")))
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
SESSION_SECRET = os.getenv("SESSION_SECRET", "")
HTTPS_ONLY = os.getenv("HTTPS_ONLY", "false").lower() == "true"
TZ = ZoneInfo("America/Sao_Paulo")

if not ADMIN_PASSWORD or ADMIN_PASSWORD == "SUBSTITUA_POR_UMA_SENHA_FORTE":
    raise RuntimeError("Configure ADMIN_PASSWORD no arquivo .env")
if len(SESSION_SECRET) < 32 or SESSION_SECRET.startswith("SUBSTITUA_"):
    raise RuntimeError("Configure SESSION_SECRET com no mínimo 32 caracteres")

serializer = URLSafeTimedSerializer(SESSION_SECRET, salt="unieb-admin-session-v1")
app = FastAPI(title="Agendamento de Triagem | UNIEB Brazlândia", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def today():
    return datetime.now(TZ).date()


def now_local():
    return datetime.now(TZ)


@contextmanager
def db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=15, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=15000")
    try:
        yield connection
    finally:
        connection.close()


@app.on_event("startup")
def init_db():
    with db() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript("""
            CREATE TABLE IF NOT EXISTS slots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day TEXT NOT NULL,
                hour TEXT NOT NULL,
                UNIQUE(day, hour)
            );
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slot_id INTEGER NOT NULL REFERENCES slots(id),
                responsible TEXT NOT NULL,
                student TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'confirmed' CHECK(status IN ('confirmed','cancelled')),
                created_at TEXT NOT NULL,
                cancelled_at TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS one_confirmed_per_slot
              ON bookings(slot_id) WHERE status = 'confirmed';
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        # Agenda inicial cadastrada apenas uma vez por banco de dados.
        # Reiniciar o Docker não repõe horários que o administrador excluiu.
        first_setup = c.execute("SELECT 1 FROM app_settings WHERE key='triagem_2026_seeded'").fetchone()
        if not first_setup:
            days = ('2026-11-17', '2026-11-18', '2026-11-19',
                    '2026-11-24', '2026-11-25', '2026-11-27',
                    '2026-12-01', '2026-12-02')
            c.executemany("INSERT OR IGNORE INTO slots(day,hour) VALUES(?,?)",
                          [(day, hour) for day in days for hour in ('14:00', '15:00', '16:00')])
            c.execute("INSERT INTO app_settings(key,value) VALUES('triagem_2026_seeded','1')")


def valid_day(s):
    try:
        d = date.fromisoformat(s)
        if d.isoformat() != s:
            raise ValueError
        return d
    except (ValueError, TypeError):
        raise HTTPException(422, "Data inválida")


def valid_hour(s):
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", s):
        raise HTTPException(422, "Horário inválido")
    return s


def slot_is_future(day, hour):
    return datetime.fromisoformat(f"{day}T{hour}").replace(tzinfo=TZ) > now_local()


def get_admin(request: Request):
    token = request.cookies.get("unieb_admin", "")
    try:
        payload = serializer.loads(token, max_age=8 * 60 * 60)
        if payload.get("role") == "admin" and isinstance(payload.get("csrf"), str):
            return payload
    except (BadSignature, ValueError):
        pass
    raise HTTPException(401, "Acesso administrativo não autorizado")


def require_admin(request: Request, mutate=False):
    session = get_admin(request)
    if mutate:
        sent = request.headers.get("X-CSRF-Token", "")
        if not hmac.compare_digest(sent, session["csrf"]):
            raise HTTPException(403, "Token de segurança inválido")
        # Compare a origem com o Host público que o navegador utilizou.
        # request.base_url pode conter o esquema/porta interna quando há proxy.
        origin = request.headers.get("origin")
        if origin:
            parsed = urlsplit(origin)
            host = request.headers.get("host", "").lower()
            if parsed.scheme not in ("http", "https") or parsed.netloc.lower() != host:
                raise HTTPException(403, "Origem inválida. Atualize a página e tente novamente")
    return session


class BookingIn(BaseModel):
    slot_id: int = Field(gt=0)
    responsible: str = Field(min_length=3, max_length=120)
    student: str = Field(min_length=3, max_length=120)


class LoginIn(BaseModel):
    password: str


class SlotsIn(BaseModel):
    day: str
    start: str
    end: str
    interval_minutes: int = Field(ge=10, le=120)


def clean_name(name):
    name = " ".join(name.strip().split())
    if len(name) < 3 or len(name) > 120 or any(ord(c) < 32 for c in name):
        raise HTTPException(422, "Preencha os nomes corretamente")
    return name


@app.get("/", response_class=HTMLResponse)
def public_page(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request):
    return templates.TemplateResponse(request, "admin.html")


@app.get("/api/dates")
def available_dates():
    with db() as c:
        rows = c.execute("""
            SELECT s.day, s.hour FROM slots s
            LEFT JOIN bookings b ON b.slot_id=s.id AND b.status='confirmed'
            WHERE s.day >= ? AND b.id IS NULL
            ORDER BY s.day,s.hour
        """, (today().isoformat(),)).fetchall()
    counts = {}
    for row in rows:
        if slot_is_future(row["day"], row["hour"]):
            counts[row["day"]] = counts.get(row["day"], 0) + 1
    return [{"day": day, "available": count} for day, count in counts.items()]


@app.get("/api/slots")
def available_slots(day: str):
    d = valid_day(day)
    if d < today():
        return []
    with db() as c:
        rows = c.execute("""
            SELECT s.id, s.hour FROM slots s
            LEFT JOIN bookings b ON b.slot_id=s.id AND b.status='confirmed'
            WHERE s.day=? AND b.id IS NULL ORDER BY s.hour
        """, (day,)).fetchall()
    return [{"id": r["id"], "hour": r["hour"]} for r in rows if slot_is_future(day, r["hour"])]


@app.post("/api/bookings", status_code=201)
def create_booking(body: BookingIn):
    responsible = clean_name(body.responsible)
    student = clean_name(body.student)
    with db() as c:
        try:
            c.execute("BEGIN IMMEDIATE")
            slot = c.execute("SELECT day,hour FROM slots WHERE id=?", (body.slot_id,)).fetchone()
            if not slot or not slot_is_future(slot["day"], slot["hour"]):
                raise HTTPException(409, "Horário inexistente ou já encerrado")
            cur = c.execute("""INSERT INTO bookings(slot_id,responsible,student,created_at)
                             VALUES(?,?,?,?)""", (body.slot_id, responsible, student, now_local().isoformat()))
            c.commit()
        except sqlite3.IntegrityError:
            c.rollback()
            raise HTTPException(409, "Esse horário já foi reservado. Escolha outro.")
        except Exception:
            c.rollback()
            raise
    return {"id": cur.lastrowid, "day": slot["day"], "hour": slot["hour"], "responsible": responsible, "student": student}


# Limite básico de tentativas por processo; em produção de maior escala usar proxy/Redis.
_login_failures = {}


@app.post("/api/admin/login")
def login(body: LoginIn, request: Request, response: Response):
    ip = request.client.host if request.client else "unknown"
    timestamp = now_local().timestamp()
    attempts = [t for t in _login_failures.get(ip, []) if timestamp - t < 15 * 60]
    if len(attempts) >= 10:
        raise HTTPException(429, "Muitas tentativas. Tente novamente mais tarde.")
    if not hmac.compare_digest(body.password, ADMIN_PASSWORD):
        attempts.append(timestamp)
        _login_failures[ip] = attempts
        raise HTTPException(401, "Senha incorreta")
    _login_failures.pop(ip, None)
    csrf = secrets.token_urlsafe(32)
    response.set_cookie("unieb_admin", serializer.dumps({"role": "admin", "csrf": csrf}),
                        max_age=8 * 60 * 60, httponly=True, secure=HTTPS_ONLY, samesite="lax", path="/")
    return {"ok": True, "csrf": csrf}


@app.post("/api/admin/logout")
def logout(request: Request, response: Response):
    require_admin(request, mutate=True)
    response.delete_cookie("unieb_admin", path="/")
    return {"ok": True}


@app.get("/api/admin/me")
def admin_me(request: Request):
    session = require_admin(request)
    return {"ok": True, "csrf": session["csrf"]}


@app.get("/api/admin/summary")
def admin_summary(request: Request):
    require_admin(request)
    with db() as c:
        slots = c.execute("SELECT COUNT(*) FROM slots WHERE day>=?", (today().isoformat(),)).fetchone()[0]
        confirmed = c.execute("""SELECT COUNT(*) FROM bookings b JOIN slots s ON s.id=b.slot_id
              WHERE b.status='confirmed' AND s.day>=?""", (today().isoformat(),)).fetchone()[0]
        all_confirmed = c.execute("SELECT COUNT(*) FROM bookings WHERE status='confirmed'").fetchone()[0]
    return {"future_slots": slots, "future_bookings": confirmed, "available": slots - confirmed, "total_confirmed": all_confirmed}


@app.get("/api/admin/bookings")
def admin_bookings(request: Request, day: str = ""):
    require_admin(request)
    if day:
        valid_day(day)
    with db() as c:
        rows = c.execute("""SELECT b.id,b.responsible,b.student,b.status,b.created_at,s.day,s.hour
            FROM bookings b JOIN slots s ON s.id=b.slot_id
            WHERE (?='' OR s.day=?) ORDER BY s.day DESC,s.hour DESC,b.id DESC LIMIT 2000""", (day, day)).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/admin/slots")
def admin_slots(request: Request, day: str):
    require_admin(request)
    valid_day(day)
    with db() as c:
        rows = c.execute("""SELECT s.id,s.day,s.hour,
            CASE WHEN b.id IS NULL THEN 0 ELSE 1 END AS booked
            FROM slots s LEFT JOIN bookings b ON b.slot_id=s.id AND b.status='confirmed'
            WHERE s.day=? ORDER BY s.hour""", (day,)).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/admin/slots")
def add_slots(body: SlotsIn, request: Request):
    require_admin(request, mutate=True)
    day = valid_day(body.day)
    if day < today():
        raise HTTPException(422, "Não é possível abrir horários em datas passadas")
    start = valid_hour(body.start)
    end = valid_hour(body.end)
    start_dt = datetime.fromisoformat(f"{day}T{start}")
    end_dt = datetime.fromisoformat(f"{day}T{end}")
    if end_dt <= start_dt:
        raise HTTPException(422, "O horário final deve ser posterior ao inicial")
    generated = []
    current = start_dt
    while current < end_dt:
        hour = current.strftime("%H:%M")
        if slot_is_future(body.day, hour):
            generated.append((body.day, hour))
        current += timedelta(minutes=body.interval_minutes)
    if len(generated) > 100:
        raise HTTPException(422, "Limite de 100 horários por operação")
    with db() as c:
        before = c.total_changes
        c.executemany("INSERT OR IGNORE INTO slots(day,hour) VALUES(?,?)", generated)
        inserted = c.total_changes - before
    return {"inserted": inserted, "skipped": len(generated) - inserted}


@app.delete("/api/admin/slots/{slot_id}")
def delete_slot(slot_id: int, request: Request):
    require_admin(request, mutate=True)
    with db() as c:
        booked = c.execute("SELECT 1 FROM bookings WHERE slot_id=? LIMIT 1", (slot_id,)).fetchone()
        if booked:
            raise HTTPException(409, "Este horário tem histórico de reserva e não pode ser excluído")
        result = c.execute("DELETE FROM slots WHERE id=?", (slot_id,))
        if not result.rowcount:
            raise HTTPException(404, "Horário não encontrado")
    return {"ok": True}


@app.post("/api/admin/bookings/{booking_id}/cancel")
def cancel_booking(booking_id: int, request: Request):
    require_admin(request, mutate=True)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        result = c.execute("""UPDATE bookings SET status='cancelled',cancelled_at=?
            WHERE id=? AND status='confirmed'""", (now_local().isoformat(), booking_id))
        if not result.rowcount:
            c.rollback()
            raise HTTPException(404, "Agendamento ativo não encontrado")
        c.commit()
    return {"ok": True, "message": "Agendamento cancelado; vaga liberada"}


@app.get("/api/admin/export.csv")
def export_csv(request: Request):
    require_admin(request)
    with db() as c:
        rows = c.execute("""SELECT s.day,s.hour,b.responsible,b.student,b.status,b.created_at
            FROM bookings b JOIN slots s ON s.id=b.slot_id ORDER BY s.day,s.hour""").fetchall()
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["Data", "Horário", "Responsável", "Estudante", "Situação", "Registrado em"])
    for row in rows:
        writer.writerow([row["day"], row["hour"], row["responsible"], row["student"], row["status"], row["created_at"]])
    csv_content = "\ufeff" + output.getvalue()
    return StreamingResponse(iter([csv_content]), media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="agendamentos-unieb.csv"',
                     "Cache-Control": "no-store"})


@app.get("/health")
def health():
    return {"status": "ok"}


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api/") else "no-cache"
    return response
