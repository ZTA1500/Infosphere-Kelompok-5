"""Small input-cleaning helpers shared by every endpoint that accepts text.

Pages always render user text with textContent (never innerHTML), so these
are a second line of defence: stored text never contains markup or control
characters in the first place.
"""
import re
from datetime import datetime, timezone

_TAG_RE = re.compile(r'<[^>]{0,1000}>')
_CTRL_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')


class ValidationError(ValueError):
    """Raised with a message that is safe to show to the visitor."""


def clean_text(value, max_len, *, field='Text', required=False, multiline=True, min_len=0):
    """Strip HTML tags and control characters, normalise whitespace, check length."""
    if value is None:
        value = ''
    if not isinstance(value, (str, int, float)):
        raise ValidationError(f'{field} must be text.')
    text = _CTRL_RE.sub('', _TAG_RE.sub('', str(value)))
    if multiline:
        text = '\n'.join(' '.join(line.split()) for line in text.replace('\r\n', '\n').split('\n'))
        text = re.sub(r'\n{3,}', '\n\n', text).strip()
    else:
        text = ' '.join(text.split())
    if required and not text:
        raise ValidationError(f'{field} is required.')
    if text and len(text) < min_len:
        raise ValidationError(f'{field} is too short.')
    if len(text) > max_len:
        raise ValidationError(f'{field} is too long (max {max_len} characters).')
    return text


def parse_utc(value, field='Date'):
    """ISO 8601 -> aware UTC datetime. Naive values are taken as UTC. '' -> None."""
    if value in (None, ''):
        return None
    if not isinstance(value, str) or len(value) > 40:
        raise ValidationError(f'{field} is not a valid date.')
    try:
        dt = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    except ValueError:
        raise ValidationError(f'{field} is not a valid date.') from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def utc_iso(dt):
    """Uniform UTC string ('2026-10-02T08:00:00Z') — sorts and compares as text."""
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ') if dt else None


def now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0)
