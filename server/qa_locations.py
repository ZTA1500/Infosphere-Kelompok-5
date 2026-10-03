"""Generate the location Q&A dataset FROM data/rooms.json.

Every room on the map gets a set of "where is X?" questions (Indonesian,
English and Mandarin), so the chatbot can answer for every room the map can
draw. Output: data/qa/locations_generated.csv, which the retrain pipeline
merges with the other datasets. app.py regenerates it automatically whenever
rooms.json is newer than the CSV; scripts/generate_location_dataset.py does
it by hand.

Answers are stored in Indonesian; server/i18n.py builds the English and
Mandarin versions from the same rooms (name_en/_zh, location_en/_zh).
"""
import csv
import os
from collections import Counter

from server.dataset import load_rooms
from server.paths import LOCATIONS_CSV, ROOMS_JSON

# {n} = room display name. Indonesian (bulk) + English.
TEMPLATES = [
    "Dimana lokasi {n}?",
    "Lokasi {n} ada dimana?",
    "Dimanakah letak {n}?",
    "{n} ada di lantai berapa?",
    "Di mana saya bisa menemukan {n}?",
    "Tolong tunjukkan lokasi {n}.",
    "Bagaimana cara ke {n}?",
    "Arah ke {n} kemana?",
    "{n} itu dimana ya?",
    "Posisi {n} di gedung ini dimana?",
    "Letak {n} ada di sebelah mana?",
    "Saya mau ke {n}, lewat mana?",
    "Di bagian mana {n} berada?",
    "{n} terletak dimana?",
    "Tunjukkan jalan ke {n}.",
    "Mau tanya, {n} ada dimana?",
    "Cari {n} dimana?",
    "{n} ada di sisi mana gedung?",
    "Where is {n}?",
    "Where can I find {n}?",
    "How do I get to {n}?",
    "Location of {n}?",
    "Show me the way to {n}.",
]
TEMPLATES_EN = ["Where is the {n}?", "Where is {n}?", "How do I get to the {n}?", "Where can I find the {n}?",
                "Which floor is the {n} on?"]
TEMPLATES_ZH = ["{n}在哪里？", "{n}在哪儿？", "请问{n}在哪里？", "{n}在几楼？", "怎么去{n}？", "去{n}怎么走？",
                "带我去{n}", "{n}的位置在哪里？"]
ZH_TOILET_WORDS = ['洗手间', '厕所', '卫生间']
HEADER = ['Question', 'Answer', 'Category', 'Keywords', 'Difficulty', 'Confidence', 'ID']
FIRST_ID = 200


def access_note(floor, lang='id'):
    """The floor's access rule from rooms.json ("students reach Floor 3 only by
    the emergency stairs…"), without the final full stop, or ''."""
    access = next((f.get('access') or {} for f in load_rooms()['floors'] if f['floor'] == floor), {})
    return (access.get('note' if lang == 'id' else f'note_{lang}') or '').strip()


def answer_for(room, display):
    loc = (room.get('location') or '').strip()
    answer = f"{display} berada di Lantai {room['floor']}, {loc}." if loc else f"{display} berada di Lantai {room['floor']}."
    note = access_note(room['floor'])
    return f"{answer} {note}." if note else answer


def _base(name):
    return name.split(' (')[0].split('（')[0].strip()


def _keys(r):
    return {r['name'].casefold(), _base(r['name']).casefold()} | {a.casefold() for a in r.get('aliases', [])}


def _unique_pick(candidates):
    """For each room pick the first candidate name that no other room also uses."""
    counts = [Counter(c[level].casefold() for c in candidates if c[level]) for level in range(3)]
    return [next((c for level, c in enumerate(cands) if c and counts[level][c.casefold()] == 1), cands[-1])
            for cands in candidates]


def room_entries(rooms=None):
    """[(index, room, display, indonesian_answer)] — the exact answer texts the
    generated dataset contains (server/i18n.py translates these)."""
    rooms = rooms if rooms is not None else load_rooms()['rooms']
    # A name or alias shared by several rooms ("Library", "SADC", "Toilet")
    # would give the chatbot two answers for one question: shared names get
    # the floor added, shared aliases are left out.
    used = Counter(k for r in rooms for k in _keys(r))
    out = []
    for i, room in enumerate(rooms):
        display = room['name']
        if used[display.casefold()] > 1:
            display = f"{display} Lantai {room['floor']}"
        out.append((i, room, display, answer_for(room, display)))
    return out


def needs_update():
    return not os.path.exists(LOCATIONS_CSV) or os.path.getmtime(ROOMS_JSON) > os.path.getmtime(LOCATIONS_CSV)


def write_locations_csv(path=LOCATIONS_CSV):
    rooms = load_rooms()['rooms']
    used = Counter(k for r in rooms for k in _keys(r))
    entries = room_entries(rooms)
    # English / Mandarin names: plain name, then with the floor, then the full name.
    en = _unique_pick([(_base(r['name_en']), f"{_base(r['name_en'])} on Floor {r['floor']}", r['name_en'])
                       if r.get('name_en') else (None, None, None) for r in rooms])
    zh = _unique_pick([(_base(r['name_zh']), f"{r['floor']}楼{_base(r['name_zh'])}", r['name_zh'])
                       if r.get('name_zh') else (None, None, None) for r in rooms])
    rows = 0
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(HEADER)

        def emit(question, answer, room, i, j):
            nonlocal rows
            w.writerow([question, answer, 'Location', room['id'], 'Easy' if j % 3 else 'Medium', 0.85, FIRST_ID + i])
            rows += 1

        for (i, room, display, answer), name_en, name_zh in zip(entries, en, zh, strict=True):
            aliases = [a for a in room.get('aliases', []) if used[a.casefold()] == 1 and a.casefold() != display.casefold()]
            for nm in dict.fromkeys([display] + aliases[:1]):
                for j, tpl in enumerate(TEMPLATES):
                    emit(tpl.format(n=nm), answer, room, i, j)
            en_names = [name_en] if name_en and name_en.casefold() != display.casefold() else []
            if room.get('name_en'):                 # "Toilet on Floor 4" even when the floor has two
                en_names.append(f"{_base(room['name_en'])} on Floor {room['floor']}")
            for nm in dict.fromkeys(en_names):
                for j, tpl in enumerate(TEMPLATES_EN):
                    emit(tpl.format(n=nm), answer, room, i, j)
            zh_names = [name_zh, display]
            if room.get('name_zh'):                 # "2楼图书馆" even when the floor has two
                zh_names.append(f"{room['floor']}楼{_base(room['name_zh'])}")
            if room['type'] == 'toilet':            # every common word for "toilet"
                zh_names += [f"{room['floor']}楼{w}" for w in ZH_TOILET_WORDS]
            for nm in dict.fromkeys(n for n in zh_names if n):
                for j, tpl in enumerate(TEMPLATES_ZH):
                    emit(tpl.format(n=nm), answer, room, i, j)
    return rows, len(rooms)
