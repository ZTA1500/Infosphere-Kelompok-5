"""SQLite storage for page visits, site feedback, and admin sessions.

Every query here uses `?` placeholders — never string formatting with user
input. The schema is versioned with PRAGMA user_version; `init_db()` applies
any pending migrations and is safe to call on every startup.
"""
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta

from server.paths import instance_file

DB_PATH  = os.environ.get('INFOSPHERE_DB') or instance_file('infosphere.db')

# Legacy flat-file stores, imported once (and left untouched) on first run.
LEGACY_VISITS_FILE   = instance_file('visits.json')
LEGACY_FEEDBACK_FILE = instance_file('site_feedback.json')

MIGRATIONS = {
    1: """
    CREATE TABLE IF NOT EXISTS visits (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        ts       TEXT NOT NULL,              -- local ISO timestamp
        day      TEXT NOT NULL,              -- YYYY-MM-DD, for daily grouping
        path     TEXT NOT NULL,
        visitor  TEXT NOT NULL,              -- keyed hash of IP+UA, never the raw IP
        referrer TEXT NOT NULL DEFAULT '',   -- referring host only
        device   TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_visits_day ON visits(day);

    CREATE TABLE IF NOT EXISTS feedback (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        ts       TEXT NOT NULL,
        name     TEXT NOT NULL DEFAULT '',
        email    TEXT NOT NULL DEFAULT '',
        category TEXT NOT NULL DEFAULT 'Other',
        message  TEXT NOT NULL,
        rating   INTEGER,
        page     TEXT NOT NULL DEFAULT '',
        is_read  INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_feedback_read ON feedback(is_read);

    CREATE TABLE IF NOT EXISTS admin_sessions (
        id         TEXT PRIMARY KEY,         -- SHA-256 of the cookie token
        created_at REAL NOT NULL,
        last_seen  REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS meta (
        key   TEXT PRIMARY KEY,
        value TEXT
    );
    """,
    2: """
    CREATE TABLE IF NOT EXISTS closures (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        floor      INTEGER NOT NULL,
        room_id    TEXT,                     -- a room from data/rooms.json ...
        polygon    TEXT,                     -- ... or a drawn area: JSON [[x,y],...]
        status     TEXT NOT NULL CHECK (status IN ('closed', 'under_construction')),
        note       TEXT NOT NULL DEFAULT '',
        starts_at  TEXT NOT NULL,            -- UTC 'YYYY-MM-DDTHH:MM:SSZ'
        ends_at    TEXT,                     -- NULL = until an admin removes it
        updated_by TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL,
        CHECK ((room_id IS NULL) <> (polygon IS NULL))
    );
    CREATE INDEX IF NOT EXISTS idx_closures_floor ON closures(floor);
    """,
}


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def _db():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Create the database, apply pending migrations, import legacy JSON once."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with _db() as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        current = conn.execute('PRAGMA user_version').fetchone()[0]
        for version in sorted(v for v in MIGRATIONS if v > current):
            conn.executescript(MIGRATIONS[version])
            conn.execute(f'PRAGMA user_version = {int(version)}')
            print(f'[DB] Applied migration {version}')
    _import_legacy_json()
    print(f'[DB] Ready: {DB_PATH}')


