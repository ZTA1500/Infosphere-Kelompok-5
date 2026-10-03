import os
import sys

# Make console output UTF-8 safe (Windows defaults to cp1252, which crashes on
# emoji / arrows / box-drawing chars when stdout is captured to a file or pipe).
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

from server.paths import (
    AUDIO_DIR, ENV_FILE, ROOMS_JSON, STATIC_DIR, TEMPLATES_DIR, instance_file,
)

# Secrets and settings live in .env (never in code). Load it before anything
# below reads os.environ.
from server.security import load_env_file
load_env_file(ENV_FILE)

import mimetypes
import re
import ssl
import time
import tempfile

# Windows' MIME registry often lacks these; the floor maps are served as WebP.
mimetypes.add_type('image/webp', '.webp')
mimetypes.add_type('application/json', '.json')
import threading
import numpy as np
import noisereduce as nr

# Prefer faster-whisper (4-8× faster, built-in VAD). Install: pip install faster-whisper
try:
    from faster_whisper import WhisperModel as _FasterWhisperModel
    USE_FASTER_WHISPER = True
except ImportError:
    import whisper as _whisper
    USE_FASTER_WHISPER = False
    print("[Whisper] TIP: install faster-whisper for 4-8× speed: pip install faster-whisper")

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from flask import Flask, request, jsonify, send_file, render_template, redirect, url_for
from scipy.io.wavfile import write as wav_write, read as wav_read
import shutil
import subprocess
import warnings


def _find_ffmpeg():
    """System ffmpeg if installed, else the copy bundled with imageio-ffmpeg."""
    exe = shutil.which('ffmpeg')
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


FFMPEG_EXE = _find_ffmpeg()
with warnings.catch_warnings():
    warnings.simplefilter('ignore', RuntimeWarning)    # pydub's "couldn't find ffmpeg" notice
    from pydub import AudioSegment
if FFMPEG_EXE:
    AudioSegment.converter = FFMPEG_EXE
else:
    print('[Audio] WARNING: ffmpeg not found — voice input will not work. Run: pip install imageio-ffmpeg')

from server import offline_tts, voice_ai

# TLS certificate checks stay ON by default. Only for a network whose proxy
# breaks HTTPS (e.g. to download the Whisper model once) set INSECURE_SSL=1.
if os.environ.get('INSECURE_SSL') == '1':
    print('[Security] WARNING: INSECURE_SSL=1 — HTTPS certificate verification is disabled.')
    ssl._create_default_https_context = ssl._create_unverified_context
    os.environ['CURL_CA_BUNDLE'] = ''
    os.environ['REQUESTS_CA_BUNDLE'] = ''

# Only static/ is public. (Serving the whole project folder exposed source
# code, logs, datasets, and the launcher script with credentials.)
app = Flask(__name__,
            template_folder=TEMPLATES_DIR,
            static_folder=STATIC_DIR,
            static_url_path='/static')
# debug=False (below) disables Jinja's auto-reload by default, so edited
# templates would keep serving stale cached content until the process
# restarted. Force it on regardless, so template edits show up immediately.
app.config['TEMPLATES_AUTO_RELOAD'] = True
# Static files aren't fingerprinted, so keep browser caching short.
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 3600

from server import db, security, dataset, i18n
from server.closures import bp as closures_bp
from server.qa_locations import needs_update as locations_need_update, write_locations_csv
from server.security import (
    require_admin, require_admin_page, rate_limited, client_ip,
    verify_admin, admin_configured, start_admin_session, end_admin_session,
    is_admin, login_lock_remaining, record_login_failure, reset_login_failures,
    safe_next_url, csrf_failed,
)
from server.validation import ValidationError, clean_text
security.init_security(app)
db.init_db()
app.register_blueprint(closures_bp)

USE_ADVANCED       = True
AUDIO_FOLDER       = AUDIO_DIR

WHISPER_MODEL_SIZE = os.environ.get('WHISPER_MODEL', 'tiny')

MODEL_PATH       = instance_file('qa_model.pkl')
READY_AUDIO_NAME = 'siap mendengar.mpeg'

LANG_MAP = {'IND': 'id', 'ENG': 'en', 'ZH': 'zh'}

LANG_CODE_NORMALIZE = {
    'ind': 'id', 'eng': 'en', 'zh': 'zh',
    'id':  'id', 'en':  'en',
}

whisper_model = None
chatbot       = None
audio_mapping = {}
TTS_AVAILABLE = False
tts_lock      = threading.Lock()

# ── Answer thresholds ───────────────────────────────────────────────────────────
# < MATCH_THRESHOLD          → no confident match, "point nothing"
# [LEARN_THRESHOLD, 0.999)   → close paraphrase: auto-learn the new phrasing
MATCH_THRESHOLD = float(os.environ.get('MATCH_THRESHOLD', 0.38))
# Questions written only in Chinese share fewer features with the dataset, so a
# weak match is more likely to be wrong: ask for a clearer match before answering.
MATCH_THRESHOLD_ZH = float(os.environ.get('MATCH_THRESHOLD_ZH', 0.5))
_CJK_RE = re.compile(r'[㐀-鿿]')
_LATIN_RE = re.compile(r'[A-Za-z0-9]')
LEARN_THRESHOLD = float(os.environ.get('LEARN_THRESHOLD', 0.60))

# The chatbot runs locally (no external AI service, so no API key exists to
# leak). Questions are capped and every answer is computed under a timeout.
CHAT_MAX_CHARS   = 500
CHAT_TIMEOUT_SEC = float(os.environ.get('CHAT_TIMEOUT_SEC', 10))

# Bump when the model's vectorizer/feature format changes so cached models rebuild.
MODEL_VERSION = 'v3-cjk'

