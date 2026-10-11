"""Live answers for small-talk rows whose Keywords start with "@".

data/qa/smalltalk.csv (built by scripts/build_smalltalk.py) holds the
questions; a match on "@weather" or "@time" is answered here with fresh data
instead of the stored text. The stored text stays the fallback: live_answer()
returns None when it has nothing better.
"""
import re
from datetime import datetime, timedelta, timezone

# "Halo, dimana LSC?" → "dimana LSC?": a greeting in front of a real question
# would otherwise match the greeting reply instead of the room.
_GREETING = re.compile(
    r'^\s*(?:(?:halo|hallo|hai|hi|hello|hey|permisi|maaf|selamat\s+(?:pagi|siang|sore|malam)|'
    r'good\s+(?:morning|afternoon|evening)|excuse\s+me|assalamu\'?alaikum|pagi|siang|sore|malam|'
    r'kak|min|mas|mbak|bang|pak|bu|infosphere|kaela)\b[\s,.!~-]*)+'
    r'|^\s*(?:你好|您好|嗨|请问|打扰一下)[\s，,。!！]*', re.IGNORECASE)

WIB = timezone(timedelta(hours=7), 'WIB')      # campus time (Jakarta); fixed offset, no tzdata needed

# WMO weather codes (Open-Meteo) -> (Indonesian, English, Mandarin)
_SKY = [
    ((0,), ('cerah', 'clear', '晴朗')),
    ((1, 2), ('cerah berawan', 'partly cloudy', '晴间多云')),
    ((3,), ('berawan', 'cloudy', '阴天')),
    ((45, 48), ('berkabut', 'foggy', '有雾')),
    ((51, 53, 55, 56, 57), ('gerimis', 'drizzling', '下毛毛雨')),
    ((61, 63, 65, 66, 67, 80, 81, 82), ('hujan', 'raining', '下雨')),
    ((71, 73, 75, 77, 85, 86), ('bersalju', 'snowing', '下雪')),
    ((95, 96, 99), ('hujan badai petir', 'stormy, with thunder', '雷阵雨')),
]
_WET = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}
_IDX = {'id': 0, 'en': 1, 'zh': 2}

_DAYS = {'id': ['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu', 'Minggu'],
         'en': ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'],
         'zh': ['星期一', '星期二', '星期三', '星期四', '星期五', '星期六', '星期日']}
_MONTHS = {'id': ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli',
                  'Agustus', 'September', 'Oktober', 'November', 'Desember'],
           'en': ['January', 'February', 'March', 'April', 'May', 'June', 'July',
                  'August', 'September', 'October', 'November', 'December']}


def _sky(code, lang):
    for codes, words in _SKY:
        if code in codes:
            return words[_IDX[lang]]
    return None


def weather_text(lang='id', reading=None):
    """"Cuaca di sekitar kampus sekarang cerah berawan, sekitar 31°C." or None."""
    if reading is None:
        from server import weather
        reading = weather.current()
    if not reading or not isinstance(reading.get('temp_c'), (int, float)):
        return None
    t, code = round(reading['temp_c']), reading.get('code')
    sky, wet = _sky(code, lang), code in _WET
    if lang == 'en':
        text = f"It's {sky} around campus right now, about {t}°C." if sky else f"It's about {t}°C around campus right now."
        return text + (' Bring an umbrella if you are heading outside.' if wet else '')
    if lang == 'zh':
        text = f"现在校园附近{sky}，大约{t}°C。" if sky else f"现在校园附近大约{t}°C。"
        return text + ('外出请记得带伞。' if wet else '')
    text = f"Cuaca di sekitar kampus sekarang {sky}, sekitar {t}°C." if sky else f"Suhu di sekitar kampus sekarang sekitar {t}°C."
    return text + (' Jangan lupa bawa payung kalau mau keluar.' if wet else '')


def time_text(lang='id', now=None):
    """"Sekarang pukul 14.05 WIB, Sabtu, 11 Oktober 2026." in the visitor's language."""
    now = (now or datetime.now(WIB)).astimezone(WIB)
    day = _DAYS[lang][now.weekday()]
    if lang == 'en':
        hour = now.hour % 12 or 12
        return (f"It's {hour}:{now.minute:02d} {'AM' if now.hour < 12 else 'PM'} (WIB), "
                f"{day}, {now.day} {_MONTHS['en'][now.month - 1]} {now.year}.")
    if lang == 'zh':
        return f"现在是{now.hour}:{now.minute:02d}（雅加达时间），{now.year}年{now.month}月{now.day}日，{day}。"
    return f"Sekarang pukul {now.hour:02d}.{now.minute:02d} WIB, {day}, {now.day} {_MONTHS['id'][now.month - 1]} {now.year}."


def strip_greeting(question):
    """The question without a leading greeting ("Halo kak, toilet dimana?" →
    "toilet dimana?"), or the question unchanged when it is only a greeting."""
    rest = _GREETING.sub('', question, count=1).strip()
    return rest if len(re.sub(r'[\W_]+', '', rest)) >= 2 else question


def live_answer(keyword, lang='id'):
    """Fresh answer for a live small-talk keyword ("@weather", "@time"), or None."""
    lang = lang if lang in _IDX else 'id'
    key = str(keyword or '').strip().lower()
    try:
        if key == '@weather':
            return weather_text(lang)
        if key == '@time':
            return time_text(lang)
    except Exception as e:                      # live data must never break /chat
        print(f'[Smalltalk] {key} failed: {e}')
    return None
