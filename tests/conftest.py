"""Test setup: a throw-away instance folder (database) and a small Flask app
with the real security layer + closures API — without loading the speech
models, which the full app.py does at import time."""
import os
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Must be set before server.db is imported (it resolves the DB path on import).
_TMP = tempfile.mkdtemp(prefix='infosphere-test-')
os.environ['INFOSPHERE_INSTANCE'] = _TMP
os.environ.pop('INFOSPHERE_DB', None)
os.environ.pop('INFOSPHERE_ENV', None)
os.environ['SECRET_KEY'] = 'test-secret-key-not-used-anywhere-else'

from flask import Flask, jsonify  # noqa: E402

from server import closures, db, security  # noqa: E402
from server.paths import TEMPLATES_DIR  # noqa: E402


@pytest.fixture()
def app():
    app = Flask(__name__, template_folder=TEMPLATES_DIR)
    security.init_security(app)
    db.init_db()
    with db._db() as conn:
        conn.execute('DELETE FROM closures')
        conn.execute('DELETE FROM admin_sessions')
    app.register_blueprint(closures.bp)

    @app.route('/admin/login')
    def admin_login():                 # stand-in for the real login page
        return 'login'

    @app.route('/_test/csrf')
    def _csrf():
        return jsonify(csrf=security.csrf_token())

    @app.route('/_test/login', methods=['POST'])
    def _login():
        security.start_admin_session('tester')
        return jsonify(csrf=security.csrf_token())

    return app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def admin(client):
    """A client signed in as an admin; .csrf holds the matching token."""
    token = client.post('/_test/login').get_json()['csrf']
    client.csrf = token
    return client
