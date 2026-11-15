"""Pruebas de los endpoints de apoyo de la consola de demo (referencia, instantánea y escenario de q15)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import seed
from src.clock import fixed_clock
from src.infrastructure.mongo import check_mongo_health, get_db, get_mongo_client
from src.loading.validation import leer_directorio, maximos_contadores, validar_y_transformar
from src.web.app import app

TEST_DB = "farmared_test"
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
    for destino in ("src.infrastructure.mongo.get_shared_db", "src.web.demo_api.get_shared_db"):
        monkeypatch.setattr(destino, lambda: base)
    with fixed_clock(date(2026, 10, 13)):
        yield base
    base.client.drop_database(TEST_DB)
    base.client.close()


def test_reference_lista_los_datos_para_los_selectores(db) -> None:
    ref = TestClient(app).get("/api/demo/reference").json()
    assert len(ref["clientes"]) == 8 and len(ref["productos"]) == 13 and len(ref["ventas"]) == 16
    f7 = next(f for f in ref["farmaceuticos"] if f["id"] == "F007")
    assert f7["tipo_sucursal"] == "Droguería"


def test_snapshot_por_pedido_y_por_venta(db) -> None:
    cliente = TestClient(app)
    s = cliente.get("/api/demo/snapshot", params={"id_farmaceutico": "F001", "productos": "PRD001", "id_receta": "RC006"}).json()
    assert s["id_sucursal"] == "S001" and [l["id_lote"] for l in s["lotes"]] == ["L001"] and s["receta"]["_id"] == "RC006"
    assert s["contadores"]["venta"] == 16 and s["total_ventas"] == 16
    v = cliente.get("/api/demo/snapshot", params={"id_venta": "V013"}).json()
    assert v["venta"]["_id"] == "V013" and v["id_sucursal"] == "S001"
    assert cliente.get("/api/demo/snapshot", params={"id_venta": "V999"}).status_code == 404


def test_fixture_q15_normal_y_sin_stock(db) -> None:
    cliente = TestClient(app)
    ok = cliente.post("/api/demo/fixture-q15").json()
    assert ok["venta"]["_id"] == "V900" and ok["venta"]["items"][0]["cantidad"] == 4
    assert cliente.post("/api/demo/fixture-q15", params={"caso": "sin_stock"}).json()["venta"]["items"][0]["cantidad"] == 5000
    assert db["ventas"].count_documents({"_id": "V900"}) == 1


def test_vista_en_vivo_lista_colecciones_y_documentos(db) -> None:
    c = TestClient(app)
    cols = {x["name"]: x["count"] for x in c.get("/api/demo/collections").json()["collections"]}
    assert cols["clientes"] == 8 and "stock_lotes" in cols and "contadores" in cols
    r = c.get("/api/demo/collection/clientes?limit=3&desc=true").json()
    assert r["count"] == 8 and r["shown"] == 3 and r["docs"][0]["_id"] > r["docs"][1]["_id"]
    assert c.get("/api/demo/collection/inexistente").status_code == 404
