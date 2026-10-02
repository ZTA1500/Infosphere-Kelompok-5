/* Shared helpers for the admin pages. Loaded as an external file because the
   admin CSP forbids inline scripts. */

const CSRF_TOKEN = document.querySelector('meta[name="csrf-token"]')?.content || '';

/* fetch() wrapper: sends the CSRF token on state-changing requests and sends
   the admin back to the login page when the session has expired. */
async function api(url, options = {}) {
  const opts = { credentials: 'same-origin', ...options };
  const method = (opts.method || 'GET').toUpperCase();
  opts.headers = { ...(opts.headers || {}) };
  if (method !== 'GET') opts.headers['X-CSRF-Token'] = CSRF_TOKEN;
  if (opts.json !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(opts.json);
    delete opts.json;
  }
  const res = await fetch(url, opts);
  if (res.status === 401) {
    window.location.href = '/admin/login?next=' + encodeURIComponent(window.location.pathname);
    throw new Error('Session expired');
  }
  let data = null;
  try { data = await res.json(); } catch (_) { /* non-JSON body */ }
  if (!res.ok) throw new Error((data && data.message) || ('HTTP ' + res.status));
  return data;
}

function showToast(msg, type = '') {
  const t = document.getElementById('toast');
  if (!t) return;
  t.textContent = msg;
  t.className = 'toast show' + (type ? ' ' + type : '');
  clearTimeout(t._timer);
  t._timer = setTimeout(() => { t.className = 'toast'; }, 3500);
}

function escHtml(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function setUnreadBadge(n) {
  document.querySelectorAll('[data-unread-badge]').forEach(el => {
    el.textContent = n > 99 ? '99+' : String(n);
    el.hidden = !n;
  });
}

function fmtDateTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString('id-ID', { dateStyle: 'medium', timeStyle: 'short' });
}
