"""Pruebas de q03 contra MongoDB (CSV originales, base aislada)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import seed
from src.infrastructure.mongo import check_mongo_health, get_db, get_mongo_client
from src.loading.validation import leer_directorio, maximos_contadores, validar_y_transformar
from src.queries import q03
from src.services.exceptions import NO_ENCONTRADO, VALIDACION_ERROR, DomainError
from src.web.app import app

TEST_DB = "farmared_test_q03"
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
    monkeypatch.setattr("src.queries.q03.get_shared_db", lambda: base)
    yield base
    base.client.drop_database(TEST_DB)
    base.client.close()


def test_historial_c001_mezcla_ventas_y_recetas_en_orden_cronologico(db) -> None:
    h = q03.ejecutar("C001", db=db)["historial"]
    # Misma fecha (2026-09-10 y 2026-10-08): la receta va antes que la venta. V015 es Anulada pero se incluye.
    assert [(e["tipo"], e["id"]) for e in h] == [
        ("receta", "RC001"), ("venta", "V003"), ("venta", "V015"),
        ("venta", "V013"), ("receta", "RC008"), ("venta", "V010"),
    ]
    fechas = [e["fecha"] for e in h]
    assert fechas == sorted(fechas)


def test_cada_evento_trae_su_detalle(db) -> None:
    h = {e["id"]: e for e in q03.ejecutar("C001", db=db)["historial"]}
    assert h["V003"]["detalle"]["total"] == 9800
    assert h["V003"]["detalle"]["items"]  # ítems embebidos
    assert h["RC001"]["detalle"]["estado"] == "Completada"
    assert h["V015"]["detalle"]["estado"] == "Anulada"


def test_cliente_con_solo_recetas_o_solo_ventas(db) -> None:
    # C002 tiene RC009 (2026-03-02, Vencida) sin venta asociada, además de V009 y V012.
    ids = [e["id"] for e in q03.ejecutar("C002", db=db)["historial"]]
    assert ids[0] == "RC009"
    assert set(ids) == {"RC009", "RC005", "V009", "V012"}


def test_cliente_inexistente_y_parametro_faltante(db) -> None:
    with pytest.raises(DomainError) as exc:
        q03.ejecutar("C999", db=db)
    assert exc.value.code == NO_ENCONTRADO
    with pytest.raises(DomainError) as exc:
        q03.ejecutar(None, db=db)
    assert exc.value.code == VALIDACION_ERROR
    with pytest.raises(DomainError):
        q03.ejecutar("   ", db=db)


def test_endpoint_http_recibe_el_parametro(db) -> None:
    c = TestClient(app)
    r = c.get("/api/queries/q03", params={"id_cliente": "C001"})
    assert r.status_code == 200
    assert len(r.json()["result"]["historial"]) == 6
    assert c.get("/api/queries/q03").status_code == 400
    assert c.get("/api/queries/q03", params={"id_cliente": "C999"}).status_code == 404
