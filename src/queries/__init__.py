"""Paquete de consultas y catálogo Q1–Q15 de FarmaRed S.A."""

from typing import Any, Callable

from src.queries import q13
from src.queries.catalog import QUERIES_CATALOG, get_query_metadata

EJECUTORES: dict[str, Callable[..., Any]] = {
    "q13": q13.ejecutar,
}

__all__ = ["EJECUTORES", "QUERIES_CATALOG", "get_query_metadata"]