def _load_json_list(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _import_legacy_json():
    with _db() as conn:
        done = {r['key'] for r in conn.execute("SELECT key FROM meta")}

        if 'imported_visits_json' not in done and os.path.exists(LEGACY_VISITS_FILE):
            rows = []
            for v in _load_json_list(LEGACY_VISITS_FILE):
                ts = str(v.get('timestamp') or '')
                if len(ts) < 10:
                    continue
                rows.append((ts, ts[:10], str(v.get('path') or '')[:200],
                             str(v.get('visitor') or '')[:64],
                             _referrer_host(v.get('referrer')), str(v.get('device') or '')[:60]))
            conn.executemany(
                "INSERT INTO visits (ts, day, path, visitor, referrer, device) VALUES (?,?,?,?,?,?)", rows)
            conn.execute("INSERT INTO meta (key, value) VALUES ('imported_visits_json', ?)", (str(len(rows)),))
            print(f'[DB] Imported {len(rows)} visit(s) from visits.json (file left in place).')

        if 'imported_feedback_json' not in done and os.path.exists(LEGACY_FEEDBACK_FILE):
            rows = []
            for f in _load_json_list(LEGACY_FEEDBACK_FILE):
                msg = str(f.get('message') or '').strip()
                if not msg:
                    continue
                rating = f.get('rating')
                rows.append((str(f.get('timestamp') or datetime.now().isoformat()),
                             str(f.get('name') or '')[:100], str(f.get('email') or '')[:254],
                             str(f.get('category') or 'Other')[:20], msg[:2000],
                             rating if isinstance(rating, int) and 1 <= rating <= 5 else None,
                             str(f.get('page') or '')[:300]))
            conn.executemany(
                "INSERT INTO feedback (ts, name, email, category, message, rating, page) "
                "VALUES (?,?,?,?,?,?,?)", rows)
            conn.execute("INSERT INTO meta (key, value) VALUES ('imported_feedback_json', ?)", (str(len(rows)),))
            print(f'[DB] Imported {len(rows)} feedback item(s) from site_feedback.json (file left in place).')


def _referrer_host(ref):
    """Keep only the referring host — full URLs can carry query strings/PII."""
    from urllib.parse import urlsplit
    try:
        return (urlsplit(str(ref or '')).hostname or '')[:120]
    except ValueError:
        return ''


# ── Visits ─────────────────────────────────────────────────────────────────────

def add_visit(path, visitor, referrer, device):
    now = datetime.now()
    with _db() as conn:
        conn.execute(
            "INSERT INTO visits (ts, day, path, visitor, referrer, device) VALUES (?,?,?,?,?,?)",
            (now.isoformat(timespec='seconds'), now.date().isoformat(), path[:200],
             visitor, _referrer_host(referrer), device[:60]))


def visit_stats(chart_days=30):
    today      = date.today()
    week_start = (today - timedelta(days=6)).isoformat()      # today + previous 6 days
    chart_from = today - timedelta(days=chart_days - 1)
    with _db() as conn:
        def one(sql, *a):
            return conn.execute(sql, a).fetchone()[0]
        total        = one("SELECT COUNT(*) FROM visits")
        unique       = one("SELECT COUNT(DISTINCT visitor) FROM visits")
        today_n      = one("SELECT COUNT(*) FROM visits WHERE day = ?", today.isoformat())
        unique_today = one("SELECT COUNT(DISTINCT visitor) FROM visits WHERE day = ?", today.isoformat())
        week_n       = one("SELECT COUNT(*) FROM visits WHERE day >= ?", week_start)
        top_pages = [{'path': r['path'], 'n': r['n']} for r in conn.execute(
            "SELECT path, COUNT(*) AS n FROM visits GROUP BY path ORDER BY n DESC LIMIT 8")]
        devices = {r['device'] or 'Unknown': r['n'] for r in conn.execute(
            "SELECT device, COUNT(*) AS n FROM visits GROUP BY device ORDER BY n DESC")}
        per_day = {r['day']: r['n'] for r in conn.execute(
            "SELECT day, COUNT(*) AS n FROM visits WHERE day >= ? GROUP BY day",
            (chart_from.isoformat(),))}

    # Fill gaps so the chart shows every day, including zero-visit ones.
    by_day = []
    for i in range(chart_days):
        d = (chart_from + timedelta(days=i)).isoformat()
        by_day.append({'date': d, 'n': per_day.get(d, 0)})

    return {
        'total':           total,
        'unique_visitors': unique,
        'today':           today_n,
        'unique_today':    unique_today,
        'last_7_days':     week_n,
        'top_pages':       top_pages,
        'devices':         devices,
        'by_day':          by_day,
    }


# ── Feedback ───────────────────────────────────────────────────────────────────

FEEDBACK_CATEGORIES = ('Bug', 'Suggestion', 'Compliment', 'Complaint', 'Other')


def add_feedback(name, email, category, message, rating, page):
    with _db() as conn:
        cur = conn.execute(
            "INSERT INTO feedback (ts, name, email, category, message, rating, page) "
            "VALUES (?,?,?,?,?,?,?)",
            (datetime.now().isoformat(timespec='seconds'), name, email, category,
             message, rating, page))
        return cur.lastrowid


def feedback_summary():
    with _db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS total, "
            "       COALESCE(SUM(CASE WHEN is_read = 0 THEN 1 ELSE 0 END), 0) AS unread, "
            "       AVG(rating) AS avg_rating "
            "FROM feedback").fetchone()
        by_category = {r['category']: r['n'] for r in conn.execute(
            "SELECT category, COUNT(*) AS n FROM feedback GROUP BY category ORDER BY n DESC")}
    return {
        'total':       row['total'],
        'unread':      row['unread'],
        'avg_rating':  round(row['avg_rating'], 1) if row['avg_rating'] is not None else None,
        'by_category': by_category,
    }


