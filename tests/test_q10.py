"""Pruebas de q10 contra MongoDB (CSV originales, base aislada)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import main
import seed
from src.infrastructure.mongo import check_mongo_health, get_db, get_mongo_client
from src.loading.validation import leer_directorio, maximos_contadores, validar_y_transformar
from src.queries import EJECUTORES, get_query_metadata, q10
from src.services.exceptions import NO_ENCONTRADO, VALIDACION_ERROR, DomainError
from src.web.app import app

TEST_DB = "farmared_test_q10"
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
    monkeypatch.setattr("src.queries.q10.get_shared_db", lambda: base)
    try:
        yield base
    finally:
        base.client.drop_database(TEST_DB)
        base.client.close()


def test_clientes_por_sucursal_en_originales(db) -> None:
    # S001: C001 (F001 y F002, incluye V015 Anulada) y C006 (4 ventas con F002), sin duplicados.
    r_s001 = q10.ejecutar("S001", db=db)
    assert [c["id_cliente"] for c in r_s001] == ["C001", "C006"]
    assert list(r_s001[0])[0] == "id_cliente"
    assert r_s001[0] == {
        "id_cliente": "C001",
        "nombre": "Lucía",
        "apellido": "Fernández",
        "dni": "31245678",
        "email": "lucia.f@gmail.com",
        "telefono": "1145112233",
        "ciudad": "Buenos Aires",
        "provincia": "Buenos Aires",
        "obra_social": "OSDE",
        "nro_afiliado": "OS-310045",
        "activo": True,
    }

    # S002: C001 (F003 activo) y C004 (F004 inactivo).
    assert db["farmaceuticos"].find_one({"_id": "F004"})["activo"] is False
    r_s002 = q10.ejecutar("S002", db=db)
    assert [c["id_cliente"] for c in r_s002] == ["C001", "C004"]
    assert list(r_s002[0])[0] == "id_cliente"

    # S003: C002 (V009 Completada y V012 Pendiente) y C005 (V002 y V014), sin duplicados.
    r_s003 = q10.ejecutar("S003", db=db)
    assert [c["id_cliente"] for c in r_s003] == ["C002", "C005"]
    assert list(r_s003[0])[0] == "id_cliente"
    assert r_s003[1]["nro_afiliado"] is None

    # S004: C003 (V004 y V005) y C007 (única venta V011 Pendiente).
    r_s004 = q10.ejecutar("S004", db=db)
    assert [c["id_cliente"] for c in r_s004] == ["C003", "C007"]
    assert list(r_s004[0])[0] == "id_cliente"

    # S005: sucursal existente sin ventas registradas.
    assert q10.ejecutar("S005", db=db) == []


def test_incluye_clientes_inactivos_y_ventas_anuladas_o_pendientes(db) -> None:
    db["clientes"].update_one({"_id": "C004"}, {"$set": {"activo": False}})
    resultado_s002 = q10.ejecutar("S002", db=db)
    assert [c["id_cliente"] for c in resultado_s002] == ["C001", "C004"]
    por_id_s002 = {c["id_cliente"]: c for c in resultado_s002}
    assert por_id_s002["C004"]["activo"] is False

    # En S005 (sin ventas previas), C008 (inactivo) con solo ventas Anulada y C002 con solo
    # ventas Pendiente deben aparecer una única vez cada uno.
    plantilla = db["ventas"].find_one({"_id": "V015"})
    assert plantilla is not None
    for idx, (id_cliente, estado) in enumerate(
        [("C008", "Anulada"), ("C008", "Anulada"), ("C002", "Pendiente"), ("C002", "Pendiente")],
        start=901,
    ):
        venta = copy.deepcopy(plantilla)
        venta["_id"] = f"V{idx}"
        venta["id_cliente"] = id_cliente
        venta["id_farmaceutico"] = "F007"
        venta["estado"] = estado
        db["ventas"].insert_one(venta)

    resultado_s005 = q10.ejecutar("S005", db=db)
    assert [c["id_cliente"] for c in resultado_s005] == ["C002", "C008"]
    assert resultado_s005[1]["activo"] is False


def test_validacion_parametro_y_sucursal_inexistente(db) -> None:
    for invalido in (None, "", "   "):
        with pytest.raises(DomainError) as exc:
            q10.ejecutar(invalido, db=db)
        assert exc.value.code == VALIDACION_ERROR
        assert exc.value.status_code == 400

    with pytest.raises(DomainError) as exc:
        q10.ejecutar("S999", db=db)
    assert exc.value.code == NO_ENCONTRADO
    assert exc.value.status_code == 404


def test_endpoint_cli_catalogo_y_registro(
    db,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cliente = TestClient(app)
    esperado = q10.ejecutar("S002", db=db)

    respuesta = cliente.get("/api/queries/q10", params={"id_sucursal": "S002"})
    assert respuesta.status_code == 200
    assert respuesta.json()["status"] == "ok"
    assert respuesta.json()["query"] == "q10"
    assert respuesta.json()["result"] == esperado

    sin_parametro = cliente.get("/api/queries/q10")
    assert sin_parametro.status_code == 400
    assert sin_parametro.json()["error"]["code"] == VALIDACION_ERROR

    inexistente = cliente.get("/api/queries/q10", params={"id_sucursal": "S999"})
    assert inexistente.status_code == 404
    assert inexistente.json()["error"]["code"] == NO_ENCONTRADO

    assert main.main(["--query", "q10", "--param", "id_sucursal=S002"]) == 0
    assert json.loads(capsys.readouterr().out) == esperado

    assert EJECUTORES["q10"] is q10.ejecutar
    assert get_query_metadata("q10")["implemented"] is True

    simulado = [{"id_cliente": "C004", "nombre": "Federico"}]
    llamadas: list[str | None] = []

    def ejecutor_compartido(id_sucursal: str | None = None) -> list[dict[str, Any]]:
        llamadas.append(id_sucursal)
        return simulado

    monkeypatch.setitem(EJECUTORES, "q10", ejecutor_compartido)
    resp_compartida = cliente.get("/api/queries/q10", params={"id_sucursal": "S002"})
    assert resp_compartida.status_code == 200
    assert resp_compartida.json()["result"] == simulado
    assert main.main(["--query", "q10", "--param", "id_sucursal=S002"]) == 0
    assert json.loads(capsys.readouterr().out) == simulado
    assert llamadas == ["S002", "S002"]
