"""Dataset validation: the real data passes, and broken data is caught."""
import copy
import json

import pytest

from server.dataset import MAP_INVENTORY, cross_check_maps, load_rooms, validate_qa, validate_rooms
from server.paths import ROOMS_JSON
from server.validation import ValidationError, clean_text


@pytest.fixture(scope='module')
def rooms():
    return load_rooms()


def test_rooms_json_is_utf8_json():
    with open(ROOMS_JSON, 'rb') as f:
        json.loads(f.read().decode('utf-8'))


def test_real_rooms_dataset_is_valid(rooms):
    errors, _ = validate_rooms(rooms)
    assert errors == []


def test_every_room_on_the_maps_is_in_the_dataset(rooms):
    report = cross_check_maps(rooms)
    # The only known gap: floor 1's photocopy corner has no outline yet.
    assert report['on_map_not_in_dataset'] == ['Lantai 1: "Foto copy external & internal"']
    assert report['in_dataset_not_on_map'] == []
    assert sum(len(v) for v in MAP_INVENTORY.values()) >= 60


def test_rooms_without_a_map_were_not_invented(rooms):
    ids = {r['id'] for r in rooms['rooms']}
    for code in ('c0202', 'c0208', 'c0308', 'c0402', 'c0404', 'c0405'):
        assert code not in ids


def _mutate(rooms, fn):
    data = copy.deepcopy(rooms)
    fn(data)
    errors, warnings = validate_rooms(data, check_images=False)
    return errors, warnings


def test_duplicate_ids_are_caught(rooms):
    errors, _ = _mutate(rooms, lambda d: d['rooms'].append(copy.deepcopy(d['rooms'][0])))
    assert any('duplicate room id' in e for e in errors)


def test_room_outside_map_is_caught(rooms):
    def f(d):
        d['rooms'][0]['poly'][2] = [99999, 99999]
    errors, _ = _mutate(rooms, f)
    assert any('outside the Lantai' in e for e in errors)


def test_unknown_floor_is_caught(rooms):
    def f(d):
        d['rooms'][0]['floor'] = 7
    errors, _ = _mutate(rooms, f)
    assert any('floor 7 does not exist' in e for e in errors)


def test_badly_written_room_code_is_caught(rooms):
    def f(d):
        room = next(r for r in d['rooms'] if r['id'] == 'c0207')
        room['name'] = 'c-0207'
    errors, _ = _mutate(rooms, f)
    assert any('should be written "C0207"' in e for e in errors)


def test_all_caps_name_is_flagged(rooms):
    def f(d):
        next(r for r in d['rooms'] if r['id'] == 'toilet-2a')['name'] = 'TOILET'
    _, warnings = _mutate(rooms, f)
    assert any('ALL CAPS' in w for w in warnings)


def test_schema_rejects_wrong_types(rooms):
    def f(d):
        d['rooms'][0]['aliases'] = 'not a list'
        d['rooms'][1]['type'] = 'spaceship'
    errors, _ = _mutate(rooms, f)
    assert any('schema' in e and 'aliases' in e for e in errors)
    assert any('schema' in e and 'type' in e for e in errors)


def test_missing_kiosk_room_is_caught(rooms):
    def f(d):
        d['kiosk']['room'] = 'nowhere'
    errors, _ = _mutate(rooms, f)
    assert any('kiosk room' in e for e in errors)


def test_real_qa_datasets_have_no_errors():
    errors, _, rows = validate_qa()
    assert errors == []
    assert rows > 500


def test_qa_csv_problems_are_caught(tmp_path):
    missing = tmp_path / 'missing.csv'
    missing.write_text('Question,Category\nDimana?,Location\n', encoding='utf-8')
    latin = tmp_path / 'latin.csv'
    latin.write_bytes('Question,Answer\nDi mana kantin?,Kantin ada di lantai 1 – caf\xe9\n'.encode('cp1252'))
    errors, _, _ = validate_qa([str(missing), str(latin)])
    assert any('missing required column' in e for e in errors)
    assert any('not UTF-8' in e for e in errors)


def test_clean_text_strips_html_and_limits_length():
    assert clean_text('<b>Hai</b> <img src=x onerror=alert(1)>teman', 100) == 'Hai teman'
    assert clean_text('a\x00b\x1fc', 10) == 'abc'
    with pytest.raises(ValidationError):
        clean_text('x' * 11, 10)
    with pytest.raises(ValidationError):
        clean_text('  ', 10, required=True)


def test_every_answer_has_english_and_mandarin():
    from server import i18n
    errors, warnings = i18n.validate()
    assert errors == []
    assert not any('no English/Mandarin version' in w for w in warnings), warnings
    answer = 'C0207 berada di Lantai 2, di seberang eskalator, di sebelah kiri Toilet.'
    assert i18n.translate(answer, 'ENG') == 'C0207 is on Floor 2, across from the escalator, to the left of the toilet.'
    assert i18n.translate(answer, 'ZH') == 'C0207位于2楼，在扶梯对面，洗手间的左边。'
    assert i18n.translate(answer, 'IND') is None


def test_floor_access_note_is_in_every_answer_on_that_floor():
    from server import i18n
    from server.qa_locations import room_entries
    answers = {room['id']: answer for _i, room, _d, answer in room_entries()}
    assert answers['rektorat'].endswith('hanya bisa diakses lewat tangga darurat dari Lantai 2 atau Lantai 4.')
    assert i18n.translate(answers['rektorat'], 'ENG').endswith('by the emergency stairs from Floor 2 or Floor 4.')
    assert i18n.translate(answers['rektorat'], 'ZH').endswith('学生只能从2楼或4楼走紧急楼梯到3楼。')
    assert 'tangga darurat' not in answers['c0207']


def test_room_qa_ids_exist_in_the_main_spreadsheet():
    import pandas as pd

    from server.dataset import load_rooms
    from server.paths import MAIN_DATASET
    sheet_ids = set(pd.read_excel(MAIN_DATASET)['ID'].dropna().astype(int))
    linked = {r['id']: r['qa_id'] for r in load_rooms()['rooms'] if 'qa_id' in r}
    assert linked, 'expected rooms linked to spreadsheet answers (LSC, SSC, LKC)'
    assert {rid: q for rid, q in linked.items() if q not in sheet_ids} == {}
    assert len(set(linked.values())) == len(linked), 'two rooms share one spreadsheet answer'