# ── Visit tracking ───────────────────────────────────────────────────────────────
# Counts page views for the admin dashboard without storing anything that
# identifies a person: the IP+User-Agent pair goes through a keyed hash
# (HMAC with VISITOR_SALT from .env) and is never written to disk raw. Only a
# fixed allowlist of real pages is tracked — static files, API calls, and
# admin routes are excluded, and so are obvious bots and link prefetches.
import hmac
VISITOR_SALT  = os.environ.get('VISITOR_SALT') or 'infosphere-visit-salt-v1'
TRACKED_PAGES = {'/', '/landing', '/about', '/feedback'}
BOT_UA_RE = re.compile(
    r'bot|crawl|spider|slurp|scrap|facebookexternalhit|embedly|preview|monitor|uptime|pingdom|'
    r'lighthouse|headless|phantomjs|selenium|puppeteer|playwright|curl|wget|httpie|'
    r'python-requests|python-urllib|aiohttp|httpx|go-http-client|java/|okhttp|libwww|scanner',
    re.IGNORECASE)


def _visitor_hash():
    ua  = request.headers.get('User-Agent', '')
    raw = f'{client_ip()}|{ua}'.encode('utf-8')
    return hmac.new(VISITOR_SALT.encode('utf-8'), raw, 'sha256').hexdigest()[:16]


def _is_countable_visit(response):
    if request.method != 'GET' or request.path not in TRACKED_PAGES:
        return False
    if response.status_code != 200:
        return False
    ua = request.headers.get('User-Agent', '')
    if not ua or BOT_UA_RE.search(ua):
        return False
    purpose = (request.headers.get('Sec-Purpose') or request.headers.get('Purpose') or '').lower()
    return 'prefetch' not in purpose


@app.after_request
def _track_visit(response):
    if _is_countable_visit(response):
        log_visit(
            path=request.path,
            visitor=_visitor_hash(),
            referrer=request.headers.get('Referer', ''),
            user_agent=request.headers.get('User-Agent', ''),
        )
    return response


import json
LEARNED_FILE = instance_file('learned_qa.json')
_learn_lock  = threading.Lock()


