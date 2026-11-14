"""Pruebas de q02 contra MongoDB (CSV originales, base aislada)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import seed
from src.infrastructure.mongo import check_mongo_health, get_db, get_mongo_client
from src.loading.validation import leer_directorio, maximos_contadores, validar_y_transformar
from src.queries import q02
from src.web.app import app

TEST_DB = "farmared_test_q02"
ORIGINALES = Path(__file__).resolve().parent.parent / "data" / "original"


@pytest.fixture()
def db(monkeypatch: pytest.MonkeyPatch):
    if check_mongo_health()["status"] != "ok":
        pytest.skip("MongoDB (rs0) no disponible")
    crudo = leer_directorio(ORIGINALES, "original")
    docs, reporte = validar_y_transformar(crudo)
    assert reporte.ok
    seed.cargar_en_mongo(docs, maximos_contadores(crudo), db_name=TEST_DB)
    base = get_db(client=get_mongo_client(), db_name=TEST_DB)
    monkeypatch.setattr("src.queries.q02.get_shared_db", lambda: base)
    yield base
    base.client.drop_database(TEST_DB)
    base.client.close()


def test_devuelve_solo_pendientes_con_farmaceutico_y_sucursal(db) -> None:
    res = q02.ejecutar(db=db)
    assert [r["id_venta"] for r in res] == ["V012", "V011"]  # ordenadas por fecha
    assert list(res[0])[0] == "id_venta"  # el ID sale primero en el JSON
    v011 = res[1]
    assert v011["total"] == 4800
    assert v011["farmaceutico"]["id_farmaceutico"] == "F006"
    assert v011["farmaceutico"]["matricula"]
    assert v011["sucursal"]["id_sucursal"]


def test_endpoint_http_ejecuta_la_consulta(db) -> None:
    r = TestClient(app).get("/api/queries/q02")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert {v["id_venta"] for v in r.json()["result"]} == {"V011", "V012"}
