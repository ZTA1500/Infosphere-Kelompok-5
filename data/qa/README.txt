DROP NEW DATASETS HERE
======================

Any .xlsx or .csv file placed in this folder is automatically merged with the
main "Dataset Jarvis.xlsx" and the chatbot retrains itself — no restart needed.

Required columns (same as the main dataset):
  Question | Answer | Category | Keywords | Difficulty | Confidence | Confidence | ID

Minimum columns: Question, Answer  (the rest are optional).

How retraining triggers:
  • On startup  — if any dataset changed while the app was off.
  • While running — a background watcher checks every 20 seconds (configurable
    via the RETRAIN_POLL_SEC environment variable) and rebuilds when it detects
    a new/changed/edited file. The previous model keeps serving until the new
    one is ready, so there is no downtime.
  • Manually     — POST /admin/retrain  (the "Retrain" button on /admin).

Notes:
  • Rows missing a Question or Answer are skipped, so a malformed file cannot
    break the model.
  • Auto-learned phrases (instance/learned_qa.json) and answers taught from the
    dashboard (instance/admin_taught.csv) are included in every rebuild.
  • locations_generated.csv is created from data/rooms.json — edit rooms.json,
    not this file. Check everything with: python scripts/validate_data.py
  • Temporary Excel lock files (~$*.xlsx) are ignored.

English and Mandarin:
  • Add the columns Answer_EN and Answer_ZH next to Answer (see the main sheet of
    "Dataset Jarvis.xlsx"). ENG / 汉 visitors get those answers and an English /
    Mandarin voice; a row without them is answered in Indonesian.
  • Questions can be written in any of the three languages — add English or
    Mandarin phrasings as extra rows with the same Answer and ID.
  • The "Ruangan (peta)" sheet lists every room on the maps in all three
    languages. It is generated from data/rooms.json — refresh it with:
        python scripts/sync_spreadsheet.py
    Only the FIRST sheet of a workbook is used for training.
