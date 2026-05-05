from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


MEXICO_CITY_TZ = ZoneInfo("America/Mexico_City")


def mexico_now_naive() -> datetime:
    """
    MySQL DATETIME no almacena zona horaria; guardamos hora local de Mexico.
    """
    return datetime.now(MEXICO_CITY_TZ).replace(tzinfo=None)


def mexico_from_unix_timestamp(value: int | str) -> datetime:
    return datetime.fromtimestamp(int(value), tz=MEXICO_CITY_TZ).replace(tzinfo=None)
