"""Panel wall-clock preferences, independent of the server's system clock."""
import datetime as dt
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones


def zone(name='UTC'):
    if not isinstance(name, str) or not name or len(name) > 128:
        raise ValueError('Choose a valid IANA time zone, for example Asia/Tehran')
    if name == 'UTC':
        return dt.timezone.utc
    try:
        return ZoneInfo(name)
    except (ValueError, ZoneInfoNotFoundError):
        raise ValueError('Time zone is unavailable. Choose a listed IANA time zone; the server needs tzdata.') from None


@lru_cache(maxsize=1)
def names():
    # Reading zone files is relatively expensive: build this once, not per poll.
    return tuple(sorted(available_timezones() | {'UTC'}))


def name(state):
    return state.get('settings', {}).get('time_zone', 'UTC')
