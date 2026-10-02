/* Admin dashboard: site summary cards, chatbot stats, and visits. */

let charts = {};

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

/* ── Site summary (visits + feedback cards) ───────────────────────────── */
async function loadSummary() {
  try {
    const d = await api('/admin/summary');
    setText('s-visits-total', d.visits_total);
    setText('s-visits-today', d.visits_today);
    setText('s-visits-7d', d.visits_7d);
    setText('s-unique', d.unique_visitors);
    setText('s-fb-total', d.feedback_total);
    setText('s-fb-unread', d.feedback_unread);
    setText('s-fb-unread-sub', d.feedback_unread ? 'waiting for review' : 'all caught up');
    setUnreadBadge(d.feedback_unread);
  } catch (e) {
    showToast('Failed to load summary: ' + e.message, 'error');
  }
}

/* ── Chatbot stats ────────────────────────────────────────────────────── */
async function loadStats() {
  try {
    const d = await api('/admin/stats');

    setText('val-total', d.total ?? '—');
    setText('val-today', d.today ?? '—');
    setText('sub-today', d.today === 1 ? '1 query today' : (d.today ?? 0) + ' queries today');
    setText('val-ms', d.avg_ms != null ? d.avg_ms + ' ms' : '—');
    setText('val-conf', d.avg_conf != null ? d.avg_conf + '%' : '—');
    setText('last-updated', '↻ updated ' + new Date().toLocaleTimeString('id-ID'));

    renderLangChart(d.lang_counts   || {});
    renderConfChart(d.conf_buckets  || {});
    renderHourlyChart(d.hourly      || {});
    renderFeedback(d.feedback_pos   ?? 0, d.feedback_neg ?? 0);
    renderTopQ(d.top_questions      || []);
    renderUnanswered(d.unanswered   || [], d.unanswered_total ?? 0);
    renderTable(d.recent            || []);
  } catch (e) {
    showToast('Failed to load: ' + e.message, 'error');
  }
}

function _mkChart(id, config) {
  if (charts[id]) charts[id].destroy();
  charts[id] = new Chart(document.getElementById(id), config);
}

function renderLangChart(counts) {
  _mkChart('lang-chart', {
    type: 'doughnut',
    data: {
      labels: Object.keys(counts),
      datasets: [{
        data: Object.values(counts),
        backgroundColor: ['#1a6bb3', '#2f9e64', '#c9821f', '#6a4fb3'],
        borderWidth: 2, borderColor: '#fff',
      }],
    },
    options: {
      plugins: { legend: { position: 'bottom', labels: { padding: 10, boxWidth: 12 } } },
      cutout: '62%',
    },
  });
}

function renderConfChart(buckets) {
  _mkChart('conf-chart', {
    type: 'bar',
    data: {
      labels: Object.keys(buckets).map(k => k + '%'),
      datasets: [{
        data: Object.values(buckets),
        backgroundColor: ['#d6465a', '#c9821f', '#d9b23c', '#2f9e64'],
        borderRadius: 6, borderWidth: 0,
      }],
    },
    options: {
      plugins: { legend: { display: false } },
      scales: { y: { beginAtZero: true, ticks: { stepSize: 1 } } },
    },
  });
}

function renderHourlyChart(hourly) {
  const labels = Array.from({ length: 24 }, (_, h) => h + ':00');
  _mkChart('hourly-chart', {
    type: 'line',
    data: {
      labels,
      datasets: [{
        data: labels.map((_, h) => hourly[String(h)] ?? 0),
        borderColor: '#1a6bb3', backgroundColor: 'rgba(33,131,217,.12)',
        borderWidth: 2, pointRadius: 3, fill: true, tension: 0.4,
      }],
    },
    options: {
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { maxTicksLimit: 8, font: { size: 9 } } },
        y: { beginAtZero: true, ticks: { stepSize: 1 } },
      },
    },
  });
}

function renderFeedback(pos, neg) {
  setText('fb-pos', pos);
  setText('fb-neg', neg);
  const total = pos + neg;
  const pct = total > 0 ? Math.round((pos / total) * 100) : 50;
  document.getElementById('fb-bar').style.width = pct + '%';
}

function renderTopQ(topqs) {
  const el = document.getElementById('topq-list');
  if (!topqs.length) {
    el.innerHTML = '<p style="color:var(--gray);font-size:.82rem">No data yet.</p>';
    return;
  }
  const maxN = topqs[0]?.n || 1;
  el.innerHTML = topqs.map((item, i) => `
    <div class="topq-item">
      <div class="topq-rank">${i + 1}</div>
      <div class="topq-text" title="${escHtml(item.q)}">${escHtml(item.q)}</div>
      <div class="topq-bar-wrap">
        <div class="topq-bar-fill" style="width:${Math.round((item.n / maxN) * 100)}%"></div>
      </div>
      <div class="topq-count">${Number(item.n)}×</div>
    </div>`).join('');
}

