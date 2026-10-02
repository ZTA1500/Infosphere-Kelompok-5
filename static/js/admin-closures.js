/* Admin "Area Status": mark rooms / drawn areas as closed or under construction.
   Every value an admin or the API supplies is inserted with textContent. */

const STATUS_LABEL = { closed: 'Closed', under_construction: 'Under construction' };
const els = {
  map: document.getElementById('as-map'),
  hint: document.getElementById('as-hint'),
  draw: document.getElementById('btn-draw'),
  drawCancel: document.getElementById('btn-draw-cancel'),
  form: document.getElementById('as-form'),
  title: document.getElementById('as-form-title'),
  selected: document.getElementById('as-selected'),
  status: document.getElementById('as-status'),
  note: document.getElementById('as-note'),
  ends: document.getElementById('as-ends'),
  error: document.getElementById('as-error'),
  save: document.getElementById('as-save'),
  reset: document.getElementById('as-reset'),
  list: document.getElementById('as-list'),
  count: document.getElementById('as-count'),
  confirm: document.getElementById('as-confirm'),
  confirmText: document.getElementById('as-confirm-text'),
};

let MAP = null;          // rooms.json
let fm = null;           // FloorMap
let closures = [];
let selection = null;    // { floor, roomId } | { floor, polygon }
let editing = null;      // closure being edited
let saving = false;

const roomById = id => MAP.rooms.find(r => r.id === id);
const floorLabel = n => (MAP.floors.find(f => f.floor === n) || { label: 'Floor ' + n }).label;

function areaName(c) {
  const room = c.roomId && roomById(c.roomId);
  return room ? room.name : `Drawn area (${floorLabel(c.floor)})`;
}

