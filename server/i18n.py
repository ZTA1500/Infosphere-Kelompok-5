"""English and Mandarin versions of chatbot answers.

The chatbot's datasets answer in Indonesian. For a visitor using the ENG or
汉 interface, /chat swaps the answer for its translation:

- room answers (generated from data/rooms.json) are built from the room's
  name_en/name_zh and location_en/location_zh, falling back to the map name;
- every other answer comes from data/qa/translations.json.

An answer with no translation is returned in Indonesian.
"""
import json
import os
import threading

from server.dataset import load_rooms
from server.paths import QA_DIR, ROOMS_JSON

TRANSLATIONS_JSON = os.path.join(QA_DIR, 'translations.json')
LANGS = ('en', 'zh')
UI_LANG = {'ENG': 'en', 'ZH': 'zh'}

_cache = {'key': None, 'table': {}}
_lock = threading.Lock()


def _room_translation(room, lang):
    floor = room['floor']
    name = room.get(f'name_{lang}') or room['name']
    loc = (room.get(f'location_{lang}') or '').strip()
    if lang == 'zh':
        return f"{name}位于{floor}楼，{loc}。" if loc else f"{name}位于{floor}楼。"
    return f"{name} is on Floor {floor}, {loc}." if loc else f"{name} is on Floor {floor}."


def _build():
    from server.qa_locations import room_entries
    table = {}
    if os.path.exists(TRANSLATIONS_JSON):
        with open(TRANSLATIONS_JSON, 'r', encoding='utf-8') as f:
            for answer, tr in json.load(f).get('answers', {}).items():
                table[answer.strip()] = {k: v.strip() for k, v in tr.items() if k in LANGS and v.strip()}
    for _i, room, _display, answer in room_entries(load_rooms()['rooms']):
        table[answer.strip()] = {lang: _room_translation(room, lang) for lang in LANGS}
    return table


def table():
    """{indonesian_answer: {'en': ..., 'zh': ...}}, rebuilt when the source files change."""
    key = tuple(os.path.getmtime(p) if os.path.exists(p) else 0 for p in (ROOMS_JSON, TRANSLATIONS_JSON))
    with _lock:
        if _cache['key'] != key:
            _cache['table'] = _build()
            _cache['key'] = key
        return _cache['table']


def translate(answer, ui_lang):
    """Answer in the visitor's interface language, or None if there's no translation."""
    lang = UI_LANG.get(ui_lang)
    if not lang or not answer:
        return None
    return table().get(answer.strip(), {}).get(lang)


def all_translations(lang):
    return {tr[lang] for tr in table().values() if tr.get(lang)}


def validate():
    """(errors, warnings) for translations.json against the Q&A datasets."""
    import pandas as pd
    from server.dataset import qa_files
    errors, warnings = [], []
    try:
        with open(TRANSLATIONS_JSON, 'r', encoding='utf-8') as f:
            static = json.load(f).get('answers', {})
    except FileNotFoundError:
        return errors, ['data/qa/translations.json is missing — ENG/汉 visitors get Indonesian answers']
    except ValueError as e:
        return [f'translations.json is not valid JSON: {e}'], warnings
    answers = set()
    for p in qa_files():
        try:
            df = pd.read_csv(p, encoding='utf-8') if p.endswith('.csv') else pd.read_excel(p)
            answers |= {str(a).strip() for a in df.get('Answer', []) if isinstance(a, str) and a.strip()}
        except Exception:  # noqa: S112  (unreadable files are reported by validate_qa)
            continue
    for key, tr in static.items():
        for lang in LANGS:
            if not str(tr.get(lang, '')).strip():
                errors.append(f'translations.json: "{key[:50]}" has no {lang} text')
        if key.strip() not in answers and not key.startswith('Maaf'):
            warnings.append(f'translations.json: "{key[:50]}…" matches no answer in the datasets (stale?)')
    table_ = table()
    missing = sorted(a for a in answers if a not in table_)
    if missing:
        warnings.append(f'{len(missing)} answer(s) have no English/Mandarin version yet, e.g. "{missing[0][:60]}"')
    return errors, warnings