function renderUnanswered(items, total) {
  const el = document.getElementById('unanswered-list');
  setText('unanswered-total', total ? `${total} unanswered hit(s)` : '');
  if (!items.length) {
    el.innerHTML = '<p style="color:var(--green);font-size:.82rem">🎉 Nothing unanswered — the dataset is covering everything asked.</p>';
    return;
  }
  el.innerHTML = items.map(item => {
    const q = escHtml(item.q);
    return `<div class="unans-item">
      <div class="unans-q" title="${q}">${q}</div>
      <div class="unans-n">${Number(item.n)}×</div>
      <input class="unans-input" type="text" placeholder="Correct answer for this question…"
             data-q="${q}" maxlength="1000">
      <button class="unans-btn" type="button">Teach</button>
    </div>`;
  }).join('');
}

async function teachAnswer(inputEl) {
  const question = inputEl.getAttribute('data-q');
  const answer   = inputEl.value.trim();
  if (!answer) { showToast('Type an answer first'); inputEl.focus(); return; }
  const btn = inputEl.nextElementSibling;
  if (btn) { btn.disabled = true; btn.textContent = '…'; }
  try {
    const data = await api('/admin/teach', { method: 'POST', json: { question, answer } });
    if (data.status === 'ok') {
      showToast('Taught & retrained ✓', 'ok');
      loadStats();
    } else {
      throw new Error(data.message || 'error');
    }
  } catch (e) {
    showToast('Failed: ' + e.message, 'error');
    if (btn) { btn.disabled = false; btn.textContent = 'Teach'; }
  }
}

function renderTable(logs) {
  const tbody = document.getElementById('recent-body');
  if (!logs.length) {
    tbody.innerHTML = '<tr><td colspan="6" style="color:var(--gray);text-align:center;padding:20px">No queries yet.</td></tr>';
    return;
  }
  const badge = { 'IND': 'badge-ind', 'ENG': 'badge-eng', 'ZH': 'badge-zh' };
  tbody.innerHTML = logs.map(l => {
    const ts   = l.timestamp ? new Date(l.timestamp).toLocaleString('id-ID') : '—';
    const conf = Math.round((l.confidence || 0) * 100);
    const barW = Math.round(conf * 0.5);
    return `<tr>
      <td class="td-sm">${escHtml(ts)}</td>
      <td class="td-trunc">${escHtml(l.question || '—')}</td>
      <td class="td-trunc">${escHtml(l.answer   || '—')}</td>
      <td>
        <div class="conf-bar-wrap">
          <div class="conf-bar-fill" style="width:${barW}px"></div>
          <span class="td-sm">${conf}%</span>
        </div>
      </td>
      <td><span class="badge ${badge[l.language] || 'badge-ind'}">${escHtml(l.language || '—')}</span></td>
      <td class="td-sm">${Number(l.response_ms) || '—'}</td>
    </tr>`;
  }).join('');
}

/* Cells starting with = + - @ are treated as formulas by Excel/Sheets, so a
   visitor's question like "=HYPERLINK(...)" could run when the CSV is opened.
   Prefixing with an apostrophe makes the spreadsheet show it as plain text. */
function csvCell(value) {
  let s = String(value ?? '');
  if (/^[=+\-@\t\r]/.test(s)) s = "'" + s;
  return '"' + s.replace(/"/g, '""') + '"';
}

async function exportCSV() {
  try {
    const logs = await api('/admin/export');
    const queries = (logs || []).filter(l => l.type === 'query');
    if (!queries.length) { showToast('No query data to export'); return; }

    const cols = ['timestamp', 'question', 'answer', 'confidence', 'language', 'response_ms', 'matched_room'];
    const csv  = [cols.join(','), ...queries.map(l => cols.map(k => csvCell(l[k])).join(','))].join('\n');

    const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' });
    const a    = Object.assign(document.createElement('a'), {
      href:     URL.createObjectURL(blob),
      download: 'infosphere_' + new Date().toISOString().slice(0, 10) + '.csv',
    });
    a.click();
    showToast(`Exported ${queries.length} queries`, 'ok');
  } catch (e) {
    showToast('Export failed: ' + e.message, 'error');
  }
}

async function retrainModel() {
  if (!confirm('Retrain the chatbot model? This may take a minute.')) return;
  showToast('Retraining… please wait.');
  try {
    const data = await api('/admin/retrain', { method: 'POST' });
    showToast(data.status === 'ok' ? 'Model retrained successfully!' : 'Retrain failed: ' + data.message,
              data.status === 'ok' ? 'ok' : 'error');
  } catch (e) {
    showToast('Error: ' + e.message, 'error');
  }
}

/* ── Tabs ─────────────────────────────────────────────────────────────── */
function switchTab(name) {
  document.querySelectorAll('.tab-btn').forEach(b => {
    const on = b.dataset.tab === name;
    b.classList.toggle('active', on);
    b.setAttribute('aria-selected', on ? 'true' : 'false');
  });
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('active', p.dataset.tab === name));
  // Chart.js can't size a canvas inside a hidden panel; resize once it's visible.
  Object.values(charts).forEach(c => c.resize());
}

