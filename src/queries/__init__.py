"""Paquete de consultas y catálogo Q1–Q15 de FarmaRed S.A."""

from typing import Any, Callable

from src.queries import q01, q02, q03, q04, q05, q06, q07, q08, q09, q10, q11, q12, q13, q14, q15
from src.queries.catalog import QUERIES_CATALOG, get_query_metadata

EJECUTORES: dict[str, Callable[..., Any]] = {
    "q01": q01.ejecutar,
    "q02": q02.ejecutar,
    "q03": q03.ejecutar,
    "q04": q04.ejecutar,
    "q05": q05.ejecutar,
    "q06": q06.ejecutar,
    "q07": q07.ejecutar,
    "q08": q08.ejecutar,
    "q09": q09.ejecutar,
    "q10": q10.ejecutar,
    "q11": q11.ejecutar,
    "q12": q12.ejecutar,
    "q13": q13.ejecutar,
    "q14": q14.ejecutar,
    "q15": q15.ejecutar,
}

__all__ = ["EJECUTORES", "QUERIES_CATALOG", "get_query_metadata"]
