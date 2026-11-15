"""Pruebas de q09 con CSV originales y casos borde, sobre MongoDB aislado."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
import seed
from src.clock import date_to_bson
from src.infrastructure.mongo import check_mongo_health, get_db, get_mongo_client
from src.loading.validation import leer_directorio, maximos_contadores, validar_y_transformar
from src.queries import EJECUTORES, get_query_metadata, q09
from src.services.serialization import a_json
from src.web.app import app

TEST_DB = "farmared_test_q09"
ORIGINALES = Path(__file__).resolve().parent.parent / "data" / "original"


@pytest.fixture()
def db(monkeypatch: pytest.MonkeyPatch):
    if check_mongo_health()["status"] != "ok":
        pytest.skip("MongoDB (rs0) no disponible")
    crudo = leer_directorio(ORIGINALES, "original")
    docs, reporte = validar_y_transformar(crudo)
    assert reporte.ok, reporte.errores
    seed.cargar_en_mongo(docs, maximos_contadores(crudo), db_name=TEST_DB)
    base = get_db(client=get_mongo_client(), db_name=TEST_DB)
    monkeypatch.setattr("src.queries.q09.get_shared_db", lambda: base)
    try:
        yield base
    finally:
        base.client.drop_database(TEST_DB)
        base.client.close()


def test_originales_devuelven_ventas_libres_de_bajo_importe_con_items(db):
    resultado = q09.ejecutar(db=db)
    assert [(v["id_venta"], v["total"]) for v in resultado] == [("V013", 4400), ("V014", 4600)]
    assert resultado[0]["items"][0]["id_producto"] == "PRD011"
    assert resultado[0]["items"][0]["cantidad"] == 2
    assert list(resultado[0])[0] == "id_venta"


def test_limite_estricto_estados_tipo_y_desempate_por_id(db):
    plantilla = db["ventas"].find_one({"_id": "V013"})
    db["ventas"].delete_many({})
    casos = [
        ("V901", 4999, "Completada", "Venta libre"),
        ("V902", 4999, "Pendiente", "Venta libre"),
        ("V903", 5000, "Completada", "Venta libre"),
        ("V904", 5001, "Completada", "Venta libre"),
        ("V905", 4999, "Anulada", "Venta libre"),
        ("V906", 4999, "Completada", "Con receta"),
    ]
    for id_venta, total, estado, tipo in reversed(casos):
        venta = copy.deepcopy(plantilla)
        venta.update(_id=id_venta, total=total, estado=estado, tipo=tipo)
        venta["id_receta"] = "RC001" if tipo == "Con receta" else None
        venta["items"][0].update(id_detalle=f"D{id_venta[1:]}", cantidad=1, precio_unit=total)
        db["ventas"].insert_one(venta)
    assert [(v["id_venta"], v["estado"]) for v in q09.ejecutar(db=db)] == [
        ("V901", "Completada"), ("V902", "Pendiente"),
    ]


def test_no_filtra_cliente_o_producto_inactivo_ni_usa_precios_actuales(db):
    db["clientes"].update_one({"_id": "C001"}, {"$set": {"activo": False}})
    db["productos"].update_one({"_id": "PRD011"}, {"$set": {"activo": False, "precio_unit": 99999}})
    resultado = q09.ejecutar(db=db)
    assert [(v["id_venta"], v["total"]) for v in resultado] == [("V013", 4400), ("V014", 4600)]
    assert resultado[0]["items"][0]["precio_unit"] == 2200


def test_sin_coincidencias_devuelve_lista_vacia(db):
    db["ventas"].update_many({}, {"$set": {"estado": "Anulada"}})
    assert q09.ejecutar(db=db) == []


def test_endpoint_y_cli_ejecutan_y_serializan_fechas(db, capsys):
    respuesta = TestClient(app).get("/api/queries/q09")
    assert respuesta.status_code == 200
    assert main.main(["--query", "q09"]) == 0
    assert json.loads(capsys.readouterr().out) == respuesta.json()["result"] == a_json(q09.ejecutar(db=db))
    assert respuesta.json()["result"][0]["fecha"] == "2026-10-02"


def test_catalogo_y_registro_habilitan_q09():
    assert get_query_metadata("q09")["implemented"] is True
    assert EJECUTORES["q09"] is q09.ejecutar


def test_api_y_cli_comparten_ejecutor_y_serializan_fechas(monkeypatch, capsys):
    resultado = [{"id_venta": "V013", "total": 4400, "fecha": date_to_bson("2026-10-02")}]
    monkeypatch.setitem(EJECUTORES, "q09", lambda: resultado)
    respuesta = TestClient(app).get("/api/queries/q09")
    assert respuesta.status_code == 200
    assert main.main(["--query", "q09"]) == 0
    assert json.loads(capsys.readouterr().out) == respuesta.json()["result"] == a_json(resultado)