/* datetime-local <-> UTC ISO */
function toLocalInput(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function fromLocalInput(v) {
  if (!v) return null;
  const d = new Date(v);
  return isNaN(d) ? 'invalid' : d.toISOString();
}

/* ── selection ─────────────────────────────────────────────────────────── */

function setSelection(sel) {
  selection = sel;
  fm.setSelection(sel);
  els.selected.textContent = '';
  if (!sel) {
    els.selected.textContent = 'Nothing selected yet — click a room or draw an area.';
    els.selected.classList.remove('has');
    return;
  }
  els.selected.classList.add('has');
  const strong = document.createElement('b');
  strong.textContent = sel.roomId ? roomById(sel.roomId).name : 'Drawn area';
  els.selected.append(strong, ` · ${floorLabel(sel.floor)}`);
  const existing = closures.find(c => c.floor === sel.floor && sel.roomId && c.roomId === sel.roomId);
  if (existing && (!editing || editing.id !== existing.id)) {
    const warn = document.createElement('div');
    warn.className = 'as-note-warn';
    warn.textContent = `Already marked "${STATUS_LABEL[existing.status]}" — edit it in the list instead of adding a second one.`;
    els.selected.appendChild(warn);
  }
}

function resetForm() {
  editing = null;
  els.title.textContent = 'New closure';
  els.save.textContent = 'Save';
  els.status.value = 'closed';
  els.note.value = '';
  els.ends.value = '';
  els.error.textContent = '';
  setSelection(null);
  renderList();
}

function startEdit(c) {
  editing = c;
  els.title.textContent = `Edit: ${areaName(c)}`;
  els.save.textContent = 'Save changes';
  els.status.value = c.status;
  els.note.value = c.note || '';
  els.ends.value = toLocalInput(c.endsAt);
  els.error.textContent = '';
  fm.showFloor(c.floor);
  setSelection(c.roomId ? { floor: c.floor, roomId: c.roomId } : { floor: c.floor, polygon: c.polygon });
  renderList();
  els.form.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  els.status.focus({ preventScroll: true });
}

/* ── drawing ───────────────────────────────────────────────────────────── */

async function drawArea() {
  els.draw.hidden = true;
  els.drawCancel.hidden = false;
  els.hint.textContent = 'Drag on the map to draw the area (zoom with the buttons first if needed).';
  const poly = await fm.drawRect();
  els.draw.hidden = false;
  els.drawCancel.hidden = true;
  els.hint.textContent = 'Choose a floor, then click a room on the map.';
  if (poly) setSelection({ floor: fm.current, polygon: poly });
}

/* ── list ──────────────────────────────────────────────────────────────── */

function renderList() {
  els.list.textContent = '';
  els.count.textContent = closures.length ? `${closures.length} total` : '';
  if (!closures.length) {
    const p = document.createElement('p');
    p.className = 'empty-state';
    p.textContent = 'No closures — every area is open.';
    els.list.appendChild(p);
    return;
  }
  for (const c of closures) {
    const card = document.createElement('article');
    card.className = 'fb-card as-card' + (editing && editing.id === c.id ? ' editing' : '');
    const head = document.createElement('div');
    head.className = 'fb-card-head';
    const badge = document.createElement('span');
    badge.className = `badge-cat as-badge as-badge-${c.status}`;
    badge.textContent = (c.status === 'closed' ? '⛔ ' : '🚧 ') + STATUS_LABEL[c.status];
    const name = document.createElement('span');
    name.className = 'fb-card-who';
    name.textContent = `${areaName(c)} · ${floorLabel(c.floor)}`;
    head.append(badge, name);
    if (!c.active) {
      const sched = document.createElement('span');
      sched.className = 'new-pill';
      sched.textContent = 'Scheduled';
      head.appendChild(sched);
    }
    card.appendChild(head);
    if (c.note) {
      const note = document.createElement('div');
      note.className = 'fb-card-msg';
      note.textContent = c.note;
      card.appendChild(note);
    }
    const foot = document.createElement('div');
    foot.className = 'fb-card-foot';
    const meta = document.createElement('span');
    meta.className = 'fb-card-meta';
    meta.textContent = `${c.endsAt ? 'Until ' + fmtDateTime(c.endsAt) : 'Until removed'} · updated ${fmtDateTime(c.updatedAt)}${c.updatedBy ? ' by ' + c.updatedBy : ''}`;
    const actions = document.createElement('div');
    actions.className = 'fb-actions';
    const show = document.createElement('button');
    show.type = 'button'; show.className = 'fb-act'; show.textContent = 'Show';
    show.addEventListener('click', () => { fm.showFloor(c.floor); });
    const edit = document.createElement('button');
    edit.type = 'button'; edit.className = 'fb-act'; edit.textContent = 'Edit';
    edit.addEventListener('click', () => startEdit(c));
    const del = document.createElement('button');
    del.type = 'button'; del.className = 'fb-act danger'; del.textContent = 'Remove';
    del.addEventListener('click', () => removeClosure(c));
    actions.append(show, edit, del);
    foot.append(meta, actions);
    card.appendChild(foot);
    els.list.appendChild(card);
  }
}

async function loadClosures() {
  try {
    const data = await api('/admin/api/closures');
    closures = data.closures || [];
  } catch (e) {
    els.list.textContent = '';
    const p = document.createElement('p');
    p.className = 'empty-state';
    p.textContent = 'Could not load closures: ' + e.message;
    els.list.appendChild(p);
    return;
  }
  fm.setClosures(closures);
  renderList();
}

function confirmRemove(c) {
  els.confirmText.textContent = `"${areaName(c)}" will show as open again for every visitor.`;
  if (typeof els.confirm.showModal !== 'function') {
    return Promise.resolve(window.confirm(`Remove the closure on ${areaName(c)}?`));
  }
  return new Promise(resolve => {
    els.confirm.returnValue = '';
    els.confirm.addEventListener('close', () => resolve(els.confirm.returnValue === 'ok'), { once: true });
    els.confirm.showModal();
  });
}

async function removeClosure(c) {
  if (!(await confirmRemove(c))) return;
  try {
    await api(`/admin/api/closures/${c.id}`, { method: 'DELETE' });
    showToast(`${areaName(c)} is open again.`, 'ok');
    if (editing && editing.id === c.id) resetForm();
    await loadClosures();
  } catch (e) {
    showToast('Could not remove: ' + e.message, 'error');
  }
}

/* ── save ──────────────────────────────────────────────────────────────── */

els.form.addEventListener('submit', async e => {
  e.preventDefault();
  if (saving) return;
  els.error.textContent = '';
  if (!selection) { els.error.textContent = 'Select a room on the map or draw an area first.'; return; }
  const endsAt = fromLocalInput(els.ends.value);
  if (endsAt === 'invalid') { els.error.textContent = 'The end date is not valid.'; return; }
  if (endsAt && new Date(endsAt) <= new Date()) { els.error.textContent = 'The end date must be in the future.'; return; }
  const note = els.note.value.trim();
  if (note.length > 200) { els.error.textContent = 'The note is too long (max 200 characters).'; return; }
  const body = {
    floor: selection.floor,
    roomId: selection.roomId || null,
    polygon: selection.polygon || null,
    status: els.status.value,
    note,
    endsAt,
    startsAt: editing ? editing.startsAt : null,
  };
  saving = true;
  els.save.disabled = true;
  els.save.textContent = 'Saving…';
  try {
    if (editing) await api(`/admin/api/closures/${editing.id}`, { method: 'PUT', json: body });
    else await api('/admin/api/closures', { method: 'POST', json: body });
    showToast('Saved — visitors see it now.', 'ok');
    resetForm();
    await loadClosures();
  } catch (err) {
    els.error.textContent = err.message;
  } finally {
    saving = false;
    els.save.disabled = false;
    els.save.textContent = editing ? 'Save changes' : 'Save';
  }
});

els.reset.addEventListener('click', () => { fm.cancelDraw(); resetForm(); });
els.draw.addEventListener('click', drawArea);
els.drawCancel.addEventListener('click', () => fm.cancelDraw());

/* ── boot ──────────────────────────────────────────────────────────────── */

(async function init() {
  try {
    const res = await fetch('/rooms.json', { cache: 'no-cache', credentials: 'same-origin' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    MAP = await res.json();
  } catch (e) {
    els.map.textContent = '';
    const p = document.createElement('p');
    p.className = 'empty-state';
    p.textContent = 'Could not load the map data: ' + e.message;
    els.map.appendChild(p);
    return;
  }
  fm = new FloorMap(els.map, {
    data: MAP,
    mode: 'admin',
    initialFloor: MAP.kiosk ? MAP.kiosk.floor : 1,
    onRoomClick: room => setSelection({ floor: room.floor, roomId: room.id }),
    onAreaClick: c => startEdit(c),
    onFloorChange: () => {
      if (!fm) return;
      fm.cancelDraw();
      if (selection && selection.floor !== fm.current && !editing) setSelection(null);
    },
  });
  await loadClosures();
})();
