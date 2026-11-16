"""Pruebas de q11 contra MongoDB (CSV originales, reloj fijo y base aislada)."""

from __future__ import annotations

import copy
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
from src.queries import EJECUTORES, get_query_metadata, q11
from src.web.app import app

TEST_DB = "farmared_test_q11"
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
    monkeypatch.setattr("src.queries.q11.get_shared_db", lambda: base)
    try:
        yield base
    finally:
        base.client.drop_database(TEST_DB)
        base.client.close()


def _nueva_venta(
    plantilla: dict,
    *,
    id_venta: str,
    id_farmaceutico: str,
    fecha: str,
    total: int,
    estado: str = "Completada",
) -> dict:
    doc = copy.deepcopy(plantilla)
    doc["_id"] = id_venta
    doc["id_farmaceutico"] = id_farmaceutico
    doc["fecha"] = date_to_bson(fecha)
    doc["total"] = total
    doc["estado"] = estado
    doc["stock_aplicado"] = estado == "Completada"
    return doc


def test_ingresos_mes_actual_al_13_10_2026(db) -> None:
    with fixed_clock(date(2026, 10, 13)):
        resultado = q11.ejecutar(db=db)

    assert [(r["id_farmaceutico"], r["ingresos_totales"]) for r in resultado] == [
        ("F002", 7800),
        ("F003", 7100),
        ("F005", 4600),
        ("F001", 4400),
    ]
    assert list(resultado[0])[0] == "id_farmaceutico"

    por_id = {r["id_farmaceutico"]: r for r in resultado}
    assert all(r["cantidad_ventas"] == 1 for r in resultado)
    assert por_id["F002"]["nombre"] == "Sebastián"
    assert por_id["F002"]["apellido"] == "Ledesma"
    assert por_id["F002"]["matricula"] == "MN-18078"
    assert por_id["F002"]["id_sucursal"] == "S001"
    assert por_id["F002"]["activo"] is True
    # V011 (F006) y V012 (F005) son Pendiente; V015 (F002, 25/09) es Anulada y de otro mes.
    assert "F006" not in por_id


def test_incluye_farmaceutico_inactivo_y_excluye_pendientes_y_anuladas_del_mismo_mes(db) -> None:
    with fixed_clock(date(2025, 9, 20)):
        sep_2025 = q11.ejecutar(db=db)

    assert len(sep_2025) == 1
    assert sep_2025[0]["id_farmaceutico"] == "F004"
    assert sep_2025[0]["ingresos_totales"] == 3850
    assert sep_2025[0]["cantidad_ventas"] == 1
    assert sep_2025[0]["activo"] is False

    plantilla = db["ventas"].find_one({"_id": "V013"})
    db["ventas"].insert_many([
        _nueva_venta(plantilla, id_venta="V901", id_farmaceutico="F002", fecha="2026-10-15", total=5000, estado="Anulada"),
        _nueva_venta(plantilla, id_venta="V902", id_farmaceutico="F001", fecha="2026-10-16", total=6000, estado="Pendiente"),
    ])
    db["ventas"].update_one({"_id": "V010"}, {"$set": {"estado": "Anulada"}})
    db["ventas"].update_one({"_id": "V014"}, {"$set": {"estado": "Pendiente"}})

    with fixed_clock(date(2026, 10, 13)):
        oct_2026 = q11.ejecutar(db=db)

    assert [(r["id_farmaceutico"], r["ingresos_totales"]) for r in oct_2026] == [
        ("F002", 7800),
        ("F001", 4400),
    ]


def test_limites_ventana_mensual_y_cambio_de_anio(db) -> None:
    assert q11.ventana(date(2026, 12, 15)) == (date(2026, 12, 1), date(2027, 1, 1))
    assert q11.ventana(date(2026, 10, 13)) == (date(2026, 10, 1), date(2026, 11, 1))

    plantilla = db["ventas"].find_one({"_id": "V013"})
    db["ventas"].insert_many([
        _nueva_venta(plantilla, id_venta="V910", id_farmaceutico="F001", fecha="2026-11-30", total=1000),
        _nueva_venta(plantilla, id_venta="V911", id_farmaceutico="F001", fecha="2026-12-01", total=2500),
        _nueva_venta(plantilla, id_venta="V912", id_farmaceutico="F001", fecha="2026-12-31", total=1500),
        _nueva_venta(plantilla, id_venta="V913", id_farmaceutico="F002", fecha="2027-01-01", total=9000),
    ])

    with fixed_clock(date(2026, 12, 15)):
        dic_2026 = q11.ejecutar(db=db)
    assert [(r["id_farmaceutico"], r["ingresos_totales"], r["cantidad_ventas"]) for r in dic_2026] == [
        ("F001", 4000, 2),
    ]

    with fixed_clock(date(2027, 1, 5)):
        ene_2027 = q11.ejecutar(db=db)
    assert [(r["id_farmaceutico"], r["ingresos_totales"], r["cantidad_ventas"]) for r in ene_2027] == [
        ("F002", 9000, 1),
    ]

    with fixed_clock(date(2026, 2, 15)):
        assert q11.ejecutar(db=db) == []


def test_desempate_por_id_farmaceutico(db) -> None:
    plantilla = db["ventas"].find_one({"_id": "V013"})
    db["ventas"].insert_many([
        # Insertados en orden inverso para comprobar que el desempate no depende de la inserción.
        _nueva_venta(plantilla, id_venta="V920", id_farmaceutico="F006", fecha="2026-05-10", total=5000),
        _nueva_venta(plantilla, id_venta="V921", id_farmaceutico="F005", fecha="2026-05-11", total=2000),
        _nueva_venta(plantilla, id_venta="V922", id_farmaceutico="F005", fecha="2026-05-12", total=3000),
        _nueva_venta(plantilla, id_venta="V923", id_farmaceutico="F003", fecha="2026-05-10", total=5000),
        _nueva_venta(plantilla, id_venta="V924", id_farmaceutico="F001", fecha="2026-05-10", total=5000),
    ])

    with fixed_clock(date(2026, 5, 20)):
        resultado = q11.ejecutar(db=db)

    assert [(r["id_farmaceutico"], r["ingresos_totales"]) for r in resultado] == [
        ("F001", 5000),
        ("F003", 5000),
        ("F005", 5000),
        ("F006", 5000),
    ]


def test_endpoint_cli_catalogo_y_registro(
    db,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert get_query_metadata("q11")["implemented"] is True
    assert EJECUTORES["q11"] is q11.ejecutar

    with fixed_clock(date(2026, 10, 13)):
        esperado = q11.ejecutar(db=db)
        respuesta = TestClient(app).get("/api/queries/q11")
        assert respuesta.status_code == 200
        assert respuesta.json()["status"] == "ok"
        assert respuesta.json()["query"]["id"] == "q11"
        assert respuesta.json()["resultado"] == esperado

        assert main.main(["--query", "q11"]) == 0
        assert json.loads(capsys.readouterr().out) == esperado

    mock_resultado = [{"id_farmaceutico": "F002", "ingresos_totales": 7800, "cantidad_ventas": 1}]
    monkeypatch.setitem(EJECUTORES, "q11", lambda: mock_resultado)
    respuesta_mock = TestClient(app).get("/api/queries/q11")
    assert respuesta_mock.status_code == 200
    assert respuesta_mock.json()["resultado"] == mock_resultado
    assert main.main(["--query", "q11"]) == 0
    assert json.loads(capsys.readouterr().out) == mock_resultado
