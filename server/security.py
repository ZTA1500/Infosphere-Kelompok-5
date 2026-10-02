"""Security plumbing for Infosphere: .env loading, admin login and sessions,
CSRF tokens, login lockout, rate limiting, and response security headers.

Configuration (environment variables or the .env file next to App.py):
  INFOSPHERE_ENV       'production' turns on HTTPS redirect, Secure cookies, HSTS
  SECRET_KEY           signs the session cookie (required in production)
  ADMIN_USER           admin username (default: admin)
  ADMIN_PASSWORD_HASH  scrypt/pbkdf2 hash — create it with scripts/set_admin_password.py
  TRUST_PROXY          '1' when running behind nginx/Caddy/a load balancer
  ADMIN_IDLE_MINUTES   idle timeout for admin sessions (default 30)
"""
import hashlib
import hmac
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from functools import wraps
from urllib.parse import urlsplit

from flask import abort, g, jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash


def load_env_file(path):
    """Minimal .env reader (KEY=VALUE per line). Real env vars take precedence."""
    if not os.path.exists(path):
        return
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, _, val = line.partition('=')
            key, val = key.strip(), val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in '"\'':
                val = val[1:-1]
            os.environ.setdefault(key, val)


def _env_flag(name, default=False):
    return os.environ.get(name, '1' if default else '0').strip().lower() in ('1', 'true', 'yes', 'on')


# ── Rate limiting (in-memory, per process) ─────────────────────────────────────

class RateLimiter:
    def __init__(self):
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()
        self._calls = 0

    def allow(self, key, limit, window_seconds):
        """Record a hit for `key`; False once `limit` hits land inside the window."""
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - window_seconds:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            self._calls += 1
            if self._calls % 1000 == 0:        # drop idle keys so memory stays bounded
                for k in [k for k, v in self._hits.items() if not v or v[-1] < now - 3600]:
                    del self._hits[k]
            return True


limiter = RateLimiter()


def client_ip():
    # With TRUST_PROXY=1, ProxyFix has already rewritten remote_addr from
    # X-Forwarded-For. Without it the header is ignored, so it can't be spoofed.
    return request.remote_addr or 'unknown'


