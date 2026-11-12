const day = document.querySelector('#day');
const times = document.querySelector('#time-list');
const slot = document.querySelector('#slot');
const form = document.querySelector('#booking-form');
const message = document.querySelector('#message');
const submit = document.querySelector('#submit');
function notify(text, error = false) { message.textContent = text; message.className = `message${error ? ' error' : ''}`; }
function dateBR(text) { return new Date(`${text}T12:00:00`).toLocaleDateString('pt-BR', {day:'2-digit',month:'long',year:'numeric'}); }
async function api(url, opts) { const r = await fetch(url, opts); const data = await r.json(); if (!r.ok) throw Error(typeof data.detail === 'string' ? data.detail : 'Não foi possível concluir a solicitação.'); return data; }
async function loadDates() {
  day.innerHTML = '<option value="">Selecione uma data</option>'; slot.value = '';
  try { const dates = await api('/api/dates');
    for (const d of dates) { const opt = document.createElement('option'); opt.value = d.day; opt.textContent = `${dateBR(d.day)} · ${d.available} disponível(is)`; day.append(opt); }
    if (!dates.length) { day.innerHTML = '<option value="">Nenhuma data disponível no momento</option>'; times.innerHTML = '<span class="muted">Aguarde a abertura de novos horários.</span>'; }
  } catch(e) { notify(e.message, true); }
}
async function loadTimes() {
  slot.value = ''; times.replaceChildren();
  if (!day.value) { times.textContent = 'Selecione uma data para ver os horários.'; return; }
  times.textContent = 'Carregando horários...';
  try { const slots = await api(`/api/slots?day=${encodeURIComponent(day.value)}`); times.replaceChildren();
    if (!slots.length) { times.textContent = 'Não há horários livres nesta data.'; return; }
    for (const s of slots) { const b = document.createElement('button'); b.type='button'; b.className='time-button'; b.textContent=s.hour; b.setAttribute('aria-pressed', 'false'); b.addEventListener('click', () => { times.querySelectorAll('button').forEach(x => { x.classList.remove('active'); x.setAttribute('aria-pressed','false'); }); b.classList.add('active'); b.setAttribute('aria-pressed','true'); slot.value=s.id; }); times.append(b); }
  } catch(e) { notify(e.message, true); }
}
day.addEventListener('change', loadTimes);
form.addEventListener('submit', async (ev) => { ev.preventDefault(); message.classList.add('hidden'); if(!slot.value) { notify('Escolha um horário antes de continuar.', true); return; } submit.disabled = true;
  try { const booked = await api('/api/bookings', {method:'POST',headers:{'Content-Type':'application/json'},body: JSON.stringify({slot_id:Number(slot.value), responsible:document.querySelector('#responsible').value,student:document.querySelector('#student').value})});
    form.classList.add('hidden'); const box = document.querySelector('#confirmation'); box.replaceChildren();
    const title = document.createElement('h3'); title.textContent = '✓ Agendamento confirmado!'; box.append(title);
    const text = document.createElement('p'); text.textContent='Guarde estas informações para o dia do atendimento.'; box.append(text);
    const dl = document.createElement('dl'); for(const [name,value] of [['Protocolo',`#${booked.id}`],['Data',dateBR(booked.day)],['Horário',booked.hour],['Responsável',booked.responsible],['Estudante',booked.student]]){const dt=document.createElement('dt');dt.textContent=name;const dd=document.createElement('dd');dd.textContent=value;dl.append(dt,dd);}box.append(dl);
    const again=document.createElement('button');again.className='secondary-button';again.textContent='Fazer outro agendamento';again.addEventListener('click',()=>location.reload());box.append(again);box.classList.remove('hidden');
  } catch(e) { notify(e.message,true); await loadDates(); } finally { submit.disabled = false; }
});
loadDates();
