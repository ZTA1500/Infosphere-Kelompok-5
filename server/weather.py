"""Current outdoor temperature for the kiosk header.

Fetched server-side from Open-Meteo (free, no API key, no account, so nothing
can ever be billed) and cached, so the kiosk makes about one request every
15 minutes no matter how many screens are open. When the fetch fails the
endpoint returns no temperature and the header simply hides the reading.

WEATHER_LAT / WEATHER_LON pick the location (default: BINUS @Anggrek, Jakarta).
WEATHER_ENABLED=0 turns it off entirely.
"""
import json
import os
import threading
import time
import urllib.request

CACHE_SECONDS = 15 * 60
FAIL_RETRY_SECONDS = 5 * 60
_URL = ('https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}'
        '&current=temperature_2m,weather_code&timezone=auto')

_lock = threading.Lock()
_cache = {'at': 0.0, 'data': None}


def _enabled():
    return os.environ.get('WEATHER_ENABLED', '1').strip().lower() not in ('0', 'false', 'no', 'off')


def _fetch():
    lat = float(os.environ.get('WEATHER_LAT', '-6.2018'))
    lon = float(os.environ.get('WEATHER_LON', '106.7823'))
    req = urllib.request.Request(_URL.format(lat=lat, lon=lon),      # noqa: S310 (fixed https host)
                                 headers={'User-Agent': 'Infosphere-kiosk'})
    with urllib.request.urlopen(req, timeout=4) as resp:      # noqa: S310 (fixed https host)
        body = json.loads(resp.read(65536).decode('utf-8'))
    cur = body.get('current') or {}
    temp = cur.get('temperature_2m')
    if not isinstance(temp, (int, float)):
        return None
    return {'temp_c': round(float(temp)), 'code': cur.get('weather_code')}


def current():
    """{'temp_c': 31, 'code': 2} or None. Never raises."""
    if not _enabled():
        return None
    now = time.time()
    with _lock:
        age = now - _cache['at']
        if age < (CACHE_SECONDS if _cache['data'] else FAIL_RETRY_SECONDS):
            return _cache['data']
        _cache['at'] = now                  # one fetch at a time; others get the old value
    try:
        data = _fetch()
    except Exception as e:                  # offline, DNS, timeout, bad JSON
        print(f'[Weather] unavailable: {e}')
        data = None
    with _lock:
        if data:
            _cache['data'] = data           # on failure keep the last good reading
        _cache['at'] = time.time()
        return _cache['data']
