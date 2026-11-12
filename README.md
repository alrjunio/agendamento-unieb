# Agendamento de triagem — CRE Brazlândia / UNIEB

Aplicação em **Python + FastAPI + HTML + CSS + JavaScript**, responsiva para celulares.

## Funcionalidades

- Página pública: data, horário disponível, nome do responsável e nome do estudante.
- Confirmação na tela com número de protocolo.
- Painel administrativo protegido por senha: `/admin`.
- Administrador abre horários por data, intervalo de atendimento e duração.
- Administrador consulta agendamentos, cancela reservas, exclui horários nunca reservados e exporta CSV.
- Bloqueio de duplicidade **garantido pelo SQLite** (índice único parcial), mesmo com requisições concorrentes.
- Cancelamento mantém o histórico e libera o horário para nova reserva.
- Fuso horário: `America/Sao_Paulo` (Brasília).

## Executar com Docker

1. Instale Docker Desktop e abra um terminal nesta pasta.
2. No PowerShell, execute `powershell -ExecutionPolicy Bypass -File .\configurar.ps1`, e defina uma senha forte (mínimo 12 caracteres). Isso cria o `.env` e gera uma chave secreta.
3. Alternativamente, copie `.env.example` para `.env` e configure manualmente uma **senha forte** e uma chave secreta aleatória. Para gerar chave (se tiver Python instalado):

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

4. Rode:

   ```bash
   docker compose up -d --build
   ```

5. Acesse localmente `http://localhost:8000` e `http://localhost:8000/admin`.
6. As datas e horários abaixo são cadastrados automaticamente na primeira inicialização do banco de dados. O painel também permite criar outras datas. Reiniciar não duplica reservas nem repõe horários excluídos.

O banco de dados persiste no volume Docker `agendamento_data`. **Faça backup deste volume**. O arquivo `.env` não deve ser publicado nem incluído em repositórios.

### Executar sem Docker (desenvolvimento)

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# Linux/macOS:
# source .venv/bin/activate
pip install -r requirements.txt
# Configure ADMIN_PASSWORD e SESSION_SECRET no ambiente antes de iniciar.
uvicorn app.main:app --reload
```

## Agenda inicial — 24 vagas

Datas de **2026**: 17/11, 18/11, 19/11, 24/11, 25/11, 27/11, 01/12 e 02/12.
Horários em cada data: **14:00, 15:00 e 16:00** (Brasília). Apenas uma reserva ativa por horário.

## Publicar na internet

A configuração de Docker publica o FastAPI **apenas na interface local** (`127.0.0.1:8000`) por segurança. Para torná-lo público, configure um domínio e um proxy reverso (Caddy, Nginx, Traefik ou solução equivalente) com **HTTPS** na frente do serviço. Exemplo de Caddyfile:

```caddy
agendamento.seudominio.com.br {
    reverse_proxy 127.0.0.1:8000
}
```

No servidor, configure `HTTPS_ONLY=true` no `.env`, reinicie o contêiner, habilite backups, atualizações e proteção contra ataques de força bruta no proxy. Garanta que somente o proxy seja exposto. Para maior escala/múltiplas instâncias, considere PostgreSQL, rate limiting centralizado e controles adicionais de auditoria e de acesso.

## Marca / identidade visual

A interface usa paleta verde e amarelo e identificação textual **CRE Brazlândia · UNIEB**. O quadrado `DF` é **um elemento gráfico provisório**, não a logomarca oficial. Para usar logos oficiais sem alterar ou distorcer, substitua-o com o arquivo institucional autorizado e siga o manual de identidade visual do GDF.

## Privacidade

Este é um sistema de marcação para um contexto que envolve estudantes. Colete somente os nomes necessários. **Não inclua dados de saúde, diagnóstico ou cópia dos laudos.** Restrinja acesso aos administradores designados, estabeleça prazo de retenção e procedimento de exclusão, e confirme a adequação à LGPD e às orientações da SEEDF antes de colocar dados reais na internet. Este MVP não inclui recuperação de senha, perfis múltiplos, notificação por e-mail ou comprovante por WhatsApp.

## Endpoints

- `GET /api/dates` — datas disponíveis.
- `GET /api/slots?day=AAAA-MM-DD` — horários livres.
- `POST /api/bookings` — reserva atômica.
- `POST /api/admin/login` — login.
- `GET /api/admin/summary` — indicadores.
- `GET /api/admin/bookings` — lista.
- `POST /api/admin/slots` — abrir horários.
- `POST /api/admin/bookings/{id}/cancel` — cancelar.
- `GET /api/admin/export.csv` — relatório CSV.