def list_feedback(page=1, per_page=10, status='all', category=''):
    where, args = [], []
    if status == 'unread':
        where.append("is_read = 0")
    elif status == 'read':
        where.append("is_read = 1")
    if category in FEEDBACK_CATEGORIES:
        where.append("category = ?")
        args.append(category)
    # Only fixed SQL fragments are joined here; every value is a ? parameter.
    clause = (" WHERE " + " AND ".join(where)) if where else ""

    with _db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM feedback" + clause, args).fetchone()[0]  # noqa: S608
        pages = max(1, -(-total // per_page))
        page  = min(max(1, page), pages)
        rows  = conn.execute(
            "SELECT id, ts, name, email, category, message, rating, page, is_read FROM feedback"  # noqa: S608
            + clause + " ORDER BY id DESC LIMIT ? OFFSET ?",
            args + [per_page, (page - 1) * per_page]).fetchall()

    items = [{
        'id': r['id'], 'timestamp': r['ts'], 'name': r['name'], 'email': r['email'],
        'category': r['category'], 'message': r['message'], 'rating': r['rating'],
        'page': r['page'], 'read': bool(r['is_read']),
    } for r in rows]
    return {'items': items, 'page': page, 'pages': pages, 'per_page': per_page, 'total': total}


def set_feedback_read(feedback_id, read=True):
    with _db() as conn:
        cur = conn.execute("UPDATE feedback SET is_read = ? WHERE id = ?", (1 if read else 0, feedback_id))
        return cur.rowcount > 0


def mark_all_feedback_read():
    with _db() as conn:
        return conn.execute("UPDATE feedback SET is_read = 1 WHERE is_read = 0").rowcount


def delete_feedback(feedback_id):
    with _db() as conn:
        return conn.execute("DELETE FROM feedback WHERE id = ?", (feedback_id,)).rowcount > 0


# ── Admin sessions (server-side, so logout really revokes the cookie) ─────────

def create_admin_session(session_hash):
    now = time.time()
    with _db() as conn:
        conn.execute("INSERT INTO admin_sessions (id, created_at, last_seen) VALUES (?,?,?)",
                     (session_hash, now, now))


def get_admin_session(session_hash):
    with _db() as conn:
        row = conn.execute("SELECT created_at, last_seen FROM admin_sessions WHERE id = ?",
                           (session_hash,)).fetchone()
    return dict(row) if row else None


def touch_admin_session(session_hash):
    with _db() as conn:
        conn.execute("UPDATE admin_sessions SET last_seen = ? WHERE id = ?", (time.time(), session_hash))


def delete_admin_session(session_hash):
    with _db() as conn:
        conn.execute("DELETE FROM admin_sessions WHERE id = ?", (session_hash,))


def purge_admin_sessions(idle_seconds, max_age_seconds):
    now = time.time()
    with _db() as conn:
        conn.execute("DELETE FROM admin_sessions WHERE last_seen < ? OR created_at < ?",
                     (now - idle_seconds, now - max_age_seconds))


def revoke_all_admin_sessions():
    with _db() as conn:
        return conn.execute("DELETE FROM admin_sessions").rowcount


# ── Area closures ("Closed" / "Under construction") ───────────────────────────

CLOSURE_STATUSES = ('closed', 'under_construction')
_CLOSURE_COLS = "id, floor, room_id, polygon, status, note, starts_at, ends_at, updated_by, updated_at"


def _closure_row(r):
    return {
        'id': r['id'], 'floor': r['floor'], 'room_id': r['room_id'],
        'polygon': json.loads(r['polygon']) if r['polygon'] else None,
        'status': r['status'], 'note': r['note'], 'starts_at': r['starts_at'],
        'ends_at': r['ends_at'], 'updated_by': r['updated_by'], 'updated_at': r['updated_at'],
    }


def list_closures(now_iso, include_scheduled=False):
    """Closures that haven't ended. `include_scheduled` also returns ones that
    start in the future (admin view); the public view only gets active ones."""
    sql = f"SELECT {_CLOSURE_COLS} FROM closures WHERE (ends_at IS NULL OR ends_at > ?)"  # noqa: S608 (constant columns)
    args = [now_iso]
    if not include_scheduled:
        sql += " AND starts_at <= ?"
        args.append(now_iso)
    with _db() as conn:
        return [_closure_row(r) for r in conn.execute(sql + " ORDER BY floor, id", args)]


def get_closure(closure_id):
    with _db() as conn:
        r = conn.execute(f"SELECT {_CLOSURE_COLS} FROM closures WHERE id = ?",  # noqa: S608 (constant columns)
                         (closure_id,)).fetchone()
    return _closure_row(r) if r else None


def add_closure(c):
    with _db() as conn:
        cur = conn.execute(
            "INSERT INTO closures (floor, room_id, polygon, status, note, starts_at, ends_at, updated_by, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (c['floor'], c['room_id'], json.dumps(c['polygon']) if c['polygon'] else None, c['status'],
             c['note'], c['starts_at'], c['ends_at'], c['updated_by'], c['updated_at']))
        return cur.lastrowid


def update_closure(closure_id, c):
    with _db() as conn:
        cur = conn.execute(
            "UPDATE closures SET floor = ?, room_id = ?, polygon = ?, status = ?, note = ?, starts_at = ?, "
            "ends_at = ?, updated_by = ?, updated_at = ? WHERE id = ?",
            (c['floor'], c['room_id'], json.dumps(c['polygon']) if c['polygon'] else None, c['status'],
             c['note'], c['starts_at'], c['ends_at'], c['updated_by'], c['updated_at'], closure_id))
        return cur.rowcount > 0


def delete_closure(closure_id):
    with _db() as conn:
        return conn.execute("DELETE FROM closures WHERE id = ?", (closure_id,)).rowcount > 0
