/* Admin feedback inbox: filter, paginate, mark read/unread, delete.
   Every piece of visitor-supplied text is inserted with textContent — never
   innerHTML — so a feedback message can't inject markup or script. */

const CATEGORIES = ['Bug', 'Suggestion', 'Compliment', 'Complaint', 'Other'];
const PER_PAGE = 10;

const params = new URLSearchParams(window.location.search);
const state = {
  page:     Math.max(1, parseInt(params.get('page'), 10) || 1),
  status:   ['all', 'unread', 'read'].includes(params.get('status')) ? params.get('status') : 'all',
  category: CATEGORIES.includes(params.get('category')) ? params.get('category') : '',
};

const listEl = document.getElementById('feedback-list');

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function syncUrl() {
  const q = new URLSearchParams();
  if (state.status !== 'all') q.set('status', state.status);
  if (state.category) q.set('category', state.category);
  if (state.page > 1) q.set('page', state.page);
  const qs = q.toString();
  history.replaceState(null, '', window.location.pathname + (qs ? '?' + qs : ''));
}

function syncControls() {
  document.querySelectorAll('.seg button').forEach(b =>
    b.setAttribute('aria-pressed', b.dataset.status === state.status ? 'true' : 'false'));
  document.getElementById('cat-filter').value = state.category;
}

async function loadFeedback() {
  syncUrl();
  syncControls();
  const q = new URLSearchParams({ page: state.page, per_page: PER_PAGE, status: state.status });
  if (state.category) q.set('category', state.category);
  try {
    const d = await api('/admin/site-feedback?' + q.toString());
    state.page = d.page;
    renderSummary(d);
    renderList(d.items || []);
    renderPager(d);
  } catch (e) {
    listEl.replaceChildren(el('p', 'empty-state', 'Could not load feedback: ' + e.message));
  }
}

function renderSummary(d) {
  document.getElementById('fb-total').textContent = d.total ?? '—';
  document.getElementById('fb-unread').textContent = d.unread ?? '—';
  document.getElementById('fb-avg-rating').textContent = d.avg_rating != null ? d.avg_rating + ' / 5' : '—';
  const cats = Object.entries(d.by_category || {}).sort((a, b) => b[1] - a[1]);
  document.getElementById('fb-top-cat').textContent = cats[0] ? cats[0][0] : '—';
  document.getElementById('fb-top-cat-n').textContent =
    cats[0] ? `${cats[0][1]} submission${cats[0][1] === 1 ? '' : 's'}` : ' ';
  document.getElementById('btn-read-all').disabled = !d.unread;
  setUnreadBadge(d.unread || 0);

  const n = d.filtered ?? 0;
  document.getElementById('inbox-count').textContent =
    `${n} ${state.status === 'all' ? '' : state.status + ' '}item${n === 1 ? '' : 's'}`;
}

function starRow(rating) {
  if (!rating) return el('span', 'td-sm', 'No rating');
  const wrap = el('span', 'fb-stars');
  wrap.setAttribute('aria-label', `${rating} out of 5 stars`);
  for (let i = 1; i <= 5; i++) wrap.appendChild(el('span', i <= rating ? '' : 'off', '★'));
  return wrap;
}

function pagePath(url) {
  try { return new URL(url).pathname; } catch (_) { return url; }
}

