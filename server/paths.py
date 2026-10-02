"""Every file location the app uses, in one place.

    data/       tracked source data: rooms.json (+ schema) and the Q&A datasets
    static/     public files served at /static/ (css, js, images, maps, audio)
    templates/  Jinja pages
    instance/   runtime state that must never be committed: the SQLite
                database, logs, the trained model cache, generated voice lines.
                Point INFOSPHERE_INSTANCE at a persistent volume when hosting.
"""
import os

ROOT          = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR      = os.path.join(ROOT, 'data')
QA_DIR        = os.path.join(DATA_DIR, 'qa')
ROOMS_JSON    = os.path.join(DATA_DIR, 'rooms.json')
ROOMS_SCHEMA  = os.path.join(DATA_DIR, 'rooms.schema.json')
MAIN_DATASET  = os.path.join(QA_DIR, 'Dataset Jarvis.xlsx')
LOCATIONS_CSV = os.path.join(QA_DIR, 'locations_generated.csv')

STATIC_DIR    = os.path.join(ROOT, 'static')
TEMPLATES_DIR = os.path.join(ROOT, 'templates')
AUDIO_DIR     = os.path.join(STATIC_DIR, 'audio')
MAPS_DIR      = os.path.join(STATIC_DIR, 'maps')

INSTANCE_DIR  = os.path.abspath(os.environ.get('INFOSPHERE_INSTANCE') or os.path.join(ROOT, 'instance'))
VOICE_CACHE   = os.path.join(INSTANCE_DIR, 'voice-cache')
TAUGHT_CSV    = os.path.join(INSTANCE_DIR, 'admin_taught.csv')   # answers added from the dashboard
ENV_FILE      = os.path.join(ROOT, '.env')


def instance_file(name):
    os.makedirs(INSTANCE_DIR, exist_ok=True)
    return os.path.join(INSTANCE_DIR, name)
