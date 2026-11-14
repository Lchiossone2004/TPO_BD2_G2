"""Pruebas de q12 contra MongoDB (CSV originales, reloj fijo)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

import seed
from src.clock import fixed_clock
from src.infrastructure.mongo import check_mongo_health, get_db, get_mongo_client
from src.loading.validation import leer_directorio, maximos_contadores, validar_y_transformar
from src.queries import q12

TEST_DB = "farmared_test_q12"
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


def _ids(db, hoy: date) -> list[str]:
    with fixed_clock(hoy):
        return [c["id_cliente"] for c in q12.ejecutar(db=db)]


def test_clientes_sin_ventas_en_el_ultimo_anio_al_13_10_2026(db) -> None:
    # C004 solo compró el 2025-09-18 (fuera de la ventana) y C008 (inactivo) nunca compró.
    assert _ids(db, date(2026, 10, 13)) == ["C004", "C008"]


def test_incluye_clientes_inactivos_con_su_flag(db) -> None:
    with fixed_clock(date(2026, 10, 13)):
        por_id = {c["id_cliente"]: c for c in q12.ejecutar(db=db)}
    assert por_id["C008"]["activo"] is False
    assert por_id["C004"]["activo"] is True


def test_pendientes_y_anuladas_cuentan_como_venta_registrada(db) -> None:
    # C007 solo tiene V011 (Pendiente): no aparece. Con hoy = 10-13 sus ventas están en la ventana.
    assert "C007" not in _ids(db, date(2026, 10, 13))


def test_limite_de_la_ventana_incluido_y_excluido(db) -> None:
    # V001 (C004) es del 2025-09-18: con hoy = 2026-09-18 la ventana arranca ese día (incluida)...
    assert "C004" not in _ids(db, date(2026, 9, 18))
    # ...y con hoy = 2026-09-19 arranca el 09-19 (excluida): C004 vuelve a aparecer.
    assert "C004" in _ids(db, date(2026, 9, 19))


def test_ventana_del_29_de_febrero() -> None:
    assert q12.ventana(date(2028, 2, 29)) == (date(2027, 2, 28), date(2028, 2, 29))
    assert q12.ventana(date(2026, 10, 13)) == (date(2025, 10, 13), date(2026, 10, 13))


def test_ventas_futuras_no_cuentan(db) -> None:
    # Con hoy = 2026-06-01, todas las ventas de C002 (V009 del 09-28 y V012 del 10-11) son futuras:
    # no cuentan y el cliente figura sin ventas.
    assert "C002" in _ids(db, date(2026, 6, 1))
