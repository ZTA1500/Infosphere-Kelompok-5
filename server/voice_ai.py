"""Natural AI voice lines for chatbot answers.

Answers that have no human recording in static/audio/ are spoken with a Microsoft
neural voice (via the `edge-tts` package) instead of the robotic built-in
Windows voice. Each line is generated once, saved as an MP3 in instance/voice-cache/, and
played from disk after that — so the kiosk keeps working offline. Until a line
exists (no internet yet, package missing), the old offline TTS is used.

Generation runs in a separate worker process (this file run as a script), so
network hiccups or slow responses never touch the web server. The server only
reads the finished MP3s.

    python -m server.voice_ai "Teks yang mau dibacakan"   # one line, by hand

Voices can be changed in .env: AI_VOICE_ID, AI_VOICE_EN, AI_VOICE_ZH.
List all voices with:  .venv\\Scripts\\edge-tts --list-voices
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time

from server.paths import ROOT, VOICE_CACHE as CACHE_DIR, ENV_FILE

# Common Indonesian words — the dataset answers are Indonesian even when a
# visitor picked ENG, so pick the voice from the text, not only the UI setting.
_ID_WORDS = {'di', 'dan', 'yang', 'ke', 'dari', 'berada', 'lantai', 'lokasi', 'maaf', 'saya',
             'gedung', 'samping', 'depan', 'setelah', 'menuju', 'ruangan', 'dapat', 'ini',
             'itu', 'untuk', 'dengan', 'naik', 'turun', 'kanan', 'kiri', 'lurus', 'ada'}


def voices():
    return {
        'id': os.environ.get('AI_VOICE_ID', 'id-ID-GadisNeural'),
        'en': os.environ.get('AI_VOICE_EN', 'en-US-AvaMultilingualNeural'),
        'zh': os.environ.get('AI_VOICE_ZH', 'zh-CN-XiaoxiaoNeural'),
    }


def available():
    try:
        import edge_tts  # noqa: F401
        return True
    except ImportError:
        return False


_DIGITS_ID = 'nol satu dua tiga empat lima enam tujuh delapan sembilan'.split()
_DIGITS_EN = 'zero one two three four five six seven eight nine'.split()
_DIGITS_ZH = list('零一二三四五六七八九')
_DIGITS = {'id': (_DIGITS_ID, 'sampai'), 'en': (_DIGITS_EN, 'to'), 'zh': (_DIGITS_ZH, '到')}
# ASCII-only boundaries: in Mandarin text "C0207位于" has no \b between 7 and 位.
_ROOM_CODE_RE = re.compile(r'(?<![0-9A-Za-z])([A-Z])(\d{4})(?:-(\d{2}))?(?![0-9A-Za-z])')
# Abbreviations that should be spelled letter by letter, not read as a word.
_ACRONYMS = {'LSC', 'SSC', 'SADC', 'SDC', 'BCA', 'UKM', 'IT', 'LKC', 'TV', 'GOR', 'P3K'}


def spoken_form(text, lang='id'):
    """How a line should be pronounced: room codes digit by digit ("C0207" ->
    "C, nol dua nol tujuh,") and abbreviations letter by letter ("LSC" ->
    "L S C"). Only the audio changes — the cache key stays the original text."""
    digits, until = _DIGITS.get(lang, _DIGITS['en'])

    def code(m):
        out = f"{m.group(1)}, {' '.join(digits[int(d)] for d in m.group(2))}"
        if m.group(3):
            out += f" {until} {' '.join(digits[int(d)] for d in m.group(3))}"
        return out + ','

    text = re.sub(r'(?<=[A-Za-z]) (?=[A-Z]\d{4}(?![0-9A-Za-z]))', ', ', text)     # short pause before a code
    text = _ROOM_CODE_RE.sub(code, text)
    text = re.sub(r'(?<![0-9A-Za-z])[A-Z0-9]{2,4}(?![0-9A-Za-z])',
                  lambda m: ' '.join(m.group(0)) if m.group(0) in _ACRONYMS else m.group(0), text)
    return re.sub(r',\s*([.,])', r'\1', text)


def voice_lang(text, requested='id'):
    if re.search(r'[一-鿿]', text):
        return 'zh'
    words = re.findall(r'[a-z]+', text.lower())
    if words and sum(w in _ID_WORDS for w in words) / len(words) >= 0.1:
        return 'id'
    return requested if requested in voices() else 'id'


def cache_path(text, lang='id'):
    voice = voices()[voice_lang(text, lang)]
    key = hashlib.sha256(f'{voice}|{text.strip()}'.encode('utf-8')).hexdigest()[:32]
    return os.path.join(CACHE_DIR, f'{key}.mp3')


def cached(text, lang='id'):
    """Path of the finished MP3, or None (missing, or still being written)."""
    path = cache_path(text, lang)
    return path if os.path.exists(path) and not os.path.exists(path + '.pending') else None


# ── Server side: queue work for the worker process ─────────────────────────────

_pending = set()
_queue_lock = threading.Lock()
_queue_wakeup = threading.Event()
_queue_thread = None


def generate_in_background(texts, lang='id'):
    """Queue lines that don't have an MP3 yet. A single worker process handles
    them one batch at a time; this never blocks the caller."""
    global _queue_thread
    missing = {(lang, t.strip()) for t in texts if t and t.strip() and not cached(t, lang)}
    if not missing or not available():
        return
    with _queue_lock:
        _pending.update(missing)               # (lang, text) pairs: each line keeps its language
        if _queue_thread is None or not _queue_thread.is_alive():
            _queue_thread = threading.Thread(target=_run_queue, daemon=True)
            _queue_thread.start()
    _queue_wakeup.set()


def _run_queue():
    while True:
        _queue_wakeup.wait(timeout=60)
        _queue_wakeup.clear()
        with _queue_lock:
            batch = sorted(_pending)
            _pending.clear()
        for lang in sorted({lg for lg, _ in batch}):
            texts = [t for lg, t in batch if lg == lang]
            try:
                proc = subprocess.Popen(
                    [sys.executable, '-m', 'server.voice_ai', '--worker', '--lang', lang],
                    stdin=subprocess.PIPE, cwd=ROOT,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                proc.communicate(json.dumps(texts).encode('utf-8'), timeout=30 * len(texts) + 30)
            except Exception as e:
                print(f'[AI voice] worker failed: {e}')
                time.sleep(300)          # probably offline — try again later
                break


# ── Worker side: actually create the MP3 files ─────────────────────────────────

def _generate(text, lang='id', timeout=30):
    path = cache_path(text, lang)
    marker = path + '.pending'
    if os.path.exists(path) and not os.path.exists(marker):
        return True
    voice = voices()[voice_lang(text, lang)]
    os.makedirs(CACHE_DIR, exist_ok=True)
    # Write straight to the final name and flag it with a marker file while in
    # progress. (The usual write-to-temp-then-rename trick is deliberately NOT
    # used: renaming freshly written audio files looks like ransomware to this
    # PC's security software, which then kills the process on the 3rd rename.)
    ok = False
    try:
        with open(marker, 'w') as f:
            f.write(str(os.getpid()))
        import asyncio
        import edge_tts

        say = spoken_form(text, voice_lang(text, lang))

        async def _run():
            await asyncio.wait_for(edge_tts.Communicate(say, voice).save(path), timeout)

        asyncio.run(_run())
        if os.path.getsize(path) < 1000:
            raise RuntimeError('empty audio returned')
        ok = True
        print(f'[AI voice] + {voice}: {text[:50]}', flush=True)
        return True
    except Exception as e:
        print(f'[AI voice] could not generate ({type(e).__name__}: {e}) — offline TTS stays in use.', flush=True)
        return False
    finally:
        for p in ([marker] if ok else [path, marker]):
            try:
                os.remove(p)
            except OSError:
                pass


def _main():
    import argparse
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    try:
        from server.security import load_env_file
        load_env_file(ENV_FILE)     # custom AI_VOICE_* settings
    except Exception:
        pass
    ap = argparse.ArgumentParser(description='Generate AI voice lines into instance/voice-cache/.')
    ap.add_argument('text', nargs='*', help='text to voice (omit with --worker)')
    ap.add_argument('--lang', default='id')
    ap.add_argument('--worker', action='store_true', help='read a JSON list of texts from stdin')
    args = ap.parse_args()
    texts = json.load(sys.stdin) if args.worker else [' '.join(args.text)]
    for t in texts:
        if t and t.strip():
            if not _generate(t.strip(), args.lang):
                break                       # offline — don't hammer the network


if __name__ == '__main__':
    _main()