def _load_learned():
    if not os.path.exists(LEARNED_FILE):
        return []
    try:
        with open(LEARNED_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []


def _save_learned(items):
    tmp = LEARNED_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    os.replace(tmp, LEARNED_FILE)


MAX_LEARNED          = int(os.environ.get('MAX_LEARNED', 2000))
MAX_LEARNED_QUESTION = 150


def learn_question(question, answer, metadata=None):
    """Teach the live model a new phrasing of an already-known answer.
    Runs on a background thread so it never delays the response. Visitors can
    only add *phrasings* — the answer is always an existing dataset answer —
    and the list is capped so spam can't grow it without limit."""
    if len(question) > MAX_LEARNED_QUESTION:
        return

    def _work():
        with _learn_lock:
            try:
                if not hasattr(chatbot, 'add_learned'):
                    return
                if len(_load_learned()) >= MAX_LEARNED:
                    return
                if not chatbot.add_learned(question, answer, metadata):
                    return                                  # duplicate / empty
                items = _load_learned()
                items.append({'question': question, 'answer': answer, 'metadata': metadata or {}})
                _save_learned(items)
                print(f"[Learn] +1 (total {len(items)}): {question[:50]}")
            except Exception as e:
                print(f"[Learn] failed: {e}")
    threading.Thread(target=_work, daemon=True).start()


def _replay_learned():
    """Re-apply persisted learned Q&A after the base model is loaded."""
    if not hasattr(chatbot, 'add_learned'):
        return
    items = _load_learned()
    n = 0
    for it in items:
        try:
            if chatbot.add_learned(it.get('question', ''), it.get('answer', ''), it.get('metadata')):
                n += 1
        except Exception:
            pass
    if n:
        print(f"[Learn] replayed {n} learned Q&A pair(s).")


# ── Auto-retrain pipeline ───────────────────────────────────────────────────────
# Drop a new .xlsx/.csv into data/qa/ (or edit an existing one) and the model
# retrains itself — on startup if it changed while the app was down, and live via
# a background watcher while the app is running. All offline, no external calls.
import hashlib

FINGERPRINT_FILE = instance_file('dataset_fingerprint')
RETRAIN_POLL_SEC = int(os.environ.get('RETRAIN_POLL_SEC', 20))

_train_lock       = threading.Lock()
_last_fingerprint = None


def discover_datasets():
    """Every Q&A dataset: all .xlsx/.csv files in data/qa/ (Excel lock files skipped)."""
    return [p for p in dataset.qa_files() if '~$' not in os.path.basename(p)]


def refresh_location_dataset():
    """Rebuild the generated "where is room X?" questions when rooms.json changed."""
    try:
        if locations_need_update():
            rows, rooms = write_locations_csv()
            print(f"[Pipeline] Location Q&A regenerated from rooms.json ({rows} rows, {rooms} rooms).")
    except Exception as e:
        print(f"[Pipeline] Could not regenerate location Q&A: {e}")


def dataset_fingerprint():
    """Hash of (name, mtime, size) for every dataset — changes when data changes.
    MODEL_VERSION is mixed in so a model-format change also forces a rebuild."""
    h = hashlib.sha256()
    h.update(MODEL_VERSION.encode('utf-8'))
    for p in discover_datasets():
        try:
            st = os.stat(p)
            h.update(os.path.basename(p).encode('utf-8'))
            h.update(f"{int(st.st_mtime)}:{st.st_size}".encode('utf-8'))
        except OSError:
            pass
    return h.hexdigest()


def _load_fingerprint():
    try:
        with open(FINGERPRINT_FILE, 'r') as f:
            return f.read().strip()
    except OSError:
        return None


def _save_fingerprint(fp):
    try:
        with open(FINGERPRINT_FILE, 'w') as f:
            f.write(fp)
    except OSError:
        pass


def _load_merged_dataframe():
    import pandas as pd
    frames = []
    for p in discover_datasets():
        try:
            df = pd.read_csv(p, encoding='utf-8') if p.lower().endswith('.csv') else pd.read_excel(p)
            frames.append(df)
            print(f"[Pipeline]   + {os.path.basename(p)} ({len(df)} rows)")
        except Exception as e:
            print(f"[Pipeline]   ! skipped {os.path.basename(p)}: {e}")
    if not frames:
        raise FileNotFoundError("No dataset files found.")
    return pd.concat(frames, ignore_index=True, sort=False)


def build_model(force=False):
    """Train a fresh model from ALL datasets, replay learned data, hot-swap it in,
    and persist. Returns True if the model was rebuilt. Thread-safe & non-fatal:
    on any error the currently-served model is left untouched."""
    global chatbot, _last_fingerprint
    with _train_lock:
        fp = dataset_fingerprint()
        if not force and fp == _last_fingerprint:
            return False
        try:
            from server.chatbot import SimpleQAChatbot
            df    = _load_merged_dataframe()
            fresh = SimpleQAChatbot()
            print("[Pipeline] Training merged dataset ...")
            fresh.train_dataframe(df)
            # carry over everything the model has auto-learned so far
            for it in _load_learned():
                try:
                    fresh.add_learned(it.get('question', ''), it.get('answer', ''), it.get('metadata'))
                except Exception:
                    pass
            fresh.save_model(MODEL_PATH)
            _save_fingerprint(fp)
            chatbot = fresh                      # atomic reference swap
            _last_fingerprint = fp
            warm_ai_voices()                     # voice any new answers in the background
            print(f"[Pipeline] Model rebuilt: {len(fresh.questions)} questions "
                  f"from {len(discover_datasets())} dataset(s).")
            return True
        except Exception as e:
            print(f"[Pipeline] Rebuild FAILED, keeping current model: {e}")
            return False


AI_VOICE_LIVE = os.environ.get('AI_VOICE_LIVE', '1') == '1'


def known_answer_texts():
    """Every reply the chatbot can give. This is a bounded set, and only these
    get AI voice lines — arbitrary text sent to /speak keeps the offline TTS."""
    if chatbot is None:
        return set()
    texts = set(getattr(chatbot, 'answers', []) or [])
    try:
        texts.add(chatbot.get_answer('zzqx', threshold=2.0)['answer'])   # the "not found" reply
    except Exception:
        pass
    texts = {t.strip() for t in texts if isinstance(t, str) and t.strip()}
    for lang in i18n.LANGS:                       # English / Mandarin versions
        texts |= i18n.all_translations(lang)
    return texts


def warm_ai_voices():
    """Generate natural voice lines for every answer that has no human
    recording yet — Indonesian, plus the English and Mandarin translations."""
    if AI_VOICE_LIVE and voice_ai.available() and chatbot is not None:
        texts = {t.strip() for t in getattr(chatbot, 'answers', []) if isinstance(t, str) and t.strip()}
        try:
            texts.add(chatbot.get_answer('zzqx', threshold=2.0)['answer'].strip())
        except Exception:
            pass
        voice_ai.generate_in_background(texts, lang='id')
        for lang in i18n.LANGS:
            voice_ai.generate_in_background(i18n.all_translations(lang), lang=lang)


def start_dataset_watcher():
    """Background daemon that retrains when any dataset file (or rooms.json) changes."""
    if RETRAIN_POLL_SEC <= 0:
        return

    def _loop():
        global _last_fingerprint
        while True:
            time.sleep(RETRAIN_POLL_SEC)
            try:
                refresh_location_dataset()
                fp = dataset_fingerprint()
                if fp != _last_fingerprint:
                    # debounce: wait for the file write to settle before training
                    time.sleep(2)
                    if dataset_fingerprint() == fp:
                        print("[Pipeline] Dataset change detected → retraining ...")
                        build_model(force=True)
            except Exception as e:
                print(f"[Pipeline] watcher error: {e}")

    threading.Thread(target=_loop, daemon=True).start()
    print(f"[Pipeline] Dataset watcher active (checks every {RETRAIN_POLL_SEC}s, dir: data/qa).")

try:
    from server.analytics import (
        log_query, log_feedback, log_visit, log_site_feedback,
        get_visit_stats, get_site_feedback,
    )
    ANALYTICS_ENABLED = True
except ImportError:
    ANALYTICS_ENABLED = False
    def log_query(*args, **kwargs): pass
    def log_feedback(*args, **kwargs): pass
    def log_visit(*args, **kwargs): pass
    def log_site_feedback(*args, **kwargs): pass
    def get_visit_stats(*args, **kwargs): return {}
    def get_site_feedback(*args, **kwargs): return {}


def load_whisper():
    """Server-side speech-to-text (fallback when the browser has none). The
    model downloads once; without it voice input falls back gracefully."""
    global whisper_model
    try:
        if USE_FASTER_WHISPER:
            print(f"[Whisper] Loading faster-whisper '{WHISPER_MODEL_SIZE}' (int8 CPU)...")
            whisper_model = _FasterWhisperModel(
                WHISPER_MODEL_SIZE, device="cpu", compute_type="int8"
            )
        else:
            print(f"[Whisper] Loading whisper '{WHISPER_MODEL_SIZE}'...")
            whisper_model = _whisper.load_model(WHISPER_MODEL_SIZE)
        print("[Whisper] Ready.")
    except Exception as e:
        whisper_model = None
        print(f"[Whisper] Not available ({e}) — /transcribe is disabled, browser speech input still works.")
        return
    warmup_whisper()


def warmup_whisper():
    tmp = None
    try:
        dummy = np.zeros(16000, dtype=np.float32)
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            tmp = f.name
        wav_write(tmp, 16000, np.int16(dummy))
        if USE_FASTER_WHISPER:
            segs, _ = whisper_model.transcribe(tmp, language='id', beam_size=1)
            list(segs)
        else:
            whisper_model.transcribe(tmp, language='id', fp16=False)
        print("[Whisper] Warm-up complete.")
    except Exception as e:
        print(f"[Whisper] Warm-up failed: {e}")
    finally:
        if tmp and os.path.exists(tmp):
            os.remove(tmp)


def load_chatbot():
    """Load the cached model if it still matches the datasets, otherwise rebuild.
    Then start the watcher so later dataset changes retrain automatically."""
    global chatbot, _last_fingerprint
    from server.chatbot import SimpleQAChatbot
    refresh_location_dataset()
    chatbot = SimpleQAChatbot()

    cur_fp   = dataset_fingerprint()
    saved_fp = _load_fingerprint()
    try:
        if saved_fp == cur_fp and os.path.exists(MODEL_PATH):
            chatbot.load_model(MODEL_PATH)
            _last_fingerprint = cur_fp
            _replay_learned()
            print(f"[Chatbot] Cached model loaded ({len(chatbot.questions)} questions, dataset unchanged).")
        else:
            reason = "no cached model" if not os.path.exists(MODEL_PATH) else "dataset changed since last build"
            print(f"[Chatbot] Rebuilding ({reason}) ...")
            build_model(force=True)
    except Exception as e:
        print(f"[Chatbot] Load error ({e}) – rebuilding ...")
        build_model(force=True)

    start_dataset_watcher()

    _replay_learned()


def load_audio_mapping():
    global audio_mapping
    if not os.path.isdir(AUDIO_FOLDER):
        print(f"[Audio] Folder '{AUDIO_FOLDER}' not found.")
        return
    for fname in sorted(os.listdir(AUDIO_FOLDER)):
        if fname.lower().endswith(('.mp3', '.wav', '.mpeg', '.ogg')):
            if fname == READY_AUDIO_NAME:
                continue
            try:
                num = int(''.join(filter(str.isdigit, fname)))
                audio_mapping[num] = os.path.join(AUDIO_FOLDER, fname)
            except ValueError:
                pass
    print(f"[Audio] {len(audio_mapping)} files → IDs {sorted(audio_mapping.keys())}")


def init_tts():
    """Offline fallback voice (Windows SAPI5 / espeak-ng on Linux), run per
    request in a child process (server/offline_tts.py) so a stuck engine can
    never block the server. Optional: without it, /speak serves only the
    pre-generated AI voice lines."""
    global TTS_AVAILABLE
    TTS_AVAILABLE = offline_tts.available()
    print("[TTS] Offline fallback voice ready." if TTS_AVAILABLE
          else "[TTS] Offline voice not available — only pre-generated voice lines will play.")


with app.app_context():
    load_whisper()
    load_chatbot()
    load_audio_mapping()
    init_tts()
    warm_ai_voices()     # cached model path doesn't go through build_model()


def convert_webm_to_wav(inp, out, sr=16000):
    # Call ffmpeg directly: pydub's from_file() would also need ffprobe.
    if not FFMPEG_EXE:
        raise RuntimeError('ffmpeg not available')
    subprocess.run(
        [FFMPEG_EXE, '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
         '-i', inp, '-ac', '1', '-ar', str(sr), '-t', '60', out],
        check=True, timeout=60, capture_output=True)


def apply_noise_reduction(wav_in, wav_out):
    sr, data = wav_read(wav_in)
    if data.ndim > 1:
        data = data[:, 0]
    data = data.astype(np.float32) / 32768.0
    noise = data[:int(0.5 * sr)]      # first 0.5 s as noise profile
    reduced = nr.reduce_noise(
        y=data, sr=sr, y_noise=noise,
        prop_decrease=0.9,
        stationary=True,               # 5-10× faster than non-stationary
        n_fft=1024,
    )
    peak = max(np.max(np.abs(reduced)), 1e-6)
    wav_write(wav_out, sr, np.int16(reduced / peak * 32767))


def trim_wav_silence(wav_in, wav_out, silence_thresh=-38, padding_ms=100):
    """Strip leading/trailing silence so Whisper processes less audio."""
    from pydub import silence as pdub_sil
    audio = AudioSegment.from_wav(wav_in)
    chunks = pdub_sil.detect_nonsilent(
        audio, min_silence_len=200, silence_thresh=silence_thresh
    )
    if chunks:
        start = max(0, chunks[0][0] - padding_ms)
        end   = min(len(audio), chunks[-1][1] + padding_ms)
        audio = audio[start:end]
    audio.export(wav_out, format='wav')


TTS_TIMEOUT_SEC = 20


def tts_to_file(text, lang='id'):
    if not TTS_AVAILABLE:
        raise RuntimeError('offline TTS not available')
    # One request at a time; a request that can't get its turn soon gives up.
    if not tts_lock.acquire(timeout=TTS_TIMEOUT_SEC):
        raise RuntimeError('offline TTS busy')
    path = _temp_path('.wav')
    try:
        proc = subprocess.run(
            [sys.executable, '-m', 'server.offline_tts', path, lang],
            input=text.encode('utf-8'), cwd=os.path.dirname(os.path.abspath(__file__)),
            timeout=TTS_TIMEOUT_SEC, capture_output=True,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if proc.returncode != 0 or not os.path.exists(path) or os.path.getsize(path) < 1000:
            raise RuntimeError(f'offline TTS failed (exit {proc.returncode})')
        return path
    except Exception:
        if os.path.exists(path):
            os.remove(path)
        raise
    finally:
        tts_lock.release()


def deferred_remove(path, delay=3):
    def _rm():
        time.sleep(delay)
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
    threading.Thread(target=_rm, daemon=True).start()


def _temp_path(suffix):
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        return f.name


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/landing')
def landing():
    return render_template('landing.html')


@app.route('/about')
def about():
    return render_template('about.html')


@app.route('/healthz')
def healthz():
    """Liveness/readiness probe for the hosting platform."""
    ready = chatbot is not None
    return jsonify({'status': 'ok' if ready else 'starting'}), 200 if ready else 503


@app.errorhandler(404)
def not_found(_error):
    if request.path.startswith(('/api/', '/admin/api/')):
        return jsonify({'status': 'error', 'message': 'Not found.'}), 404
    return render_template('404.html'), 404


def _wants_json():
    return request.is_json or request.path.startswith(('/admin/', '/api/')) or request.method != 'GET'


@app.errorhandler(405)
def method_not_allowed(_error):
    return jsonify({'status': 'error', 'message': 'Method not allowed.'}), 405


@app.errorhandler(413)
def too_large(_error):
    return jsonify({'status': 'error', 'message': 'Upload is too large.'}), 413


@app.errorhandler(500)
def server_error(_error):
    # Flask has already logged the traceback server-side; the visitor only
    # gets a generic message — never internal details.
    if _wants_json():
        return jsonify({'status': 'error', 'message': 'Internal server error.'}), 500
    return 'Something went wrong on our side. Please try again later.', 500


@app.route('/rooms.json')
def serve_rooms():
    """The single source of truth for map rooms (also drives the location Q&A)."""
    resp = send_file(ROOMS_JSON, mimetype='application/json', max_age=0)
    resp.headers['Cache-Control'] = 'no-cache'
    return resp


@app.route('/qr')
@rate_limited('qr', limit=30, window_seconds=60)
def serve_qr():
    """Generate an OFFLINE QR code (PNG) for arbitrary text — used by the
    'take directions to your phone' feature. No internet required."""
    import io
    text = request.args.get('text', '').strip() or 'Infosphere'
    if len(text) > 800:
        return jsonify({'error': 'Text too long'}), 400
    try:
        import qrcode
        img = qrcode.make(text)
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        return send_file(buf, mimetype='image/png')
    except ImportError:
        return jsonify({'error': "qrcode not installed — run: pip install qrcode"}), 501
    except Exception as e:
        print(f'[QR] failed: {e}')
        return jsonify({'error': 'Could not generate QR code'}), 500


@app.route('/transcribe', methods=['POST'])
@rate_limited('transcribe', limit=20, window_seconds=60)
def transcribe():
    if whisper_model is None:
        return jsonify({'error': 'Voice input is not available on this server right now.'}), 503
    if 'audio' not in request.files:
        return jsonify({'error': 'No audio file'}), 400
    upload = request.files['audio']
    # Only audio is accepted; it is converted by ffmpeg into a temp file, read,
    # and deleted — never stored, served, or executed.
    if upload.mimetype and not upload.mimetype.startswith(('audio/', 'video/webm', 'application/octet-stream')):
        return jsonify({'error': 'Unsupported file type'}), 400

    ui_lang      = request.form.get('lang', 'IND').upper()
    whisper_lang = LANG_MAP.get(ui_lang, 'id')
    tmp_in = tmp_wav = tmp_nr = tmp_trimmed = None

    try:
        tmp_in = _temp_path('.webm')
        upload.save(tmp_in)

        tmp_wav = _temp_path('.wav')
        convert_webm_to_wav(tmp_in, tmp_wav)

        tmp_nr = _temp_path('.wav')
        apply_noise_reduction(tmp_wav, tmp_nr)

        tmp_trimmed = _temp_path('.wav')
        trim_wav_silence(tmp_nr, tmp_trimmed)

        if USE_FASTER_WHISPER:
            segments, info = whisper_model.transcribe(
                tmp_trimmed,
                language=whisper_lang,
                beam_size=1,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 300},
            )
            text          = " ".join(s.text for s in segments).strip()
            detected_lang = info.language
        else:
            result = whisper_model.transcribe(
                tmp_trimmed,
                language=whisper_lang,
                fp16=False,
                beam_size=1,
                best_of=1,
                temperature=0.0,
                no_speech_threshold=0.5,
                condition_on_previous_text=False,
            )
            text          = result['text'].strip()
            detected_lang = result.get('language', whisper_lang)

        if not text:
            return jsonify({'error': 'empty'}), 200

        return jsonify({'transcript': text[:CHAT_MAX_CHARS], 'detected_lang': detected_lang})

    except Exception:
        import traceback; traceback.print_exc()
        return jsonify({'error': 'Could not process the recording'}), 500
    finally:
        for p in [tmp_in, tmp_wav, tmp_nr, tmp_trimmed]:
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass


_chat_executor = ThreadPoolExecutor(max_workers=4)


@app.route('/chat', methods=['POST'])
@rate_limited('chat', limit=60, window_seconds=60)
def chat():
    data     = request.get_json(silent=True) or {}
    lang     = str(data.get('lang') or 'IND').upper()
    if lang not in LANG_MAP:
        lang = 'IND'
    try:
        question = clean_text(data.get('question'), CHAT_MAX_CHARS, field='Question',
                              required=True, multiline=False)
    except ValidationError as e:
        return jsonify({'error': 'invalid', 'message': str(e)}), 400
    if chatbot is None:
        return jsonify({'error': 'starting', 'message': 'The assistant is still starting — try again in a moment.'}), 503
    try:
        t0     = time.time()
        threshold = MATCH_THRESHOLD_ZH if _CJK_RE.search(question) and not _LATIN_RE.search(question) else MATCH_THRESHOLD
        result = _chat_executor.submit(chatbot.get_answer, question, threshold).result(timeout=CHAT_TIMEOUT_SEC)
        ms     = int((time.time() - t0) * 1000)

        conf  = float(result.get('confidence', 0))
        found = bool(result.get('found', conf >= threshold))

        # Auto-learn: a close paraphrase of a known question → remember this phrasing
        if found and LEARN_THRESHOLD <= conf < 0.999:
            learn_question(question, result.get('answer', ''), result.get('metadata'))

        audio_id = result.get('metadata', {}).get('id') if (found and result.get('metadata')) else None
        try:
            audio_id = int(audio_id) if audio_id is not None else None
        except (TypeError, ValueError):
            audio_id = None

        matched_room = result.get('metadata', {}).get('keywords') if found else None
        # Room answers carry the room id (Keywords column) — the page routes to it directly.
        room_id = str(matched_room).strip() if matched_room is not None else None
        if room_id not in dataset.rooms_by_id(dataset.load_rooms()):
            room_id = room_for_qa_id(audio_id) if found else None   # e.g. "Dimana LKC?" → route to the LKC
        log_query(question, result.get('answer', ''), conf, lang, ms,
                  matched_room=matched_room, found=found)

        # ENG / 汉 visitors get the translated answer (and an AI voice in that
        # language instead of the Indonesian recording) when one exists.
        answer = str(result.get('answer', ''))
        translated = i18n.translate(answer, lang)
        if translated:
            answer, audio_id = translated, None

        # The answer is plain text from our own dataset; the page still renders
        # it with textContent, never as HTML.
        return jsonify({
            'answer':         answer,
            'answer_lang':    i18n.UI_LANG.get(lang, 'id') if translated else 'id',
            'room_id':        room_id,
            'confidence':     round(conf * 100, 1),
            'found':          found,
            'audio_id':       audio_id,
            'has_audio_file': (audio_id in audio_mapping) if audio_id else False,
        })
    except FutureTimeout:
        print(f'[Chat] timed out after {CHAT_TIMEOUT_SEC}s: {question[:60]!r}')
        return jsonify({'error': 'timeout', 'message': 'The assistant took too long to answer — please try again.'}), 504
    except Exception:
        import traceback; traceback.print_exc()
        return jsonify({'error': 'internal', 'message': 'The assistant is unavailable right now — please try again.'}), 500


@app.route('/api/room-answer/<room_id>')
@rate_limited('room-answer', limit=120, window_seconds=60)
def room_answer(room_id):
    """The chatbot's answer for one map room in the visitor's language (spoken
    when someone taps the room on the map)."""
    lang = str(request.args.get('lang') or 'IND').upper()
    from server.qa_locations import room_entries
    for _i, room, _display, answer in room_entries():
        if room['id'] == room_id:
            # A room linked to a spreadsheet row (qa_id) answers like typing
            # the question: that row's answer, with its human recording.
            audio_id = None
            sheet_answer = qa_answer_by_id(room.get('qa_id'))
            if sheet_answer:
                answer, audio_id = sheet_answer, room['qa_id']
            translated = i18n.translate(answer, lang)
            if translated:
                answer, audio_id = translated, None
            return jsonify({'room_id': room_id, 'answer': answer,
                            'answer_lang': i18n.UI_LANG.get(lang, 'id') if translated else 'id',
                            'audio_id': audio_id,
                            'has_audio_file': (audio_id in audio_mapping) if audio_id else False})
    return jsonify({'status': 'error', 'message': 'Room not found.'}), 404


def qa_answer_by_id(qa_id):
    """The chatbot's answer for a spreadsheet ID (first row with that ID), or None."""
    if qa_id is None or chatbot is None:
        return None
    ids = chatbot.metadata.get('ids') or []
    for i, row_id in enumerate(ids):
        try:
            if int(row_id) == int(qa_id):
                return str(chatbot.answers[i]).strip() or None
        except (TypeError, ValueError):
            continue
    return None


def room_for_qa_id(qa_id):
    """Id of the map room linked to a spreadsheet ID (rooms.json qa_id), or None."""
    if qa_id is None:
        return None
    return next((r['id'] for r in dataset.load_rooms()['rooms'] if r.get('qa_id') == qa_id), None)


@app.route('/status')
def status():
    # The LAN address is only useful (and only shown) on the local kiosk network.
    if app.config.get('IS_PRODUCTION'):
        return jsonify({'status': 'ok'})
    import socket
    try:
        ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        ip = '127.0.0.1'
    return jsonify({'status': 'ok', 'ip': ip, 'port': int(os.environ.get('PORT', 5000))})


@app.route('/speak', methods=['POST'])
@rate_limited('speak', limit=30, window_seconds=60)
def speak():
    data     = request.get_json(silent=True) or {}
    text     = str(data.get('text') or '').strip()
    raw_lang = str(data.get('lang') or 'id').lower()
    lang     = LANG_CODE_NORMALIZE.get(raw_lang, 'id')
    if not text:
        return jsonify({'error': 'Empty text'}), 400
    if len(text) > 1000:
        return jsonify({'error': 'Text too long'}), 400
    if text in known_answer_texts():
        # Not made yet (new or edited answer): make it now rather than fall
        # back to the robotic offline voice.
        ai_path = voice_ai.cached(text, lang) or (AI_VOICE_LIVE and voice_ai.generate_now(text, lang))
        if ai_path:
            return send_file(ai_path, mimetype='audio/mpeg', max_age=86400)
        if AI_VOICE_LIVE:
            voice_ai.generate_in_background([text], lang)   # ready for the next visitor
    try:
        path = tts_to_file(text, lang)
        deferred_remove(path)
        return send_file(path, mimetype='audio/wav')
    except Exception as e:
        print(f'[TTS] failed: {e}')
        return jsonify({'error': 'Speech synthesis failed'}), 503


@app.route('/audio/<int:audio_id>')
def serve_audio(audio_id):
    path = audio_mapping.get(audio_id)
    if not path or not os.path.exists(path):
        return jsonify({'error': 'Not found'}), 404
    return send_file(path)


@app.route('/audio/ready')
def serve_ready_audio():
    path = os.path.join(AUDIO_FOLDER, READY_AUDIO_NAME)
    if not os.path.exists(path):
        return jsonify({'error': 'Ready audio not found'}), 404
    return send_file(path)


@app.route('/feedback', methods=['POST'])
@rate_limited('thumbs', limit=30, window_seconds=60)
def feedback():
    data = request.get_json(silent=True) or {}
    try:
        question = clean_text(data.get('question'), 500, multiline=False)
    except ValidationError:
        question = ''
    log_feedback(question=question, positive=data.get('positive') is not False)
    return jsonify({'status': 'ok'})


@app.route('/feedback', methods=['GET'])
def feedback_page():
    return render_template('feedback.html')


FEEDBACK_MAX = 1000


def _feedback_error(message, status=400):
    return jsonify({'status': 'error', 'message': message}), status


@app.route('/feedback/submit', methods=['POST'])
@rate_limited('feedback-submit', limit=5, window_seconds=600)
def submit_site_feedback():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _feedback_error('Invalid request.')

    # Honeypot: a hidden field real visitors never fill. If it's set, silently
    # pretend success — don't tip off whatever filled it.
    if str(data.get('website') or '').strip():
        return jsonify({'status': 'ok'})

    try:
        message = clean_text(data.get('message'), FEEDBACK_MAX, field='Message', required=True, min_len=3)
        name    = clean_text(data.get('name'), 100, field='Name', multiline=False)
        email   = clean_text(data.get('email'), 254, field='Contact', multiline=False)
        page    = clean_text(data.get('page'), 300, field='Page', multiline=False)
    except ValidationError as e:
        return _feedback_error(str(e))
    if data.get('anonymous') is True:
        name, email = '', ''

    rating = data.get('rating')
    try:
        rating = int(rating) if rating not in (None, '') else None
        if rating is not None and not (1 <= rating <= 5):
            rating = None
    except (TypeError, ValueError):
        rating = None

    category = data.get('category') or 'Other'
    if category not in db.FEEDBACK_CATEGORIES:
        category = 'Other'

    try:
        log_site_feedback(name=name, email=email, category=category,
                          message=message, rating=rating, page_url=page)
    except Exception as e:
        print(f'[Feedback] could not save: {e}')
        return _feedback_error('Could not save your feedback — please try again later.', 500)
    return jsonify({'status': 'ok'})


# ── Admin: login / logout ───────────────────────────────────────────────────────

@app.route('/admin/login', methods=['GET', 'POST'])
@rate_limited('login-page', limit=30, window_seconds=60)
def admin_login():
    next_url = safe_next_url(request.values.get('next'))
    if request.method == 'GET':
        if is_admin():
            return redirect(next_url)
        return render_template('admin_login.html', error=None, next_url=next_url,
                               configured=admin_configured(), username='')

    username = (request.form.get('username') or '').strip()
    password = request.form.get('password') or ''
    ip = client_ip()

    def fail(message, status=401):
        return render_template('admin_login.html', error=message, next_url=next_url,
                               configured=admin_configured(), username=username[:100]), status

    if csrf_failed():
        return fail('Your session expired. Please try again.', 400)
    if not admin_configured():
        return fail('Admin login is disabled until a password is set (run scripts/set_admin_password.py).', 503)
    locked = login_lock_remaining(ip)
    if locked:
        return fail(f'Too many failed attempts. Try again in {max(1, locked // 60)} minute(s).', 429)
    if not verify_admin(username, password):
        record_login_failure(ip)
        print(f'[Admin] failed login attempt from {ip}')
        return fail('Incorrect username or password.')

    reset_login_failures(ip)
    start_admin_session(username)
    print(f'[Admin] login from {ip}')
    return redirect(next_url)


@app.route('/admin/logout', methods=['POST'])
def admin_logout():
    end_admin_session()
    return redirect(url_for('admin_login'))


# ── Admin: pages ────────────────────────────────────────────────────────────────

@app.route('/admin')
@require_admin_page
def admin():
    return render_template('admin.html', active='dashboard')


@app.route('/admin/feedback')
@require_admin_page
def admin_feedback_page():
    return render_template('admin_feedback.html', active='feedback')


# ── Admin: JSON APIs ────────────────────────────────────────────────────────────

@app.route('/admin/visits')
@require_admin
def admin_visits():
    try:
        return jsonify(get_visit_stats())
    except Exception as e:
        print(f'[Admin] visit stats failed: {e}')
        return jsonify({'error': 'Could not load visit stats'}), 500


@app.route('/admin/summary')
@require_admin
def admin_summary():
    """Numbers for the dashboard cards: visits + feedback at a glance."""
    try:
        v = get_visit_stats()
        f = db.feedback_summary()
        return jsonify({
            'visits_total':    v['total'],
            'visits_today':    v['today'],
            'visits_7d':       v['last_7_days'],
            'unique_visitors': v['unique_visitors'],
            'feedback_total':  f['total'],
            'feedback_unread': f['unread'],
        })
    except Exception as e:
        print(f'[Admin] summary failed: {e}')
        return jsonify({'error': 'Could not load summary'}), 500


@app.route('/admin/site-feedback')
@require_admin
def admin_site_feedback():
    page     = request.args.get('page', 1, type=int) or 1
    per_page = min(max(request.args.get('per_page', 10, type=int) or 10, 5), 50)
    status   = request.args.get('status', 'all')
    category = request.args.get('category', '')
    if status not in ('all', 'read', 'unread'):
        status = 'all'
    try:
        return jsonify(get_site_feedback(page=page, per_page=per_page,
                                         status=status, category=category))
    except Exception as e:
        print(f'[Admin] feedback list failed: {e}')
        return jsonify({'error': 'Could not load feedback'}), 500


@app.route('/admin/site-feedback/<int:feedback_id>/read', methods=['POST'])
@require_admin
def admin_feedback_mark(feedback_id):
    data = request.get_json(silent=True) or {}
    if not db.set_feedback_read(feedback_id, bool(data.get('read', True))):
        return jsonify({'status': 'error', 'message': 'Feedback not found'}), 404
    return jsonify({'status': 'ok'})


@app.route('/admin/site-feedback/read-all', methods=['POST'])
@require_admin
def admin_feedback_mark_all():
    return jsonify({'status': 'ok', 'updated': db.mark_all_feedback_read()})


@app.route('/admin/site-feedback/<int:feedback_id>', methods=['DELETE'])
@require_admin
def admin_feedback_delete(feedback_id):
    if not db.delete_feedback(feedback_id):
        return jsonify({'status': 'error', 'message': 'Feedback not found'}), 404
    return jsonify({'status': 'ok'})


@app.route('/admin/stats')
@require_admin
def admin_stats():
    try:
        from server.analytics import get_stats
        return jsonify(get_stats())
    except Exception as e:
        print(f'[Admin] stats failed: {e}')
        return jsonify({
            'total': 0, 'today': 0, 'avg_ms': 0, 'avg_conf': 0,
            'lang_counts': {}, 'conf_buckets': {}, 'top_questions': [],
            'feedback_pos': 0, 'feedback_neg': 0, 'hourly': {}, 'recent': [],
            'unanswered': [], 'unanswered_total': 0,
        })


@app.route('/admin/export')
@require_admin
def admin_export():
    """Return all logs as JSON for client-side CSV export."""
    try:
        from server.analytics import get_all_logs
        return jsonify(get_all_logs())
    except Exception:
        return jsonify([])


@app.route('/admin/retrain', methods=['POST'])
@require_admin
@rate_limited('retrain', limit=6, window_seconds=60)
def retrain():
    try:
        build_model(force=True)
        return jsonify({
            'status':  'ok',
            'message': f'Model retrained: {len(chatbot.questions)} questions '
                       f'from {len(discover_datasets())} dataset(s).',
            'questions': len(chatbot.questions),
            'datasets':  [os.path.basename(p) for p in discover_datasets()],
        })
    except Exception as e:
        print(f'[Admin] retrain failed: {e}')
        return jsonify({'status': 'error', 'message': 'Retrain failed — see server log.'}), 500


@app.route('/admin/datasets')
@require_admin
def admin_datasets():
    """List the datasets feeding the model and the current training status."""
    return jsonify({
        'datasets': [
            {'name': os.path.basename(p), 'modified': int(os.path.getmtime(p))}
            for p in discover_datasets()
        ],
        'questions':      len(chatbot.questions) if chatbot else 0,
        'watcher_seconds': RETRAIN_POLL_SEC,
        'fingerprint':    (_last_fingerprint or '')[:12],
    })


# Admin-supplied answer for an unanswered question. Appended to a CSV dataset so
# it flows through the normal pipeline (merged + retrained + persisted on disk).
TAUGHT_DATASET = instance_file("admin_taught.csv")
_teach_lock    = threading.Lock()


@app.route('/admin/teach', methods=['POST'])
@require_admin
@rate_limited('teach', limit=20, window_seconds=60)
def admin_teach():
    import csv
    data = request.get_json(silent=True) or {}
    try:
        question = clean_text(data.get('question'), 300, field='Question', required=True, multiline=False)
        answer   = clean_text(data.get('answer'), 1000, field='Answer', required=True)
    except ValidationError as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400
    try:
        with _teach_lock:
            new_file = not os.path.exists(TAUGHT_DATASET)
            with open(TAUGHT_DATASET, 'a', newline='', encoding='utf-8') as f:
                w = csv.writer(f)
                if new_file:
                    w.writerow(['Question', 'Answer', 'Category', 'Keywords',
                                'Difficulty', 'Confidence', 'Confidence', 'ID'])
                w.writerow([question, answer, 'Location', 'AdminTaught',
                            'Easy', 0.9, 0.9, 100])
        build_model(force=True)          # retrain immediately so it answers now
        return jsonify({'status': 'ok', 'message': 'Learned. Model retrained.',
                        'questions': len(chatbot.questions)})
    except Exception as e:
        print(f'[Admin] teach failed: {e}')
        return jsonify({'status': 'error', 'message': 'Could not save the answer — see server log.'}), 500


if __name__ == "__main__":
    import socket
    hostname = socket.gethostname()
    try:
        local_ip = socket.gethostbyname(hostname)
    except OSError:
        local_ip = '127.0.0.1'
    host = os.environ.get('HOST', '0.0.0.0')
    port = int(os.environ.get('PORT', 5000))
    print("\n╔══════════════════════════════════════════╗")
    print("║  Infosphere running!                     ║")
    print(f"║  Local :  http://127.0.0.1:{port}          ║")
    print(f"║  Network: http://{local_ip}:{port}{' ' * max(0, 17-len(local_ip))}║")
    print("║  Admin :  /admin/login                   ║")
    print("╚══════════════════════════════════════════╝\n")
    try:
        # Production-grade WSGI server (pure Python, works on Windows and Linux).
        from waitress import serve
        serve(app, host=host, port=port, threads=int(os.environ.get('THREADS', 8)))
    except ImportError:
        if app.config.get('IS_PRODUCTION'):
            raise SystemExit('waitress is required in production: pip install waitress')
        app.run(host=host, port=port, debug=False, threaded=True, use_reloader=False)