/* ── Visits ───────────────────────────────────────────────────────────── */
async function loadVisits() {
  try {
    const d = await api('/admin/visits');

    setText('v-total', d.total ?? '—');
    setText('v-unique', d.unique_visitors ?? '—');
    setText('v-today', d.today ?? '—');
    setText('v-7d', d.last_7_days ?? '—');
    setText('v-today-unique', d.unique_today != null ? `${d.unique_today} unique visitor${d.unique_today === 1 ? '' : 's'}` : '');

    const byDay = d.by_day || [];
    const sum30 = byDay.reduce((acc, x) => acc + x.n, 0);
    setText('v-30d-total', `${sum30} visit${sum30 === 1 ? '' : 's'} in the last 30 days`);

    renderVisitsChart(byDay);
    renderDeviceChart(d.devices || {});
    renderTopPages(d.top_pages || []);
  } catch (e) {
    showToast('Failed to load visits: ' + e.message, 'error');
  }
}

function renderVisitsChart(byDay) {
  _mkChart('visits-chart', {
    type: 'bar',
    data: {
      labels: byDay.map(d => d.date.slice(5)),   // MM-DD
      datasets: [{
        data: byDay.map(d => d.n),
        backgroundColor: 'rgba(33,131,217,.55)',
        hoverBackgroundColor: '#1a6bb3',
        borderRadius: 4, borderWidth: 0, maxBarThickness: 18,
      }],
    },
    options: {
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { title: items => byDay[items[0].dataIndex].date,
                                label: item => `${item.parsed.y} visit${item.parsed.y === 1 ? '' : 's'}` } },
      },
      scales: {
        x: { grid: { display: false }, ticks: { maxTicksLimit: 10, font: { size: 10 } } },
        y: { beginAtZero: true, ticks: { precision: 0 } },
      },
    },
  });
}

function renderDeviceChart(devices) {
  _mkChart('device-chart', {
    type: 'doughnut',
    data: {
      labels: Object.keys(devices),
      datasets: [{
        data: Object.values(devices),
        backgroundColor: ['#1a6bb3', '#2f9e64', '#c9821f', '#6a4fb3', '#4a9ee6', '#d6465a'],
        borderWidth: 2, borderColor: '#fff',
      }],
    },
    options: {
      plugins: { legend: { position: 'bottom', labels: { font: { size: 10 }, padding: 8, boxWidth: 10 } } },
      cutout: '58%',
    },
  });
}

function renderTopPages(pages) {
  const el = document.getElementById('top-pages-list');
  if (!pages.length) {
    el.innerHTML = '<p style="color:var(--gray);font-size:.82rem">No visits recorded yet.</p>';
    return;
  }
  const maxN = pages[0]?.n || 1;
  el.innerHTML = pages.map(p => `
    <div class="topq-item">
      <div class="topq-text" title="${escHtml(p.path)}">${escHtml(p.path)}</div>
      <div class="topq-bar-wrap">
        <div class="topq-bar-fill" style="width:${Math.round((p.n / maxN) * 100)}%"></div>
      </div>
      <div class="topq-count">${Number(p.n)}×</div>
    </div>`).join('');
}

/* ── Wiring ───────────────────────────────────────────────────────────── */
function refreshAll() {
  loadSummary();
  loadStats();
  loadVisits();
}

document.getElementById('btn-refresh').addEventListener('click', refreshAll);
document.getElementById('btn-export').addEventListener('click', exportCSV);
document.getElementById('btn-retrain').addEventListener('click', retrainModel);
document.querySelectorAll('.tab-btn').forEach(b => b.addEventListener('click', () => switchTab(b.dataset.tab)));

const unansweredList = document.getElementById('unanswered-list');
unansweredList.addEventListener('click', e => {
  const btn = e.target.closest('.unans-btn');
  if (btn) teachAnswer(btn.previousElementSibling);
});
unansweredList.addEventListener('keydown', e => {
  if (e.key === 'Enter' && e.target.classList.contains('unans-input')) teachAnswer(e.target);
});

refreshAll();
setInterval(refreshAll, 30000);