def rate_limited(bucket, limit, window_seconds):
    """Decorator: 429 once one client exceeds `limit` calls per window."""
    def deco(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not limiter.allow(f'{bucket}:{client_ip()}', limit, window_seconds):
                return jsonify({'status': 'error', 'error': 'rate_limited',
                                'message': 'Too many requests — please wait a moment and try again.'}), 429
            return view(*args, **kwargs)
        return wrapper
    return deco


# ── Login lockout ──────────────────────────────────────────────────────────────

LOGIN_MAX_FAILS_PER_IP   = 5      # then lock that IP out
LOGIN_MAX_FAILS_ACCOUNT  = 20     # across all IPs, then lock the account briefly
LOGIN_WINDOW_SECONDS     = 15 * 60
LOGIN_LOCK_SECONDS       = 15 * 60

_login_fails = {}                 # key -> [fail_count, window_start, locked_until]
_login_lock  = threading.Lock()


def _lock_remaining(key):
    entry = _login_fails.get(key)
    return max(0, int(entry[2] - time.time())) if entry else 0


def login_lock_remaining(ip):
    with _login_lock:
        return max(_lock_remaining(f'ip:{ip}'), _lock_remaining('account'))


def record_login_failure(ip):
    now = time.time()
    with _login_lock:
        for key, limit in ((f'ip:{ip}', LOGIN_MAX_FAILS_PER_IP), ('account', LOGIN_MAX_FAILS_ACCOUNT)):
            entry = _login_fails.get(key)
            if not entry or now - entry[1] > LOGIN_WINDOW_SECONDS:
                entry = [0, now, 0]
            entry[0] += 1
            if entry[0] >= limit:
                entry[2] = now + LOGIN_LOCK_SECONDS
                entry[0], entry[1] = 0, now
            _login_fails[key] = entry


def reset_login_failures(ip):
    with _login_lock:
        _login_fails.pop(f'ip:{ip}', None)


# ── Admin credentials ──────────────────────────────────────────────────────────

# Compared against when the username is wrong, so a bad username takes as long
# to reject as a bad password (no user-enumeration timing signal).
_DUMMY_HASH = 'scrypt:32768:8:1$dummysaltdummys$' + '0' * 128


def admin_configured():
    return bool(os.environ.get('ADMIN_PASSWORD_HASH', '').strip())


def verify_admin(username, password):
    expected_user = os.environ.get('ADMIN_USER', 'admin')
    pw_hash = os.environ.get('ADMIN_PASSWORD_HASH', '').strip()
    if not pw_hash or not password:
        return False
    user_ok = hmac.compare_digest((username or '').encode(), expected_user.encode())
    try:
        pw_ok = check_password_hash(pw_hash if user_ok else _DUMMY_HASH, password)
    except (ValueError, TypeError):
        return False
    return user_ok and pw_ok


# ── Admin sessions ─────────────────────────────────────────────────────────────

ADMIN_IDLE_SECONDS    = 30 * 60      # overridden from ADMIN_IDLE_MINUTES in init_security()
ADMIN_MAX_AGE_SECONDS = 12 * 3600
_TOUCH_EVERY_SECONDS  = 60


def _token_hash(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def start_admin_session(username=''):
    """Called after a successful login: throw away the old session (prevents
    fixation) and issue a fresh random token stored server-side."""
    from server import db
    session.clear()
    token = secrets.token_urlsafe(32)
    db.create_admin_session(_token_hash(token))
    session['admin_sid'] = token
    session['admin_user'] = str(username)[:100]
    session['_csrf'] = secrets.token_urlsafe(32)
    session['_touched'] = time.time()
    session.permanent = True


def end_admin_session():
    from server import db
    token = session.get('admin_sid')
    if token:
        db.delete_admin_session(_token_hash(token))
    session.clear()


def is_admin():
    from server import db
    token = session.get('admin_sid')
    if not token:
        return False
    sid = _token_hash(token)
    row = db.get_admin_session(sid)
    now = time.time()
    if (not row or now - row['last_seen'] > ADMIN_IDLE_SECONDS
            or now - row['created_at'] > ADMIN_MAX_AGE_SECONDS):
        if row:
            db.delete_admin_session(sid)
        session.pop('admin_sid', None)
        return False
    if now - session.get('_touched', 0) > _TOUCH_EVERY_SECONDS:
        db.touch_admin_session(sid)
        session['_touched'] = now
    return True


def current_admin():
    """Username of the signed-in admin (for audit fields), '' when unknown."""
    return session.get('admin_user') or ''


def require_admin_page(view):
    """HTML admin pages: redirect to the login form when not signed in."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not is_admin():
            return redirect(url_for('admin_login', next=request.path))
        return view(*args, **kwargs)
    return wrapper


def require_admin(view):
    """Admin JSON endpoints: 401 when not signed in."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not is_admin():
            return jsonify({'status': 'error', 'error': 'auth_required',
                            'message': 'Admin login required.'}), 401
        return view(*args, **kwargs)
    return wrapper


def safe_next_url(target):
    """Only allow redirects back into the admin area of this site."""
    if not target or not target.startswith('/admin') or target.startswith('//') or '\\' in target:
        return '/admin'
    return target


# ── CSRF ───────────────────────────────────────────────────────────────────────

CSRF_PROTECTED_PREFIXES = ('/admin', '/feedback/submit')


def csrf_token():
    token = session.get('_csrf')
    if not token:
        token = secrets.token_urlsafe(32)
        session['_csrf'] = token
    return token


def _csrf_failure():
    if request.path.startswith('/admin/login'):
        return None   # the login view shows its own friendly message
    return jsonify({'status': 'error', 'error': 'csrf',
                    'message': 'Your session expired — please reload the page and try again.'}), 403


def check_csrf():
    """before_request hook: state-changing requests need a matching token and,
    when the browser sends one, a same-origin Origin header."""
    if request.method in ('GET', 'HEAD', 'OPTIONS'):
        return None
    if not request.path.startswith(CSRF_PROTECTED_PREFIXES):
        return None
    origin = request.headers.get('Origin')
    if origin and urlsplit(origin).netloc != request.host:
        return _csrf_failure() or ('Cross-origin request blocked.', 403)
    sent = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token') or ''
    expected = session.get('_csrf') or ''
    if not expected or not hmac.compare_digest(sent.encode(), expected.encode()):
        request.environ['infosphere.csrf_failed'] = True
        return _csrf_failure()
    return None


def csrf_failed():
    return bool(request.environ.get('infosphere.csrf_failed'))


# ── Security headers ───────────────────────────────────────────────────────────

_CSP_COMMON = (
    "default-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' data: https://fonts.gstatic.com; "
    "img-src 'self' data: blob:; "
    "media-src 'self' blob:; "
    "connect-src 'self'; "
    "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)


def csp_nonce():
    """Per-request random value. Templates put it on their inline <script>
    tags; any script without it (e.g. one injected by an attacker) is blocked."""
    if 'csp_nonce' not in g:
        g.csp_nonce = secrets.token_urlsafe(16)
    return g.csp_nonce


def apply_security_headers(response):
    h = response.headers
    is_admin_path = request.path.startswith('/admin')
    # Admin pages load only external same-origin scripts; public pages may also
    # run their own inline <script> blocks, but only the ones carrying the nonce.
    script_src = "script-src 'self'" if is_admin_path else f"script-src 'self' 'nonce-{csp_nonce()}'"
    h['Content-Security-Policy'] = f"{script_src}; {_CSP_COMMON}"
    h['X-Frame-Options'] = 'DENY'
    h['X-Content-Type-Options'] = 'nosniff'
    h['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    h['Permissions-Policy'] = 'microphone=(self), camera=(), geolocation=(), payment=(), usb=()'
    h['Cross-Origin-Opener-Policy'] = 'same-origin'
    if request.is_secure:
        h['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    if is_admin_path:
        h['Cache-Control'] = 'no-store'
    return response


# ── App wiring ─────────────────────────────────────────────────────────────────

def _own_addresses():
    """Loopback plus this machine's own LAN addresses (so opening the admin via
    http://192.168.x.x:5000 on the kiosk PC itself still works)."""
    import socket
    addrs = {'127.0.0.1', '::1', 'localhost'}
    try:
        addrs.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    return addrs


def init_security(app):
    global ADMIN_IDLE_SECONDS
    try:
        ADMIN_IDLE_SECONDS = max(5, int(os.environ.get('ADMIN_IDLE_MINUTES', 30))) * 60
    except ValueError:
        pass

    production = os.environ.get('INFOSPHERE_ENV', '').strip().lower() == 'production'
    app.config['IS_PRODUCTION'] = production

    secret = os.environ.get('SECRET_KEY', '').strip()
    if not secret:
        if production:
            raise RuntimeError('SECRET_KEY must be set in production (run scripts/set_admin_password.py --print).')
        secret = secrets.token_hex(32)
        print('[Security] WARNING: SECRET_KEY not set — using a random one; sessions reset on restart.')
    app.secret_key = secret

    if _env_flag('TRUST_PROXY'):
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    secure_cookies = _env_flag('COOKIE_SECURE', default=production)
    app.config.update(
        SESSION_COOKIE_NAME='__Host-infosphere' if secure_cookies else 'infosphere_session',
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=secure_cookies,
        SESSION_COOKIE_SAMESITE='Lax',
        PERMANENT_SESSION_LIFETIME=ADMIN_MAX_AGE_SECONDS,
        MAX_CONTENT_LENGTH=10 * 1024 * 1024,     # audio uploads are well under this
    )

    force_https = _env_flag('FORCE_HTTPS', default=production)

    @app.before_request
    def _https_redirect():
        # /healthz stays on plain http for the platform's internal health checks.
        if force_https and not request.is_secure and request.path != '/healthz':
            return redirect(request.url.replace('http://', 'https://', 1), code=301)

    # Without HTTPS the admin password would cross the network readable by
    # anyone on the same Wi-Fi, so by default the admin area only answers
    # requests from this computer. Production (HTTPS) or ADMIN_ALLOW_REMOTE=1
    # opens it to other devices.
    admin_remote_ok = _env_flag('ADMIN_ALLOW_REMOTE', default=production)
    own_addresses = _own_addresses()

    @app.before_request
    def _admin_local_only():
        if admin_remote_ok or not request.path.startswith('/admin'):
            return None
        if client_ip() not in own_addresses:
            abort(404)      # look like the page doesn't exist

    app.before_request(check_csrf)
    app.after_request(apply_security_headers)
    app.jinja_env.globals['csrf_token'] = csrf_token
    app.jinja_env.globals['csp_nonce'] = csp_nonce
    if not admin_remote_ok:
        print('[Security] Admin pages are only reachable from this computer '
              '(set ADMIN_ALLOW_REMOTE=1 or run in production with HTTPS to change that).')

    if not admin_configured():
        print('[Security] WARNING: ADMIN_PASSWORD_HASH is not set — admin login is disabled. '
              'Run: python scripts/set_admin_password.py')