function renderCard(f) {
  const card = el('article', 'fb-card ' + (f.read ? 'read' : 'unread'));
  card.dataset.id = f.id;

  const head = el('div', 'fb-card-head');
  if (!f.read) head.appendChild(el('span', 'new-pill', 'NEW'));
  const cat = CATEGORIES.includes(f.category) ? f.category : 'Other';
  head.appendChild(el('span', 'badge-cat badge-' + cat, cat));
  head.appendChild(starRow(f.rating));
  const time = el('time', 'fb-card-time', fmtDateTime(f.timestamp));
  time.dateTime = f.timestamp || '';
  head.appendChild(time);
  card.appendChild(head);

  card.appendChild(el('div', 'fb-card-msg', f.message || ''));

  const foot = el('div', 'fb-card-foot');
  const meta = el('div', 'fb-card-meta');
  meta.appendChild(el('strong', null, f.name || 'Anonymous'));
  if (f.email) {
    meta.appendChild(document.createTextNode(' · '));
    // Contact is free text (IG, WhatsApp, …) — only link it when it looks like an email
    if (/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(f.email)) {
      const a = el('a', null, f.email);
      a.href = 'mailto:' + encodeURIComponent(f.email).replace(/%40/g, '@');
      meta.appendChild(a);
    } else {
      meta.appendChild(el('span', null, f.email));
    }
  }
  if (f.page) meta.appendChild(document.createTextNode(' · via ' + pagePath(f.page)));
  foot.appendChild(meta);

  const actions = el('div', 'fb-actions');
  const toggle = el('button', 'fb-act', f.read ? 'Mark as unread' : '✓ Mark as read');
  toggle.type = 'button';
  toggle.addEventListener('click', () => setRead(f.id, !f.read, toggle));
  const del = el('button', 'fb-act danger', 'Delete');
  del.type = 'button';
  del.addEventListener('click', () => deleteItem(f.id, card, del));
  actions.append(toggle, del);
  foot.appendChild(actions);
  card.appendChild(foot);
  return card;
}

function renderList(items) {
  if (!items.length) {
    const msg = state.status === 'unread' ? '🎉 No unread feedback — you\'re all caught up.'
              : (state.status === 'all' && !state.category) ? 'No feedback submitted yet.'
              : 'No feedback matches this filter.';
    listEl.replaceChildren(el('p', 'empty-state', msg));
    return;
  }
  listEl.replaceChildren(...items.map(renderCard));
}

function renderPager(d) {
  const pager = document.getElementById('pager');
  pager.hidden = d.pages <= 1;
  document.getElementById('page-info').textContent = `Page ${d.page} of ${d.pages}`;
  document.getElementById('page-prev').disabled = d.page <= 1;
  document.getElementById('page-next').disabled = d.page >= d.pages;
}

async function setRead(id, read, btn) {
  btn.disabled = true;
  try {
    await api(`/admin/site-feedback/${encodeURIComponent(id)}/read`, { method: 'POST', json: { read } });
    showToast(read ? 'Marked as read' : 'Marked as unread', 'ok');
    loadFeedback();
  } catch (e) {
    showToast('Failed: ' + e.message, 'error');
    btn.disabled = false;
  }
}

async function deleteItem(id, card, btn) {
  if (!confirm('Delete this feedback permanently? This cannot be undone.')) return;
  btn.disabled = true;
  try {
    await api(`/admin/site-feedback/${encodeURIComponent(id)}`, { method: 'DELETE' });
    card.classList.add('removing');
    showToast('Feedback deleted', 'ok');
    setTimeout(loadFeedback, 250);
  } catch (e) {
    showToast('Delete failed: ' + e.message, 'error');
    btn.disabled = false;
  }
}

async function markAllRead() {
  if (!confirm('Mark every feedback item as read?')) return;
  try {
    const d = await api('/admin/site-feedback/read-all', { method: 'POST' });
    showToast(`${d.updated} item${d.updated === 1 ? '' : 's'} marked as read`, 'ok');
    loadFeedback();
  } catch (e) {
    showToast('Failed: ' + e.message, 'error');
  }
}

/* ── Wiring ───────────────────────────────────────────────────────────── */
document.querySelectorAll('.seg button').forEach(b => b.addEventListener('click', () => {
  state.status = b.dataset.status;
  state.page = 1;
  loadFeedback();
}));
document.getElementById('cat-filter').addEventListener('change', e => {
  state.category = e.target.value;
  state.page = 1;
  loadFeedback();
});
document.getElementById('page-prev').addEventListener('click', () => { state.page--; loadFeedback(); window.scrollTo(0, 0); });
document.getElementById('page-next').addEventListener('click', () => { state.page++; loadFeedback(); window.scrollTo(0, 0); });
document.getElementById('btn-read-all').addEventListener('click', markAllRead);

loadFeedback();
