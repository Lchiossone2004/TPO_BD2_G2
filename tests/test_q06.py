"""Pruebas de q06 con CSV originales, reloj fijo y base MongoDB aislada."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
import seed
from src.clock import date_to_bson, fixed_clock
from src.infrastructure.mongo import check_mongo_health, get_db, get_mongo_client
from src.loading.validation import leer_directorio, maximos_contadores, validar_y_transformar
from src.queries import EJECUTORES, get_query_metadata, q06
from src.web.app import app

TEST_DB = "farmared_test_q06"
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
    monkeypatch.setattr("src.queries.q06.get_shared_db", lambda: base)
    try:
        yield base
    finally:
        base.client.drop_database(TEST_DB)
        base.client.close()


def test_originales_al_13_10_2026_con_datos_del_cliente(db):
    with fixed_clock(date(2026, 10, 13)):
        resultado = q06.ejecutar(db=db)
    assert [r["id_receta"] for r in resultado] == ["RC002", "RC003"]
    assert resultado[0]["cliente"]["id_cliente"] == "C003"
    assert resultado[0]["cliente"]["nombre"] == "Carla"
    assert resultado[0]["proxima_dispensa"] == date_to_bson("2026-09-15")
    assert resultado[1]["cliente"]["dni"] == "14876543"


def test_dispensa_de_hoy_y_futura_se_excluyen_y_el_reloj_es_dinamico(db):
    for referencia, esperadas in [
        (date(2026, 9, 15), []),
        (date(2026, 9, 16), ["RC002"]),
        (date(2026, 10, 20), ["RC002", "RC003"]),
        (date(2026, 10, 21), ["RC002", "RC003", "RC004"]),
    ]:
        with fixed_clock(referencia):
            assert [r["id_receta"] for r in q06.ejecutar(db=db)] == esperadas


def test_excluye_proxima_nula_estado_no_vigente_y_otro_tipo(db):
    db["recetas"].update_one({"_id": "RC002"}, {"$set": {"proxima_dispensa": None}})
    db["recetas"].update_one({"_id": "RC003"}, {"$set": {"estado": "Vencida"}})
    db["recetas"].update_one({"_id": "RC004"}, {"$set": {
        "estado": "Completada", "dispensas_realizadas": 3,
        "proxima_dispensa": date_to_bson("2026-10-01"),
    }})
    # Esta receta Simple es Vigente y se le asigna una fecha pasada: debe seguir excluida por tipo.
    db["recetas"].update_one({"_id": "RC006"}, {"$set": {"proxima_dispensa": date_to_bson("2026-10-01")}})
    with fixed_clock(date(2026, 10, 13)):
        assert q06.ejecutar(db=db) == []


def test_incluye_cliente_inactivo_y_desempata_por_id(db):
    db["clientes"].update_one({"_id": "C003"}, {"$set": {"activo": False}})
    db["recetas"].update_one({"_id": "RC003"}, {"$set": {"proxima_dispensa": date_to_bson("2026-09-15")}})
    with fixed_clock(date(2026, 10, 13)):
        resultado = q06.ejecutar(db=db)
    assert [r["id_receta"] for r in resultado] == ["RC002", "RC003"]
    assert resultado[0]["cliente"]["activo"] is False


def test_endpoint_y_cli_serializan_fechas(db, capsys):
    with fixed_clock(date(2026, 10, 13)):
        respuesta = TestClient(app).get("/api/queries/q06")
        assert respuesta.status_code == 200
        assert main.main(["--query", "q06"]) == 0
    resultado = respuesta.json()["result"]
    assert resultado[0]["proxima_dispensa"] == "2026-09-15"
    assert json.loads(capsys.readouterr().out) == resultado


def test_catalogo_y_registro_habilitan_q06():
    assert get_query_metadata("q06")["implemented"] is True
    assert EJECUTORES["q06"] is q06.ejecutar


def test_api_y_cli_comparten_ejecutor_y_serializan_fechas(monkeypatch, capsys):
    resultado = [{"id_receta": "RC002", "proxima_dispensa": date_to_bson("2026-09-15")}]
    monkeypatch.setitem(EJECUTORES, "q06", lambda: resultado)
    respuesta = TestClient(app).get("/api/queries/q06")
    assert respuesta.status_code == 200
    assert main.main(["--query", "q06"]) == 0
    assert json.loads(capsys.readouterr().out) == respuesta.json()["result"]
    assert respuesta.json()["result"][0]["proxima_dispensa"] == "2026-09-15"
