"""Offline fallback voice (Windows SAPI5 / espeak-ng), run in its own process.

    echo "Teks" | python -m server.offline_tts out.wav id

pyttsx3 can hang inside a long-running web server (its run loop is not
thread-safe and some texts stall the engine). Running every request in a
short-lived child process — with a timeout in app.py — means a stuck engine
can never block the server. The natural AI voice lines (server/voice_ai.py)
cover all known answers, so this is only a last resort.
"""
import re
import sys

LANG_VOICE_KEYWORDS = {
    'id': ['indonesian', 'indonesia'],
    'en': ['english'],
    'zh': ['chinese', 'mandarin'],
}


def _speaks(v, code):
    """Does this voice speak `code`? By name, by its language list, or by a
    language code inside its id ("TTS_MS_ID-ID_ANDIKA") — a whole code, so
    "DAVID_11" doesn't count as Indonesian."""
    if any(kw in v.name.lower() for kw in LANG_VOICE_KEYWORDS.get(code, [])):
        return True
    langs = [str(x).lower() for x in (getattr(v, 'languages', None) or [])]
    if any(x == code or x.startswith(code + '-') or x.startswith(code + '_') for x in langs):
        return True
    return re.search(rf'(?<![a-z]){code}[-_]', v.id.lower()) is not None


def available():
    try:
        import pyttsx3  # noqa: F401
        return True
    except ImportError:
        return False


FEMALE_NAMES = ('zira', 'hazel', 'susan', 'aria', 'jenny', 'huihui', 'yaoyao', 'hanhan', 'gadis', 'female')


def _is_female(v):
    return (getattr(v, 'gender', None) or '').lower() == 'female' or any(n in v.name.lower() for n in FEMALE_NAMES)


def _pick_voice(engine, lang):
    # Female voices first, to match the natural AI voices (Gadis / Ava / Xiaoxiao).
    voices = sorted(engine.getProperty('voices') or [], key=lambda v: not _is_female(v))
    for code in (lang, 'en'):
        for v in voices:
            if _speaks(v, code):
                engine.setProperty('voice', v.id)
                return code
    return None


def main():
    out, lang = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else 'id')
    text = sys.stdin.buffer.read().decode('utf-8').strip()
    import pyttsx3
    try:
        engine = pyttsx3.init('sapi5')
    except Exception:
        engine = pyttsx3.init()
    if _pick_voice(engine, lang) != lang and lang == 'zh':
        sys.exit(3)                     # no Chinese voice installed: don't read Mandarin with an English voice
    engine.setProperty('rate', 150)
    engine.setProperty('volume', 1.0)
    engine.save_to_file(text, out)
    engine.runAndWait()


if __name__ == '__main__':
    main()
