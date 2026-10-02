"""Closure API: authentication, CSRF, status/area validation, public view."""
from datetime import timedelta

import sqlite3

import pytest

from server import db
from server.validation import now_utc, utc_iso

ROOM_ON_FLOOR_2 = 'c0207'


def post(client, body, csrf=None):
    headers = {'X-CSRF-Token': csrf} if csrf else {}
    return client.post('/admin/api/closures', json=body, headers=headers)


def valid_body(**over):
    body = {'floor': 2, 'roomId': ROOM_ON_FLOOR_2, 'status': 'under_construction', 'note': 'Renovasi plafon'}
    body.update(over)
    return body


# ── auth ────────────────────────────────────────────────────────────────────

def test_admin_list_requires_login(client):
    r = client.get('/admin/api/closures')
    assert r.status_code == 401
    assert r.get_json()['error'] == 'auth_required'


def test_admin_page_redirects_to_login(client):
    r = client.get('/admin/area-status')
    assert r.status_code == 302
    assert '/admin/login' in r.headers['Location']


@pytest.mark.parametrize('method,url', [
    ('post', '/admin/api/closures'),
    ('put', '/admin/api/closures/1'),
    ('delete', '/admin/api/closures/1'),
])
def test_writes_without_csrf_token_are_rejected(client, method, url):
    r = getattr(client, method)(url, json=valid_body())
    assert r.status_code == 403
    assert r.get_json()['error'] == 'csrf'


@pytest.mark.parametrize('method,url', [
    ('post', '/admin/api/closures'),
    ('put', '/admin/api/closures/1'),
    ('delete', '/admin/api/closures/1'),
])
def test_writes_with_csrf_but_not_logged_in_are_rejected(client, method, url):
    token = client.get('/_test/csrf').get_json()['csrf']
    r = getattr(client, method)(url, json=valid_body(), headers={'X-CSRF-Token': token})
    assert r.status_code == 401
    with db._db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM closures').fetchone()[0] == 0


def test_cross_site_origin_is_blocked(admin):
    r = admin.post('/admin/api/closures', json=valid_body(),
                   headers={'X-CSRF-Token': admin.csrf, 'Origin': 'https://evil.example'})
    assert r.status_code == 403


# ── status & area validation ────────────────────────────────────────────────

@pytest.mark.parametrize('status', ['open', 'Closed', 'CLOSED', 'under construction', '', None, 1, ['closed']])
def test_invalid_status_is_rejected(admin, status):
    r = post(admin, valid_body(status=status), admin.csrf)
    assert r.status_code == 400
    assert 'Status must be one of' in r.get_json()['message']


@pytest.mark.parametrize('status', ['closed', 'under_construction'])
def test_valid_statuses_are_accepted(admin, status):
    r = post(admin, valid_body(status=status), admin.csrf)
    assert r.status_code == 201, r.get_json()
    c = r.get_json()['closure']
    assert c['status'] == status and c['roomId'] == ROOM_ON_FLOOR_2 and c['updatedBy'] == 'tester'


def test_database_rejects_unknown_status_too():
    with pytest.raises(sqlite3.IntegrityError):
        db.add_closure({'floor': 2, 'room_id': 'c0207', 'polygon': None, 'status': 'demolished', 'note': '',
                        'starts_at': utc_iso(now_utc()), 'ends_at': None, 'updated_by': '', 'updated_at': ''})


@pytest.mark.parametrize('body,msg', [
    (valid_body(roomId='c0207', floor=3), 'does not exist on this floor'),
    (valid_body(roomId='nope'), 'does not exist on this floor'),
    (valid_body(floor=9), 'floor that exists'),
    (valid_body(floor='2'), 'floor that exists'),
    (valid_body(roomId=None), 'exactly one area'),
    (valid_body(polygon=[[0, 0], [50, 0], [50, 50]]), 'exactly one area'),
    (valid_body(roomId=None, polygon=[[0, 0], [5000, 0], [5000, 50]]), 'inside the map'),
    (valid_body(roomId=None, polygon=[[0, 0], [2, 0], [2, 2]]), 'too small'),
    (valid_body(roomId=None, polygon=[[0, 0], [40, 0]]), 'between 3 and'),
    (valid_body(note='x' * 201), 'too long'),
    (valid_body(endsAt='2001-01-01T00:00:00Z'), 'in the future'),
    (valid_body(endsAt='not a date'), 'not a valid date'),
])
def test_bad_closures_are_rejected(admin, body, msg):
    r = post(admin, body, admin.csrf)
    assert r.status_code == 400
    assert msg in r.get_json()['message']


def test_drawn_area_and_html_note(admin):
    body = valid_body(roomId=None, polygon=[[100, 100], [300, 100], [300, 180], [100, 180]],
                      note='<script>alert(1)</script>Lorong <b>ditutup</b>')
    r = post(admin, body, admin.csrf)
    assert r.status_code == 201, r.get_json()
    c = r.get_json()['closure']
    assert c['roomId'] is None and len(c['polygon']) == 4
    assert c['note'] == 'alert(1)Lorong ditutup'           # tags stripped, text kept


# ── public view, edit, delete, expiry ───────────────────────────────────────

def test_public_endpoint_hides_admin_fields(admin, client):
    assert post(admin, valid_body(), admin.csrf).status_code == 201
    items = client.get('/api/closures').get_json()['closures']
    assert len(items) == 1
    assert set(items[0]) == {'id', 'floor', 'roomId', 'polygon', 'status', 'note', 'endsAt'}


def test_edit_and_remove(admin, client):
    cid = post(admin, valid_body(), admin.csrf).get_json()['closure']['id']
    r = admin.put(f'/admin/api/closures/{cid}', json=valid_body(status='closed', note='Ditutup sementara'),
                  headers={'X-CSRF-Token': admin.csrf})
    assert r.status_code == 200 and r.get_json()['closure']['status'] == 'closed'
    r = admin.put(f'/admin/api/closures/{cid}', json=valid_body(status='broken'), headers={'X-CSRF-Token': admin.csrf})
    assert r.status_code == 400
    assert admin.delete(f'/admin/api/closures/{cid}', headers={'X-CSRF-Token': admin.csrf}).status_code == 200
    assert admin.delete(f'/admin/api/closures/{cid}', headers={'X-CSRF-Token': admin.csrf}).status_code == 404
    assert client.get('/api/closures').get_json()['closures'] == []


def test_ended_and_future_closures_are_not_public(admin, client):
    now = now_utc()
    base = {'floor': 2, 'room_id': 'c0207', 'polygon': None, 'status': 'closed', 'note': '',
            'updated_by': 't', 'updated_at': utc_iso(now)}
    db.add_closure({**base, 'starts_at': utc_iso(now - timedelta(days=3)), 'ends_at': utc_iso(now - timedelta(hours=1))})
    db.add_closure({**base, 'room_id': 'c0201', 'starts_at': utc_iso(now + timedelta(days=1)), 'ends_at': None})
    db.add_closure({**base, 'room_id': 'c0206', 'starts_at': utc_iso(now - timedelta(days=1)),
                    'ends_at': utc_iso(now + timedelta(days=1))})
    public = [c['roomId'] for c in client.get('/api/closures').get_json()['closures']]
    assert public == ['c0206']
    admin_view = {c['roomId']: c['active'] for c in admin.get('/admin/api/closures').get_json()['closures']}
    assert admin_view == {'c0201': False, 'c0206': True}      # ended one is gone, scheduled one listed
