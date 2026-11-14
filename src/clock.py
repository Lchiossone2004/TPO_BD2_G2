"""Reloj de negocio y helpers de conversión de fechas para FarmaRed S.A.

Centraliza la zona horaria oficial de negocio (America/Argentina/Buenos_Aires),
el mecanismo de inyección temporal para tests (`fixed_clock` / `set_fixed_today`)
y las conversiones BSON Date <-> fecha calendario sin corrimientos de día.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timezone
from threading import RLock
from zoneinfo import ZoneInfo

AR_TZ = ZoneInfo("America/Argentina/Buenos_Aires")

_clock_lock = RLock()
_fixed_today: date | None = None


def _normalize_date(d: date | datetime) -> date:
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    raise TypeError(f"Se esperaba date o datetime, se recibió {type(d)!r}")


def hoy() -> date:
    """Retorna la fecha calendario de negocio en Buenos Aires o el override de test."""
    with _clock_lock:
        if _fixed_today is not None:
            return _fixed_today
    return datetime.now(AR_TZ).date()


def set_fixed_today(d: date | None) -> None:
    """Fija manualmente la fecha devuelta por `hoy()`, o `None` para restaurar producción."""
    normalized = _normalize_date(d) if d is not None else None
    with _clock_lock:
        global _fixed_today
        _fixed_today = normalized


@contextmanager
def fixed_clock(d: date) -> Iterator[date]:
    """Context manager que fija temporalmente `hoy()` a `d` y restaura el valor previo."""
    if d is None:
        raise ValueError("fixed_clock requiere una fecha válida, no None")
    target = _normalize_date(d)
    with _clock_lock:
        previous = _fixed_today
        set_fixed_today(target)
    try:
        yield target
    finally:
        set_fixed_today(previous)


def date_to_bson(d: date | datetime | str) -> datetime:
    """Normaliza una fecha calendario a medianoche UTC para persistir como BSON Date."""
    if isinstance(d, str):
        cal_date = date.fromisoformat(d.strip())
    elif isinstance(d, datetime):
        cal_date = d.date()
    elif isinstance(d, date):
        cal_date = d
    else:
        raise TypeError(f"Tipo de fecha no soportado para BSON: {type(d)!r}")
    return datetime(cal_date.year, cal_date.month, cal_date.day, 0, 0, 0, tzinfo=timezone.utc)


def bson_to_date(dt: datetime | date | str | None) -> date | None:
    """Decodifica un BSON Date, date o string ISO a date sin desplazar el día a hora local."""
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is not None:
            return dt.astimezone(timezone.utc).date()
        return dt.date()
    if isinstance(dt, date):
        return dt
    if isinstance(dt, str):
        return date.fromisoformat(dt[:10])
    raise TypeError(f"Tipo de fecha no soportado: {type(dt)!r}")


def format_iso_date(dt: datetime | date | str | None) -> str | None:
    """Formatea una fecha (o BSON Date) como string ISO `YYYY-MM-DD`, o `None`."""
    parsed = bson_to_date(dt)
    return parsed.isoformat() if parsed is not None else None


def ahora_utc() -> datetime:
    """Retorna el instante técnico actual en UTC (para logs y timestamps)."""
    return datetime.now(timezone.utc)


__all__ = [
    "AR_TZ",
    "ahora_utc",
    "bson_to_date",
    "date_to_bson",
    "fixed_clock",
    "format_iso_date",
    "hoy",
    "set_fixed_today",
]
