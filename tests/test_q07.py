"""Pruebas de q07 contra MongoDB (CSV originales y base aislada)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
import seed
from src.infrastructure.mongo import check_mongo_health, get_db, get_mongo_client
from src.loading.validation import leer_directorio, maximos_contadores, validar_y_transformar
from src.queries import EJECUTORES, get_query_metadata, q07
from src.web.app import app

TEST_DB = "farmared_test_q07"
ORIGINALES = Path(__file__).resolve().parent.parent / "data" / "original"
TOP_ORIGINAL = [("PRD005", 6), ("PRD011", 5), ("PRD001", 4), ("PRD004", 3), ("PRD009", 2)]


@pytest.fixture()
def db(monkeypatch: pytest.MonkeyPatch):
    if check_mongo_health()["status"] != "ok":
        pytest.skip("MongoDB (rs0) no disponible")
    crudo = leer_directorio(ORIGINALES, "original")
    docs, reporte = validar_y_transformar(crudo)
    assert reporte.ok, reporte.errores
    seed.cargar_en_mongo(docs, maximos_contadores(crudo), db_name=TEST_DB)
    base = get_db(client=get_mongo_client(), db_name=TEST_DB)
    monkeypatch.setattr("src.queries.q07.get_shared_db", lambda: base)
    try:
        yield base
    finally:
        base.client.drop_database(TEST_DB)
        base.client.close()


def _ranking(db):
    return [(r["id_producto"], r["unidades_vendidas"]) for r in q07.ejecutar(db=db)]


def test_top_original_por_unidades_con_nombre_del_producto(db):
    assert _ranking(db) == TOP_ORIGINAL
    resultado = q07.ejecutar(db=db)
    assert resultado[0]["nombre"] == "Metformina 850mg x60"
    assert list(resultado[0])[0] == "id_producto"


def test_excluye_pendientes_y_anuladas_aunque_tengan_muchas_unidades(db):
    db["ventas"].update_one({"_id": "V012"}, {"$set": {"items.0.cantidad": 1000, "total": 3502200}})
    db["ventas"].update_one({"_id": "V015"}, {"$set": {"items.0.cantidad": 1000, "total": 3500000}})
    assert _ranking(db) == TOP_ORIGINAL


def test_suma_productos_repetidos_e_incluye_productos_inactivos(db):
    item = {"id_detalle": "D999", "id_producto": "PRD001", "nombre_producto": "Paracetamol 500mg x30",
            "cantidad": 3, "precio_unit": 2800}
    db["ventas"].update_one({"_id": "V016"}, {"$push": {"items": item}, "$inc": {"total": 8400}})
    db["productos"].update_one({"_id": "PRD001"}, {"$set": {"activo": False}})
    assert _ranking(db)[0] == ("PRD001", 7)


def test_limite_cinco_desempate_por_id_y_menos_de_cinco(db):
    plantilla = db["ventas"].find_one({"_id": "V013"})
    db["ventas"].delete_many({})
    # Insertados en orden inverso para comprobar que el desempate no depende de la inserción.
    for numero in range(6, 0, -1):
        venta = copy.deepcopy(plantilla)
        producto = db["productos"].find_one({"_id": f"PRD{numero:03d}"})
        venta["_id"] = f"V{900 + numero}"
        venta["items"] = [{"id_detalle": f"D{900 + numero}", "id_producto": producto["_id"],
                           "nombre_producto": producto["nombre"], "cantidad": 1, "precio_unit": producto["precio_unit"]}]
        venta["total"] = producto["precio_unit"]
        db["ventas"].insert_one(venta)
    assert _ranking(db) == [(f"PRD{n:03d}", 1) for n in range(1, 6)]
    db["ventas"].delete_many({"_id": {"$nin": ["V901", "V902"]}})
    assert _ranking(db) == [("PRD001", 1), ("PRD002", 1)]


def test_sin_ventas_completadas_devuelve_lista_vacia(db):
    db["ventas"].update_many({}, {"$set": {"estado": "Pendiente"}})
    assert q07.ejecutar(db=db) == []


def test_endpoint_y_cli_ejecutan_la_consulta(db, capsys):
    respuesta = TestClient(app).get("/api/queries/q07")
    assert respuesta.status_code == 200
    assert main.main(["--query", "q07"]) == 0
    assert json.loads(capsys.readouterr().out) == respuesta.json()["resultado"] == q07.ejecutar(db=db)


def test_catalogo_y_registro_habilitan_q07():
    assert get_query_metadata("q07")["implemented"] is True
    assert EJECUTORES["q07"] is q07.ejecutar


def test_api_y_cli_comparten_ejecutor(monkeypatch, capsys):
    esperado = [{"id_producto": "PRD005", "nombre": "Metformina", "unidades_vendidas": 6}]
    monkeypatch.setitem(EJECUTORES, "q07", lambda: esperado)
    respuesta = TestClient(app).get("/api/queries/q07")
    assert respuesta.status_code == 200
    assert main.main(["--query", "q07"]) == 0
    assert json.loads(capsys.readouterr().out) == respuesta.json()["resultado"] == esperado
