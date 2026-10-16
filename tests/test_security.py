"""Production hardening: HTTPS redirect, HSTS, secure cookies, headers, errors."""
from flask import Flask, jsonify

from server import closures, security
from server.paths import TEMPLATES_DIR


def make_app(monkeypatch, production):
    monkeypatch.setenv('INFOSPHERE_ENV', 'production' if production else '')
    monkeypatch.setenv('SECRET_KEY', 'x' * 64)
    app = Flask(__name__, template_folder=TEMPLATES_DIR)
    security.init_security(app)
    app.register_blueprint(closures.bp)

    @app.route('/healthz')
    def healthz():
        return jsonify(status='ok')

    @app.route('/boom')
    def boom():
        raise RuntimeError('secret internal detail')

    @app.route('/_csrf')
    def csrf():
        return jsonify(csrf=security.csrf_token())

    @app.errorhandler(500)
    def err(_e):
        return jsonify(status='error', message='Internal server error.'), 500
    return app


def test_production_redirects_http_to_https(monkeypatch):
    c = make_app(monkeypatch, True).test_client()
    r = c.get('/api/closures')
    assert r.status_code == 301 and r.headers['Location'].startswith('https://')


def test_health_check_stays_on_http(monkeypatch):
    c = make_app(monkeypatch, True).test_client()
    assert c.get('/healthz').status_code == 200


def test_production_https_headers_and_cookie(monkeypatch):
    c = make_app(monkeypatch, True).test_client()
    r = c.get('/_csrf', base_url='https://infosphere.example')
    h = r.headers
    assert 'max-age=' in h['Strict-Transport-Security']
    assert "frame-ancestors 'none'" in h['Content-Security-Policy']
    assert h['X-Content-Type-Options'] == 'nosniff'
    assert h['X-Frame-Options'] == 'DENY'
    assert h['Referrer-Policy'] == 'strict-origin-when-cross-origin'
    cookie = h['Set-Cookie']
    assert cookie.startswith('__Host-infosphere=') and 'Secure' in cookie and 'HttpOnly' in cookie and 'SameSite=Lax' in cookie
    assert 'Access-Control-Allow-Origin' not in h            # no CORS: other sites can't read responses


def test_no_internal_details_in_errors(monkeypatch):
    app = make_app(monkeypatch, False)
    c = app.test_client()
    r = c.get('/boom')
    assert r.status_code == 500
    assert b'secret internal detail' not in r.data and b'Traceback' not in r.data


def test_admin_api_hidden_from_other_devices_on_plain_http(monkeypatch):
    c = make_app(monkeypatch, False).test_client()
    r = c.get('/admin/api/closures', environ_base={'REMOTE_ADDR': '10.1.2.3'})
    assert r.status_code == 404


def test_secret_admin_path_hides_default_admin(monkeypatch):
    monkeypatch.setenv('ADMIN_PATH', 'ops-x7k2q9m4')
    try:
        app = make_app(monkeypatch, False)
        c = app.test_client()
        assert c.get('/admin/api/closures').status_code == 404           # default path is gone
        assert c.get('/ops-x7k2q9m4/api/closures').status_code == 401    # secret path reaches the (locked) API
        assert security.admin_base() == '/ops-x7k2q9m4'
        assert security.safe_next_url('/ops-x7k2q9m4/feedback') == '/admin/feedback'
        assert security.safe_next_url('//evil.com') == '/admin'
    finally:
        monkeypatch.delenv('ADMIN_PATH')
        security.init_security(Flask(__name__))       # reset the module-level admin base
        assert security.admin_base() == '/admin'


def test_secret_admin_path_must_be_well_formed(monkeypatch):
    import pytest
    monkeypatch.setenv('ADMIN_PATH', 'a/b')
    with pytest.raises(RuntimeError):
        make_app(monkeypatch, False)
    monkeypatch.delenv('ADMIN_PATH')
    security.init_security(Flask(__name__))


def test_new_password_signs_existing_admins_out(admin, monkeypatch):
    assert admin.get('/admin/api/closures').status_code == 200
    monkeypatch.setenv('ADMIN_PASSWORD_HASH', 'scrypt:32768:8:1$othersaltothersa$' + 'b' * 128)
    assert admin.get('/admin/api/closures').status_code == 401


def test_new_username_signs_existing_admins_out(admin, monkeypatch):
    monkeypatch.setenv('ADMIN_USER', 'someone-else')
    assert admin.get('/admin/api/closures').status_code == 401


def test_removing_the_password_signs_admins_out(admin, monkeypatch):
    monkeypatch.delenv('ADMIN_PASSWORD_HASH')
    assert admin.get('/admin/api/closures').status_code == 401
