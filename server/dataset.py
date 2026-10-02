"""Load and validate the map dataset (data/rooms.json) and the Q&A datasets.

Used at runtime (the closures API checks room ids against it) and by
scripts/validate_data.py / the tests.
"""
import glob
import json
import os
import re
import threading
from collections import Counter

from server.paths import MAPS_DIR, QA_DIR, ROOMS_JSON, ROOMS_SCHEMA, TAUGHT_CSV

# What the floor plans actually show (read off the images in static/maps/).
# Map label -> room id(s) in rooms.json. None = on the map but not in the dataset.
MAP_INVENTORY = {
    1: {'R Baca': 'rbaca', 'Library (kiri)': 'library_left', 'Library (kanan)': 'library_right',
        'Klinik': 'klinik', 'Foto copy external & internal': None, 'APPLE': 'apple',
        'Gallery Bersama': 'gallery', 'Admisi': 'admisi', 'Droop Out': 'dropout', 'BCA C0111-12': 'bca',
        'SSC': 'ssc', 'Marketing': 'marketing', 'SDC': 'sdc', 'SADC C0105': 'sadc', 'UKM C0104': 'ukm'},
    2: {'B0201': 'b0201', 'Library': 'library-2', 'Toilet (x2)': ['toilet-2a', 'toilet-2b'],
        'Studio Fotografi': 'studio-fotografi', 'Greenscreen': 'greenscreen', 'Binus TV': 'binus-tv',
        'Binus Radio': 'binus-radio', 'Amphitheatre': 'amphitheatre', 'C0201': 'c0201', 'C0203': 'c0203',
        'C0204': 'c0204', 'C0205': 'c0205', 'C0206': 'c0206', 'C0207': 'c0207', 'C0209': 'c0209',
        'C0210': 'c0210', 'C0212': 'c0212'},
    3: {'B0301 (Kelas Besar)': 'b0301', 'B0302': 'b0302', 'Toilet (x2)': ['toilet-3a', 'toilet-3b'],
        'Library': 'library-3', 'Finance': 'finance', 'Rektorat': 'rektorat', 'SADC': 'sadc-3',
        'C0301': 'c0301', 'C0302': 'c0302', 'C0303': 'c0303', 'C0304': 'c0304', 'C0305': 'c0305',
        'C0306': 'c0306', 'C0307': 'c0307', 'C0309': 'c0309', 'C0310': 'c0310', 'C0311': 'c0311',
        'C0312': 'c0312'},
    4: {'B0401 (Auditorium)': 'b0401', 'B0402': 'b0402', 'B0403': 'b0403', 'B0404': 'b0404',
        'B0405': 'b0405', 'Toilet (x2)': ['toilet-4a', 'toilet-4b'], 'LSC C0407': 'lsc-c0407',
        'LSC C0408-09': 'lsc-c0408-09', 'C0401': 'c0401', 'IT': 'it', 'C0403': 'c0403', 'C0406': 'c0406',
        'C0410': 'c0410', 'C0411': 'c0411', 'C0412': 'c0412'},
}
# Room codes people might expect but that no floor plan shows — listed so the
# gap is visible, never given made-up coordinates.
NOT_ON_MAPS = ['C0202', 'C0208', 'C0211', 'C0308', 'C0402', 'C0404', 'C0405', 'C0409 (only as C0408-09)']

GENERATED = 'locations_generated.csv'
ROOM_CODE_RE = re.compile(r'\b([a-zA-Z])-?0?(\d)(\d{2})\b')

_cache = {'mtime': None, 'data': None}
_cache_lock = threading.Lock()


def load_rooms(path=ROOMS_JSON):
    """Parsed rooms.json, re-read only when the file changes."""
    mtime = os.path.getmtime(path)
    with _cache_lock:
        if path == ROOMS_JSON and _cache['mtime'] == mtime:
            return _cache['data']
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if path == ROOMS_JSON:
            _cache.update(mtime=mtime, data=data)
        return data


def floors_by_number(data):
    return {f['floor']: f for f in data.get('floors', [])}


def rooms_by_id(data):
    return {r['id']: r for r in data.get('rooms', [])}


def _in_bounds(pt, floor, slack=2):
    return -slack <= pt[0] <= floor['width'] + slack and -slack <= pt[1] <= floor['height'] + slack


