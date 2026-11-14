"""Pruebas de q05 contra MongoDB (CSV originales, reloj fijo)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

import seed
from src.clock import fixed_clock
from src.infrastructure.mongo import check_mongo_health, get_db, get_mongo_client
from src.loading.validation import leer_directorio, maximos_contadores, validar_y_transformar
from src.queries import q05

TEST_DB = "farmared_test_q05"
ORIGINALES = Path(__file__).resolve().parent.parent / "data" / "original"


@pytest.fixture()
def db():
    if check_mongo_health()["status"] != "ok":
        pytest.skip("MongoDB (rs0) no disponible")
    crudo = leer_directorio(ORIGINALES, "original")
    docs, reporte = validar_y_transformar(crudo)
    assert reporte.ok
    seed.cargar_en_mongo(docs, maximos_contadores(crudo), db_name=TEST_DB)
    base = get_db(client=get_mongo_client(), db_name=TEST_DB)
    yield base
    base.client.drop_database(TEST_DB)
    base.client.close()


def _cantidades(db, hoy: date) -> dict[str, int]:
    with fixed_clock(hoy):
        return {r["id_farmaceutico"]: r["cantidad_ventas"] for r in q05.ejecutar(db=db)}


def test_conteos_al_13_10_2026_excluyen_anuladas_e_inactivos_e_incluyen_ceros(db) -> None:
    c = _cantidades(db, date(2026, 10, 13))
    # F004 está inactivo (no aparece); F007 es activo y no tiene ventas recientes (aparece con 0).
    assert c == {"F001": 2, "F002": 3, "F003": 1, "F005": 3, "F006": 2, "F007": 0}


def test_las_pendientes_cuentan_y_las_anuladas_no(db) -> None:
    c = _cantidades(db, date(2026, 10, 13))
    assert c["F005"] == 3  # V009 + V014 completadas + V012 pendiente
    assert c["F002"] == 3  # V015 anulada no cuenta


def test_limite_inferior_incluido_y_excluido(db) -> None:
    # V005 (F006) es del 2026-08-15: con hoy = 10-14 la ventana arranca el 08-15 (incluida)...
    assert _cantidades(db, date(2026, 10, 14))["F006"] == 2
    # ...y con hoy = 10-15 arranca el 08-16 (excluida); queda solo la pendiente V011.
    assert _cantidades(db, date(2026, 10, 15))["F006"] == 1


def test_no_cuenta_ventas_futuras(db) -> None:
    # Con hoy = 10-10 las ventas del 10-11 y 10-12 son futuras: F005 pierde V012 y F006 pierde V011.
    c = _cantidades(db, date(2026, 10, 10))
    assert c["F005"] == 2
    assert c["F006"] == 1


def test_orden_por_cantidad_descendente_y_luego_id(db) -> None:
    with fixed_clock(date(2026, 10, 13)):
        ids = [r["id_farmaceutico"] for r in q05.ejecutar(db=db)]
    assert ids == ["F002", "F005", "F001", "F006", "F003", "F007"]
