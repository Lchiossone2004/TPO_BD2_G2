"""Paquete de consultas y catálogo Q1–Q15 de FarmaRed S.A."""

from typing import Any, Callable

from src.queries import q02, q03, q05, q13, q14, q15
from src.queries.catalog import QUERIES_CATALOG, get_query_metadata

EJECUTORES: dict[str, Callable[..., Any]] = {
    "q02": q02.ejecutar,
    "q03": q03.ejecutar,
    "q05": q05.ejecutar,
    "q13": q13.ejecutar,
    "q14": q14.ejecutar,
    "q15": q15.ejecutar,
}

__all__ = ["EJECUTORES", "QUERIES_CATALOG", "get_query_metadata"]