def validate_rooms(data, check_images=True):
    """Returns (errors, warnings) — lists of human-readable strings."""
    errors, warnings = [], []
    try:
        import jsonschema
        with open(ROOMS_SCHEMA, 'r', encoding='utf-8') as f:
            schema = json.load(f)
        validator = jsonschema.Draft202012Validator(schema)
        for e in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
            where = '/'.join(str(p) for p in e.path) or '(root)'
            errors.append(f'schema: {where}: {e.message}')
    except ImportError:
        warnings.append('jsonschema is not installed — only the custom checks ran (pip install jsonschema).')
    if errors:
        return errors, warnings      # structure is broken; the checks below would just add noise

    floors = {}
    for f in data['floors']:
        if f['floor'] in floors:
            errors.append(f'floor {f["floor"]} is defined twice')
        floors[f['floor']] = f
        if f['label'] != f'Lantai {f["floor"]}' or f['image'] != f'lantai-{f["floor"]}':
            errors.append(f'floor {f["floor"]}: label/image should be "Lantai {f["floor"]}" / "lantai-{f["floor"]}"')
        if not _in_bounds(f['connector']['xy'], f):
            errors.append(f'floor {f["floor"]}: connector point is outside the map')
        rects = [('walkable', f['walkable'])] if 'walkable' in f else []
        rects += [(key, r) for key in ('voids', 'inside') for r in f.get(key, [])]
        for key, r in rects:
            if not (_in_bounds(r[:2], f) and _in_bounds(r[2:], f)) or r[0] >= r[2] or r[1] >= r[3]:
                errors.append(f'floor {f["floor"]}: bad {key} rectangle {r}')
        if check_images:
            for ext in ('png', 'webp'):
                if not os.path.exists(os.path.join(MAPS_DIR, f'{f["image"]}.{ext}')):
                    warnings.append(f'floor {f["floor"]}: static/maps/{f["image"]}.{ext} is missing '
                                    f'(the map shows "Map not available")')
            if 'walkable' not in f and not os.path.exists(os.path.join(MAPS_DIR, f'{f["image"]}.grid.json')):
                warnings.append(f'floor {f["floor"]}: no route grid — run scripts/build_maps.py')

    ids = Counter(r['id'] for r in data['rooms'])
    for rid, n in ids.items():
        if n > 1:
            errors.append(f'duplicate room id "{rid}" ({n}x)')

    names_per_floor = Counter((r['floor'], r['name'].casefold()) for r in data['rooms'])
    for (floor, name), n in names_per_floor.items():
        if n > 1:
            errors.append(f'floor {floor}: {n} rooms are called "{name}" — make the names distinguishable')

    alias_owner = {}
    for r in data['rooms']:
        rid, name = r['id'], r['name']
        if r['floor'] not in floors:
            errors.append(f'{rid}: floor {r["floor"]} does not exist in "floors"')
            continue
        floor = floors[r['floor']]
        if 'poly' in r:
            if not all(_in_bounds(p, floor) for p in r['poly']):
                errors.append(f'{rid}: polygon goes outside the Lantai {r["floor"]} map ({floor["width"]}x{floor["height"]})')
            xs = [p[0] for p in r['poly']]
            ys = [p[1] for p in r['poly']]
            if max(xs) - min(xs) < 5 or max(ys) - min(ys) < 5:
                errors.append(f'{rid}: polygon is degenerate (smaller than 5 units)')
        else:
            warnings.append(f'{rid}: no polygon — it can be answered but not drawn on the map')
        if name != name.strip() or '  ' in name:
            errors.append(f'{rid}: name has stray spaces: "{name}"')
        if name.isupper() and len(name) > 4 and not ROOM_CODE_RE.search(name) and name not in ('APPLE', 'SADC', 'BCA'):
            warnings.append(f'{rid}: name "{name}" is ALL CAPS — use Title Case like the other rooms')
        for m in ROOM_CODE_RE.finditer(name):
            code = m.group(0)
            canonical = f'{m.group(1).upper()}0{m.group(2)}{m.group(3)}'
            if code != canonical:
                errors.append(f'{rid}: room code "{code}" should be written "{canonical}"')
            if int(m.group(2)) != r['floor'] and canonical[0] in 'BC':
                errors.append(f'{rid}: code {canonical} says floor {m.group(2)} but the room is on floor {r["floor"]}')
        for a in r['aliases']:
            if a != a.strip():
                errors.append(f'{rid}: alias "{a}" has leading/trailing spaces')
            if a in alias_owner and alias_owner[a] != rid:
                warnings.append(f'alias "{a}" is used by both {alias_owner[a]} and {rid} (search shows both)')
            alias_owner.setdefault(a, rid)

    kiosk = data['kiosk']
    kroom = next((r for r in data['rooms'] if r['id'] == kiosk['room']), None)
    if not kroom:
        errors.append(f'kiosk room "{kiosk["room"]}" does not exist')
    elif kroom['floor'] != kiosk['floor'] or 'poly' not in kroom:
        errors.append(f'kiosk room "{kiosk["room"]}" must be on floor {kiosk["floor"]} and have a polygon')
    return errors, warnings


