"""Conversión de documentos de MongoDB a estructuras JSON (fechas como AAAA-MM-DD)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from src.clock import format_iso_date


def a_json(valor: Any) -> Any:
    """Convierte recursivamente BSON Date y fechas a ``AAAA-MM-DD`` y deja el resto igual."""
    if isinstance(valor, (datetime, date)):
        return format_iso_date(valor)
    if isinstance(valor, dict):
        return {k: a_json(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [a_json(v) for v in valor]
    return valor
