"""Area closures: admins mark a room (or a drawn area) "closed" or "under
construction"; every visitor's map darkens it and routes through it get a
warning.

    GET    /api/closures                 public, read-only, active closures only
    GET    /admin/api/closures           admin: active + scheduled, with audit fields
    POST   /admin/api/closures           admin: create
    PUT    /admin/api/closures/<id>      admin: edit
    DELETE /admin/api/closures/<id>      admin: remove (area is open again)
    GET    /admin/area-status            admin page

All /admin routes also get the app-wide CSRF check and admin-network rules
from server.security. Closures whose end time has passed simply stop being
returned — no clean-up job needed.
"""
from flask import Blueprint, jsonify, render_template, request

from server import db
from server.dataset import floors_by_number, load_rooms, rooms_by_id
from server.security import current_admin, rate_limited, require_admin, require_admin_page
from server.validation import ValidationError, clean_text, now_utc, parse_utc, utc_iso

bp = Blueprint('closures', __name__)

STATUSES = db.CLOSURE_STATUSES
NOTE_MAX = 200
MAX_POINTS = 32


def public_view(c):
    """Only what visitors need — no updated_by / updated_at / internal ids of admins."""
    return {
        'id': c['id'], 'floor': c['floor'], 'roomId': c['room_id'], 'polygon': c['polygon'],
        'status': c['status'], 'note': c['note'], 'endsAt': c['ends_at'],
    }


def admin_view(c, now_iso):
    v = public_view(c)
    v.update(startsAt=c['starts_at'], updatedBy=c['updated_by'], updatedAt=c['updated_at'],
             active=c['starts_at'] <= now_iso)
    return v


def _number(v, field):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValidationError(f'{field} must be a number.')
    return round(float(v), 1)


def validate_closure(payload):
    """Validate a create/edit request body. Returns the cleaned record."""
    if not isinstance(payload, dict):
        raise ValidationError('Invalid request.')
    data = load_rooms()
    floors = floors_by_number(data)

    floor = payload.get('floor')
    if isinstance(floor, bool) or not isinstance(floor, int) or floor not in floors:
        raise ValidationError('Choose a floor that exists on the map.')

    status = payload.get('status')
    if status not in STATUSES:
        raise ValidationError(f'Status must be one of: {", ".join(STATUSES)}.')

    room_id, polygon = payload.get('roomId'), payload.get('polygon')
    if bool(room_id) == bool(polygon):
        raise ValidationError('Select exactly one area: a room or a drawn rectangle.')
    if room_id:
        room = rooms_by_id(data).get(room_id) if isinstance(room_id, str) else None
        if not room or room['floor'] != floor:
            raise ValidationError('That room does not exist on this floor.')
        if not room.get('poly'):
            raise ValidationError('That room is not drawn on the map, so it cannot be marked.')
        room_id, polygon = room['id'], None
    else:
        f = floors[floor]
        if not isinstance(polygon, list) or not 3 <= len(polygon) <= MAX_POINTS:
            raise ValidationError(f'An area needs between 3 and {MAX_POINTS} points.')
        pts = []
        for p in polygon:
            if not isinstance(p, list) or len(p) != 2:
                raise ValidationError('Area points must be [x, y] pairs.')
            x, y = _number(p[0], 'x'), _number(p[1], 'y')
            if not (0 <= x <= f['width'] and 0 <= y <= f['height']):
                raise ValidationError('The area must be inside the map.')
            pts.append([x, y])
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        if max(xs) - min(xs) < 8 or max(ys) - min(ys) < 8:
            raise ValidationError('The area is too small.')
        polygon = pts

    note = clean_text(payload.get('note'), NOTE_MAX, field='Note', multiline=False)
    now = now_utc()
    starts = parse_utc(payload.get('startsAt'), 'Start date') or now
    ends = parse_utc(payload.get('endsAt'), 'End date')
    if ends and ends <= now:
        raise ValidationError('The end date must be in the future.')
    if ends and ends <= starts:
        raise ValidationError('The end date must be after the start date.')
    return {
        'floor': floor, 'room_id': room_id, 'polygon': polygon, 'status': status, 'note': note,
        'starts_at': utc_iso(starts), 'ends_at': utc_iso(ends),
        'updated_by': current_admin(), 'updated_at': utc_iso(now),
    }


def _error(message, status=400):
    return jsonify({'status': 'error', 'message': message}), status


# ── public ─────────────────────────────────────────────────────────────────────

@bp.get('/api/closures')
@rate_limited('closures-public', limit=120, window_seconds=60)
def public_closures():
    items = [public_view(c) for c in db.list_closures(utc_iso(now_utc()))]
    resp = jsonify({'closures': items})
    resp.headers['Cache-Control'] = 'no-cache'
    return resp


# ── admin ──────────────────────────────────────────────────────────────────────

@bp.get('/admin/area-status')
@require_admin_page
def area_status_page():
    return render_template('admin_closures.html', active='area-status')


@bp.get('/admin/api/closures')
@require_admin
def admin_list():
    now_iso = utc_iso(now_utc())
    return jsonify({'closures': [admin_view(c, now_iso) for c in db.list_closures(now_iso, include_scheduled=True)],
                    'statuses': list(STATUSES)})


@bp.post('/admin/api/closures')
@require_admin
@rate_limited('closures-write', limit=60, window_seconds=60)
def admin_create():
    try:
        rec = validate_closure(request.get_json(silent=True))
    except ValidationError as e:
        return _error(str(e))
    cid = db.add_closure(rec)
    return jsonify({'status': 'ok', 'closure': admin_view(db.get_closure(cid), utc_iso(now_utc()))}), 201


@bp.put('/admin/api/closures/<int:closure_id>')
@require_admin
@rate_limited('closures-write', limit=60, window_seconds=60)
def admin_update(closure_id):
    if not db.get_closure(closure_id):
        return _error('Closure not found.', 404)
    try:
        rec = validate_closure(request.get_json(silent=True))
    except ValidationError as e:
        return _error(str(e))
    db.update_closure(closure_id, rec)
    return jsonify({'status': 'ok', 'closure': admin_view(db.get_closure(closure_id), utc_iso(now_utc()))})


@bp.delete('/admin/api/closures/<int:closure_id>')
@require_admin
def admin_delete(closure_id):
    if not db.delete_closure(closure_id):
        return _error('Closure not found.', 404)
    return jsonify({'status': 'ok'})
