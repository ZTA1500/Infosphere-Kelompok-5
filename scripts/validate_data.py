"""Check every dataset the app uses.

    python scripts/validate_data.py          # exit code 1 if anything is broken

- data/rooms.json: valid UTF-8 JSON, matches data/rooms.schema.json, unique ids,
  coordinates inside each floor's map, consistent naming, kiosk room exists.
- Cross-check against the floor plans: rooms on a map but missing from the
  dataset, and dataset rooms that no map shows.
- data/qa/*.xlsx|csv (chatbot Q&A): readable, required columns, empty rows,
  conflicting duplicates, inconsistent keywords.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.dataset import cross_check_maps, validate_qa, validate_rooms  # noqa: E402
from server.paths import ROOMS_JSON  # noqa: E402


def section(title):
    print(f'\n== {title} ' + '=' * max(0, 60 - len(title)))


def show(kind, items):
    for it in items:
        print(f'  {kind}: {it}')


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    failed = False

    section('rooms.json')
    try:
        with open(ROOMS_JSON, 'rb') as f:
            data = json.loads(f.read().decode('utf-8'))
    except UnicodeDecodeError:
        print('  ERROR: rooms.json is not UTF-8')
        return 1
    except json.JSONDecodeError as e:
        print(f'  ERROR: rooms.json is not valid JSON: {e}')
        return 1
    errors, warnings = validate_rooms(data)
    show('ERROR', errors)
    show('warning', warnings)
    failed |= bool(errors)
    print(f'  {len(data.get("rooms", []))} rooms on {len(data.get("floors", []))} floors — '
          f'{"FAILED" if errors else "OK"}')

    if not errors:
        section('Cross-check with the floor plans')
        report = cross_check_maps(data)
        show('on a map, not in the dataset', report['on_map_not_in_dataset'] or ['(none)'])
        show('in the dataset, not on any map', report['in_dataset_not_on_map'] or ['(none)'])
        print('  room codes that appear on no floor plan (not added, no coordinates invented):')
        print('    ' + ', '.join(report['codes_not_on_any_map']))

    section('Chatbot Q&A (data/qa)')
    qa_errors, qa_warnings, rows = validate_qa()
    show('ERROR', qa_errors)
    show('warning', qa_warnings)
    failed |= bool(qa_errors)
    print(f'  {rows} rows — {"FAILED" if qa_errors else "OK"}')

    section('English / Mandarin answers')
    from server.i18n import table, validate as validate_translations
    tr_errors, tr_warnings = validate_translations()
    show('ERROR', tr_errors)
    show('warning', tr_warnings)
    failed |= bool(tr_errors)
    print(f'  {len(table())} answers translated — {"FAILED" if tr_errors else "OK"}')

    print('\nResult:', 'FAILED' if failed else 'all datasets are valid')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
