"""Regenerate data/qa/locations_generated.csv from data/rooms.json.

    python scripts/generate_location_dataset.py

The server also does this by itself on startup whenever rooms.json changed,
and the dataset watcher then retrains the chatbot.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.paths import LOCATIONS_CSV  # noqa: E402
from server.qa_locations import write_locations_csv  # noqa: E402

if __name__ == '__main__':
    rows, rooms = write_locations_csv()
    print(f'Wrote {rows} rows for {rooms} rooms -> {LOCATIONS_CSV}')
