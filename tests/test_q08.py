"""Pruebas de q08 contra MongoDB y caché Redis cache-aside (CSV originales, entorno aislado)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
import seed
from src.clock import date_to_bson
from src.infrastructure.config import get_settings
from src.infrastructure.mongo import check_mongo_health, get_db, get_mongo_client
from src.infrastructure.redis_client import check_redis_health, get_redis_client
from src.loading.validation import leer_directorio, maximos_contadores, validar_y_transformar
from src.queries import EJECUTORES, get_query_metadata, q08
from src.services.cache import clave_producto, clave_proveedor
from src.services.serialization import a_json
from src.web.app import app

TEST_DB = "farmared_test_q08"
TEST_REDIS_PREFIX = "farmared_test_q08:"
ORIGINALES = Path(__file__).resolve().parent.parent / "data" / "original"


def _limpiar_redis_test(redis_url: str) -> None:
    """Elimina las claves Redis pertenecientes al prefijo aislado de q08."""
    cliente = None
    try:
        cliente = get_redis_client(url=redis_url)
        claves = list(cliente.scan_iter(match=f"{TEST_REDIS_PREFIX}*", count=200))
        if claves:
            cliente.delete(*claves)
    except Exception:
        pass
    finally:
        if cliente is not None:
            try:
                cliente.close()
            except Exception:
                pass


@pytest.fixture()
def db(monkeypatch: pytest.MonkeyPatch):
    if check_mongo_health()["status"] != "ok":
        pytest.skip("MongoDB (rs0) no disponible")

    monkeypatch.setenv("REDIS_PREFIX", TEST_REDIS_PREFIX)
    redis_url = get_settings().redis_url
    _limpiar_redis_test(redis_url)

    crudo = leer_directorio(ORIGINALES, "original")
    docs, reporte = validar_y_transformar(crudo)
    assert reporte.ok, reporte.errores
    seed.cargar_en_mongo(docs, maximos_contadores(crudo), db_name=TEST_DB)
    base = get_db(client=get_mongo_client(), db_name=TEST_DB)
    monkeypatch.setattr("src.queries.q08.get_shared_db", lambda: base)
    try:
        yield base
    finally:
        _limpiar_redis_test(redis_url)
        base.client.drop_database(TEST_DB)
        base.client.close()


def test_originales_devuelve_lotes_menores_a_50_ordenados_y_enriquecidos(db) -> None:
    resultado = q08.ejecutar(db=db)

    assert [(item["id_lote"], item["unidades"]) for item in resultado] == [
        ("L010", 12),
        ("L018", 15),
        ("L003", 18),
        ("L007", 22),
        ("L012", 30),
        ("L002", 35),
        ("L005", 40),
        ("L014", 45),
        ("L011", 48),
    ]
    assert list(resultado[0]) == [
        "id_lote",
        "nro_lote",
        "unidades",
        "vencimiento",
        "id_producto",
        "id_sucursal",
        "producto",
        "sucursal",
        "proveedor",
    ]
    assert list(resultado[0]["producto"])[0] == "id_producto"
    assert list(resultado[0]["sucursal"])[0] == "id_sucursal"
    assert list(resultado[0]["proveedor"])[0] == "id_proveedor"

    # L018 está vencido (2026-09-30) y corresponde al producto inactivo PRD012.
    lote_vencido = resultado[1]
    assert lote_vencido["id_lote"] == "L018"
    assert lote_vencido["nro_lote"] == "L-2301Z"
    assert lote_vencido["unidades"] == 15
    assert lote_vencido["vencimiento"] == date_to_bson("2026-09-30")
    assert lote_vencido["id_producto"] == "PRD012"
    assert lote_vencido["id_sucursal"] == "S002"
    assert lote_vencido["producto"] == {
        "id_producto": "PRD012",
        "nombre": "Alcohol en gel 250ml",
        "principio_activo": "Alcohol etílico 70%",
        "categoria": "Antiséptico",
        "presentacion": "Solución 250 ml",
        "condicion_venta": "Venta libre",
        "precio_unit": 1800,
        "id_proveedor": "PRV002",
        "activo": False,
    }
    assert lote_vencido["sucursal"] == {
        "id_sucursal": "S002",
        "nombre": "Farmacia Belgrano",
        "tipo": "Farmacia",
        "direccion": "Av. Cabildo 2150",
        "ciudad": "Buenos Aires",
        "provincia": "Buenos Aires",
        "telefono": "1148002002",
        "activo": True,
    }
    assert lote_vencido["proveedor"] == {
        "id_proveedor": "PRV002",
        "razon_social": "DroguMed S.R.L.",
        "cuit": "30-70987654-3",
        "tipo": "Droguería",
        "ciudad": "Córdoba",
        "provincia": "Córdoba",
        "telefono": "3514102200",
        "activo": True,
    }


def test_limites_cero_49_y_50_unidades_e_inactivos(db) -> None:
    db["sucursales"].update_one({"_id": "S001"}, {"$set": {"activo": False}})
    db["stock_lotes"].insert_many(
        [
            {
                "_id": "L090",
                "id_producto": "PRD013",  # producto inactivo con proveedor PRV005 inactivo
                "id_sucursal": "S001",
                "nro_lote": "L-CERO",
                "unidades": 0,
                "vencimiento": date_to_bson("2025-01-10"),
            },
            {
                "_id": "L091",
                "id_producto": "PRD002",
                "id_sucursal": "S001",
                "nro_lote": "L-BORDE49",
                "unidades": 49,
                "vencimiento": date_to_bson("2027-03-31"),
            },
        ]
    )
    db["stock_lotes"].update_one({"_id": "L001"}, {"$set": {"unidades": 49}})
    db["stock_lotes"].update_one({"_id": "L004"}, {"$set": {"unidades": 50}})

    resultado = q08.ejecutar(db=db)
    ids_y_unidades = [(item["id_lote"], item["unidades"]) for item in resultado]
    assert ids_y_unidades[0] == ("L090", 0)
    assert ids_y_unidades[-2:] == [("L001", 49), ("L091", 49)]
    assert "L004" not in {item["id_lote"] for item in resultado}

    lote_cero = resultado[0]
    assert lote_cero["producto"]["id_producto"] == "PRD013"
    assert lote_cero["producto"]["activo"] is False
    assert lote_cero["sucursal"]["id_sucursal"] == "S001"
    assert lote_cero["sucursal"]["activo"] is False
    assert lote_cero["proveedor"]["id_proveedor"] == "PRV005"
    assert lote_cero["proveedor"]["activo"] is False

    db["stock_lotes"].update_many({"unidades": {"$lt": 50}}, {"$set": {"unidades": 50}})
    assert q08.ejecutar(db=db) == []

    db["stock_lotes"].delete_many({})
    assert q08.ejecutar(db=db) == []


def test_cache_aside_redis_para_producto_y_proveedor_y_no_stock(db) -> None:
    if check_redis_health()["status"] != "ok":
        pytest.skip("Redis no disponible")

    ttl_esperado = get_settings().redis_ttl_seconds
    cliente = get_redis_client()
    try:
        assert list(cliente.scan_iter(match=f"{TEST_REDIS_PREFIX}*", count=200)) == []

        primera = q08.ejecutar(db=db)
        assert len(primera) == 9

        productos_esperados = {
            "PRD001",
            "PRD003",
            "PRD004",
            "PRD007",
            "PRD008",
            "PRD009",
            "PRD010",
            "PRD012",
        }
        proveedores_esperados = {"PRV001", "PRV002", "PRV003", "PRV004"}
        claves_esperadas = {clave_producto(pid) for pid in productos_esperados} | {
            clave_proveedor(prvid) for prvid in proveedores_esperados
        }

        claves_en_redis = set(cliente.scan_iter(match=f"{TEST_REDIS_PREFIX}*", count=200))
        assert claves_en_redis == claves_esperadas
        assert not any("stock" in clave or "lote" in clave or "sucursal" in clave for clave in claves_en_redis)

        for clave in claves_esperadas:
            raw = cliente.get(clave)
            assert raw is not None
            assert "_id" in json.loads(raw)
            assert 0 < cliente.ttl(clave) <= ttl_esperado

        # Modificaciones en MongoDB: producto/proveedor siguen sirviéndose desde caché (hit),
        # mientras que stock_lotes y sucursales se leen frescos de MongoDB.
        db["productos"].update_one(
            {"_id": "PRD008"}, {"$set": {"presentacion": "Comprimidos x30 (Mongo)"}}
        )
        db["proveedores"].update_one({"_id": "PRV004"}, {"$set": {"telefono": "1199990000"}})
        db["stock_lotes"].update_one({"_id": "L010"}, {"$set": {"unidades": 11}})
        db["sucursales"].update_one({"_id": "S003"}, {"$set": {"telefono": "3419999999"}})

        segunda = q08.ejecutar(db=db)
        assert segunda[0]["id_lote"] == "L010"
        assert segunda[0]["unidades"] == 11
        assert segunda[0]["sucursal"]["telefono"] == "3419999999"
        assert segunda[0]["producto"]["presentacion"] == "Comprimidos x30"
        assert segunda[0]["proveedor"]["telefono"] == "1142304400"

        # Al invalidar las claves en Redis, la consulta recarga desde MongoDB y repuebla con TTL.
        cliente.delete(clave_producto("PRD008"), clave_proveedor("PRV004"))
        tercera = q08.ejecutar(db=db)
        assert tercera[0]["producto"]["presentacion"] == "Comprimidos x30 (Mongo)"
        assert tercera[0]["proveedor"]["telefono"] == "1199990000"
        assert 0 < cliente.ttl(clave_producto("PRD008")) <= ttl_esperado
        assert 0 < cliente.ttl(clave_proveedor("PRV004")) <= ttl_esperado
    finally:
        cliente.close()


def test_fallback_a_mongodb_si_redis_no_disponible(db, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6399/0")

    resultado = q08.ejecutar(db=db)
    assert [(item["id_lote"], item["unidades"]) for item in resultado] == [
        ("L010", 12),
        ("L018", 15),
        ("L003", 18),
        ("L007", 22),
        ("L012", 30),
        ("L002", 35),
        ("L005", 40),
        ("L014", 45),
        ("L011", 48),
    ]
    assert resultado[0]["producto"]["nombre"] == "Alprazolam 0,5mg x30"
    assert resultado[1]["producto"]["nombre"] == "Alcohol en gel 250ml"
    assert resultado[1]["proveedor"]["razon_social"] == "DroguMed S.R.L."


def test_endpoint_cli_catalogo_y_registro(db, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    assert EJECUTORES["q08"] is q08.ejecutar
    assert get_query_metadata("q08")["implemented"] is True

    respuesta = TestClient(app).get("/api/queries/q08")
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["status"] == "ok"
    assert cuerpo["query"]["id"] == "q08"

    esperado = a_json(q08.ejecutar(db=db))
    assert cuerpo["resultado"] == esperado
    assert cuerpo["resultado"][0]["vencimiento"] == "2027-01-31"
    assert cuerpo["resultado"][1]["vencimiento"] == "2026-09-30"

    assert main.main(["--query", "q08"]) == 0
    assert json.loads(capsys.readouterr().out) == esperado

    simulado = [{"id_lote": "L999", "vencimiento": date_to_bson("2026-09-30")}]
    monkeypatch.setitem(EJECUTORES, "q08", lambda: simulado)
    respuesta_compartida = TestClient(app).get("/api/queries/q08")
    assert respuesta_compartida.status_code == 200
    assert respuesta_compartida.json()["resultado"] == [{"id_lote": "L999", "vencimiento": "2026-09-30"}]
    assert main.main(["--query", "q08"]) == 0
    assert json.loads(capsys.readouterr().out) == respuesta_compartida.json()["resultado"]
