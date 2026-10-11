from datetime import datetime

from server import smalltalk


def test_greeting_in_front_of_a_question_is_dropped():
    assert smalltalk.strip_greeting('Halo kak, LSC dimana?') == 'LSC dimana?'
    assert smalltalk.strip_greeting('Selamat pagi, toilet dimana?') == 'toilet dimana?'
    assert smalltalk.strip_greeting('hi where is the library') == 'where is the library'
    assert smalltalk.strip_greeting('Halo Kaela, LSC dimana?') == 'LSC dimana?'
    assert smalltalk.strip_greeting('你好，图书馆在哪里？') == '图书馆在哪里？'


def test_greeting_alone_is_kept():
    for q in ('Halo', 'Selamat pagi', 'Hai kak', '你好', 'Halo Infosphere', 'Hai Kaela'):
        assert smalltalk.strip_greeting(q) == q


def test_time_answer_in_each_language():
    now = datetime(2026, 10, 11, 14, 5, tzinfo=smalltalk.WIB)
    assert smalltalk.time_text('id', now) == 'Sekarang pukul 14.05 WIB, Minggu, 11 Oktober 2026.'
    assert smalltalk.time_text('en', now) == "It's 2:05 PM (WIB), Sunday, 11 October 2026."
    assert smalltalk.time_text('zh', now) == '现在是14:05（雅加达时间），2026年10月11日，星期日。'


def test_weather_answer_and_rain_hint():
    assert smalltalk.weather_text('id', {'temp_c': 29.6, 'code': 2}) == 'Cuaca di sekitar kampus sekarang cerah berawan, sekitar 30°C.'
    assert 'umbrella' in smalltalk.weather_text('en', {'temp_c': 27, 'code': 63})
    assert smalltalk.weather_text('zh', {'temp_c': 27, 'code': 0}) == '现在校园附近晴朗，大约27°C。'


def test_no_live_answer_without_data(monkeypatch):
    from server import weather
    monkeypatch.setattr(weather, 'current', lambda: None)
    assert smalltalk.live_answer('@weather', 'id') is None      # /chat keeps the stored fallback
    assert smalltalk.live_answer('@nothing', 'id') is None
