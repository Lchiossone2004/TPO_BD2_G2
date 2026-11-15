"""Pruebas de q04 contra MongoDB (CSV originales, base aislada)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
import seed
from src.infrastructure.mongo import check_mongo_health, get_db, get_mongo_client
from src.loading.validation import leer_directorio, maximos_contadores, validar_y_transformar
from src.queries import EJECUTORES, get_query_metadata, q04
from src.web.app import app

TEST_DB = "farmared_test_q04"
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
    monkeypatch.setattr("src.queries.q04.get_shared_db", lambda: base)
    try:
        yield base
    finally:
        base.client.drop_database(TEST_DB)
        base.client.close()


def test_originales_cuentan_todos_los_estados_y_excluyen_clientes_con_una_receta(db):
    resultado = q04.ejecutar(db=db)
    assert [(c["id_cliente"], c["cantidad_recetas"]) for c in resultado] == [
        ("C001", 2), ("C002", 2), ("C006", 2),
    ]
    # C001 tiene dos Completadas; C002 una Completada y una Vencida; C006 dos Vigentes.
    assert resultado[0]["dni"] == "31245678"
    assert resultado[0]["nombre"] == "Lucía"
    assert list(resultado[0])[0] == "id_cliente"


def test_incluye_clientes_inactivos_y_ordena_por_cantidad(db):
    db["clientes"].update_one({"_id": "C001"}, {"$set": {"activo": False}})
    adicional = db["recetas"].find_one({"_id": "RC003"})
    adicional["_id"] = "RC010"
    db["recetas"].insert_one(adicional)
    resultado = q04.ejecutar(db=db)
    assert [(c["id_cliente"], c["cantidad_recetas"]) for c in resultado] == [
        ("C006", 3), ("C001", 2), ("C002", 2),
    ]
    assert resultado[1]["activo"] is False


def test_sin_recetas_devuelve_lista_vacia(db):
    db["recetas"].delete_many({})
    assert q04.ejecutar(db=db) == []


def test_endpoint_y_cli_ejecutan_la_consulta(db, capsys):
    respuesta = TestClient(app).get("/api/queries/q04")
    assert respuesta.status_code == 200
    assert respuesta.json()["status"] == "ok"
    esperado = q04.ejecutar(db=db)
    assert respuesta.json()["result"] == esperado
    assert main.main(["--query", "q04"]) == 0
    assert json.loads(capsys.readouterr().out) == esperado


def test_registro_y_catalogo_habilitan_q04():
    assert EJECUTORES["q04"] is q04.ejecutar
    assert get_query_metadata("q04")["implemented"] is True


def test_api_y_cli_comparten_el_ejecutor(monkeypatch, capsys):
    esperado = [{"id_cliente": "C001", "cantidad_recetas": 2}]
    monkeypatch.setitem(EJECUTORES, "q04", lambda: esperado)
    assert main.main(["--query", "q04"]) == 0
    assert json.loads(capsys.readouterr().out) == esperado
    respuesta = TestClient(app).get("/api/queries/q04")
    assert respuesta.status_code == 200
    assert respuesta.json()["result"] == esperado
