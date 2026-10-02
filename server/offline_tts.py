"""Offline fallback voice (Windows SAPI5 / espeak-ng), run in its own process.

    echo "Teks" | python -m server.offline_tts out.wav id

pyttsx3 can hang inside a long-running web server (its run loop is not
thread-safe and some texts stall the engine). Running every request in a
short-lived child process — with a timeout in app.py — means a stuck engine
can never block the server. The natural AI voice lines (server/voice_ai.py)
cover all known answers, so this is only a last resort.
"""
import sys

LANG_VOICE_KEYWORDS = {
    'id': ['indonesian', 'indonesia', 'id_', 'id-'],
    'en': ['english', 'en_us', 'en_gb', 'en-us', 'en-gb'],
    'zh': ['chinese', 'mandarin', 'zh_', 'zh-'],
}


def available():
    try:
        import pyttsx3  # noqa: F401
        return True
    except ImportError:
        return False


def _pick_voice(engine, lang):
    voices = engine.getProperty('voices') or []
    for code in (lang, 'en'):
        for v in voices:
            if any(kw in (v.name + v.id).lower() for kw in LANG_VOICE_KEYWORDS.get(code, [])):
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
