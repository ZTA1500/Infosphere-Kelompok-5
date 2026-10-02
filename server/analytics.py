import json
import os
import threading
from datetime import datetime, date
from collections import Counter, defaultdict

from server import db
from server.paths import instance_file

LOG_FILE  = instance_file('query_logs.json')

_lock = threading.Lock()


# ── Internal I/O for the chatbot query log (flat JSON file) ────────────────────

def _load(path):
    if not os.path.exists(path):
        return []
    with open(path, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except Exception:
            return []


def _save(path, logs):
    """Atomic write: write to .tmp then rename so the file is never half-written."""
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(logs, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _append(path, lock, entry):
    """Thread-safe append. Runs on a background thread — never blocks callers."""
    with lock:
        logs = _load(path)
        logs.append(entry)
        _save(path, logs)


# ── Public logging API ─────────────────────────────────────────────────────────

def log_query(question, answer, confidence, lang, response_time_ms, matched_room=None, found=None):
    entry = {
        'type':         'query',
        'timestamp':    datetime.now().isoformat(),
        'question':     question,
        'answer':       answer[:200],
        'confidence':   round(float(confidence), 3),
        'language':     lang,
        'response_ms':  int(response_time_ms),
        'matched_room': matched_room,
        'found':        bool(found) if found is not None else None,
    }
    threading.Thread(target=_append, args=(LOG_FILE, _lock, entry), daemon=True).start()


def log_feedback(question, positive):
    entry = {
        'type':      'feedback',
        'timestamp': datetime.now().isoformat(),
        'question':  question,
        'positive':  bool(positive),
    }
    threading.Thread(target=_append, args=(LOG_FILE, _lock, entry), daemon=True).start()


def log_visit(path, visitor, referrer=None, user_agent=None):
    """One page view. `visitor` is a keyed hash, never a raw IP. Never raises —
    a tracking failure must not break the page being served."""
    try:
        db.add_visit(path, visitor, referrer or '', _classify_ua(user_agent or ''))
    except Exception as e:
        print(f'[Analytics] visit not recorded: {e}')


def _classify_ua(ua):
    """Coarse device/browser bucket — enough for a chart, not a fingerprint."""
    ua = ua.lower()
    device = 'Mobile' if any(k in ua for k in ('mobi', 'android', 'iphone')) else 'Desktop'
    if 'edg' in ua:        browser = 'Edge'
    elif 'chrome' in ua:   browser = 'Chrome'
    elif 'firefox' in ua:  browser = 'Firefox'
    elif 'safari' in ua:   browser = 'Safari'
    else:                  browser = 'Other'
    return f'{device} · {browser}'


def log_site_feedback(name, email, category, message, rating, page_url):
    """Store one feedback submission (already validated by the caller). Returns its id."""
    return db.add_feedback(
        name=(name or '').strip()[:100],
        email=(email or '').strip()[:254],
        category=category or 'Other',
        message=(message or '').strip()[:2000],
        rating=rating,
        page=(page_url or '')[:300],
    )


# ── Stats computation (used by /admin/stats) ───────────────────────────────────

def get_stats():
    with _lock:
        logs = _load(LOG_FILE)

    queries  = [e for e in logs if e.get('type') == 'query']
    feedback = [e for e in logs if e.get('type') == 'feedback']

    today_str = date.today().isoformat()
    today_qs  = [q for q in queries if q.get('timestamp', '').startswith(today_str)]

    n = max(len(queries), 1)
    avg_ms   = sum(q.get('response_ms', 0) for q in queries) / n
    avg_conf = sum(q.get('confidence', 0) for q in queries) / n

    # Language breakdown
    langs = Counter(q.get('language', 'IND') for q in queries)

    # Confidence buckets (all time, not just recent)
    conf_buckets = {'0-25': 0, '26-50': 0, '51-75': 0, '76-100': 0}
    for q in queries:
        c = q.get('confidence', 0) * 100
        if   c <= 25: conf_buckets['0-25']   += 1
        elif c <= 50: conf_buckets['26-50']  += 1
        elif c <= 75: conf_buckets['51-75']  += 1
        else:         conf_buckets['76-100'] += 1

    # Top 5 most-asked questions
    top_qs = [
        {'q': q, 'n': cnt}
        for q, cnt in Counter(q.get('question', '') for q in queries).most_common(5)
        if q
    ]

    # Hourly distribution (24-hour heatmap, all time)
    hourly = defaultdict(int)
    for q in queries:
        ts = q.get('timestamp', '')
        if ts:
            try:
                hourly[datetime.fromisoformat(ts).hour] += 1
            except Exception:
                pass

    # Feedback
    fb_pos = sum(1 for f in feedback if f.get('positive'))
    fb_neg = len(feedback) - fb_pos

    # Unanswered / low-confidence questions → what the dataset is missing.
    # An entry is "unanswered" if it was flagged found=False, or (for older logs
    # without the flag) if its confidence was low.
    def _is_unanswered(q):
        f = q.get('found')
        if f is not None:
            return not f
        return q.get('confidence', 0) < 0.40

    unanswered_counter = Counter(
        (q.get('question') or '').strip()
        for q in queries if _is_unanswered(q) and (q.get('question') or '').strip()
    )
    unanswered = [
        {'q': q, 'n': cnt}
        for q, cnt in unanswered_counter.most_common(15)
    ]

    return {
        'total':            len(queries),
        'today':            len(today_qs),
        'avg_ms':           round(avg_ms),
        'avg_conf':         round(avg_conf * 100, 1),
        'lang_counts':      dict(langs),
        'conf_buckets':     conf_buckets,
        'top_questions':    top_qs,
        'feedback_pos':     fb_pos,
        'feedback_neg':     fb_neg,
        'hourly':           {str(h): hourly[h] for h in range(24)},
        'recent':           queries[-20:][::-1],
        'unanswered':       unanswered,
        'unanswered_total': sum(unanswered_counter.values()),
    }


def get_all_logs():
    """Return the full log list for CSV export."""
    with _lock:
        return _load(LOG_FILE)


def get_visit_stats():
    return db.visit_stats(chart_days=30)


def get_site_feedback(page=1, per_page=10, status='all', category=''):
    """Summary numbers plus one page of submissions, newest first."""
    summary = db.feedback_summary()              # total / unread / avg_rating / by_category
    listing = db.list_feedback(page=page, per_page=per_page, status=status, category=category)
    return {
        **summary,
        'items':    listing['items'],
        'filtered': listing['total'],            # matches for the current filter
        'page':     listing['page'],
        'pages':    listing['pages'],
        'per_page': listing['per_page'],
    }