def cross_check_maps(data):
    """Compare the dataset with what the floor plans show. Returns a dict of lists."""
    by_id = rooms_by_id(data)
    expected = set()
    on_map_missing = []
    for floor, labels in MAP_INVENTORY.items():
        for label, ids in labels.items():
            if ids is None:
                on_map_missing.append(f'Lantai {floor}: "{label}"')
                continue
            for rid in ([ids] if isinstance(ids, str) else ids):
                expected.add(rid)
                if rid not in by_id:
                    on_map_missing.append(f'Lantai {floor}: "{label}" (expected id {rid})')
                elif by_id[rid]['floor'] != floor:
                    on_map_missing.append(f'Lantai {floor}: "{label}" is stored on floor {by_id[rid]["floor"]}')
    not_on_map = [f'{r["id"]} ({r["name"]}, Lantai {r["floor"]})' for r in data['rooms'] if r['id'] not in expected]
    return {'on_map_not_in_dataset': on_map_missing, 'in_dataset_not_on_map': not_on_map,
            'codes_not_on_any_map': NOT_ON_MAPS}


def qa_files():
    """Every Q&A dataset: data/qa/*.xlsx|csv plus answers taught from the admin dashboard."""
    files = sorted(glob.glob(os.path.join(QA_DIR, '*.xlsx')) + glob.glob(os.path.join(QA_DIR, '*.csv')))
    return files + ([TAUGHT_CSV] if os.path.exists(TAUGHT_CSV) else [])


def validate_qa(paths=None):
    """Check the chatbot Q&A spreadsheets. Returns (errors, warnings, row_count)."""
    import pandas as pd
    errors, warnings, total = [], [], 0
    seen = {}
    for p in paths or qa_files():
        name = os.path.basename(p)
        if name.startswith('~$'):
            continue
        try:
            if p.lower().endswith('.csv'):
                with open(p, 'rb') as f:
                    f.read().decode('utf-8')           # must be UTF-8
                df = pd.read_csv(p, encoding='utf-8')
            else:
                df = pd.read_excel(p)
        except UnicodeDecodeError:
            errors.append(f'{name}: not UTF-8 encoded — re-save it as "CSV UTF-8"')
            continue
        except Exception as e:      # unreadable file
            errors.append(f'{name}: cannot be read ({type(e).__name__}: {e})')
            continue
        missing = [c for c in ('Question', 'Answer') if c not in df.columns]
        if missing:
            errors.append(f'{name}: missing required column(s) {missing}')
            continue
        total += len(df)
        q = df['Question'].astype('string').str.strip()
        a = df['Answer'].astype('string').str.strip()
        for i in df.index[q.isna() | (q == '')]:
            warnings.append(f'{name} row {i + 2}: empty Question (row is skipped)')
        for i in df.index[a.isna() | (a == '')]:
            warnings.append(f'{name} row {i + 2}: empty Answer (row is skipped)')
        for i, question in q.items():
            if pd.isna(question) or not question:
                continue
            key = question.casefold()
            # Generated rows repeat on purpose ("toilet on floor 2" fits both toilets there).
            both_generated = key in seen and name == GENERATED and seen[key][0].startswith(GENERATED)
            if key in seen and seen[key][1] != a[i] and not both_generated:
                warnings.append(f'{name} row {i + 2}: question "{question}" also appears in {seen[key][0]} '
                                f'with a different answer')
            seen.setdefault(key, (f'{name} row {i + 2}', a[i]))
        if 'Keywords' in df.columns:
            kw = df['Keywords'].dropna().astype(str)
            padded = sorted({k for k in kw if k != k.strip()})
            if padded:
                warnings.append(f'{name}: keywords with stray spaces: {padded}')
            groups = {}
            for k in kw:
                norm = ','.join(sorted(x.strip().casefold() for x in k.split(',')))
                groups.setdefault(norm, set()).add(k.strip())
            for variants in groups.values():
                if len(variants) > 1:
                    warnings.append(f'{name}: same keywords written differently: {sorted(variants)}')
        if 'Confidence.1' in df.columns:
            warnings.append(f'{name}: the "Confidence" column header appears twice')
    return errors, warnings, total
