"""Pruebas de q01 contra MongoDB y Redis cache-aside (CSV originales, entorno aislado)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
import seed
from src.infrastructure.config import get_settings
from src.infrastructure.mongo import check_mongo_health, get_db, get_mongo_client
from src.infrastructure.redis_client import check_redis_health, get_redis_client
from src.loading.validation import leer_directorio, maximos_contadores, validar_y_transformar
from src.queries import EJECUTORES, get_query_metadata, q01
from src.services.cache import clave_producto, clave_proveedor
from src.web.app import app

TEST_DB = "farmared_test_q01"
TEST_REDIS_PREFIX = "farmared_test_q01:"
ORIGINALES = Path(__file__).resolve().parent.parent / "data" / "original"


def _limpiar_redis_prefijo(prefijo: str, *, redis_url: str | None = None) -> None:
    """Elimina las claves del prefijo de prueba si Redis está disponible."""
    cliente = None
    try:
        cliente = get_redis_client(url=redis_url)
        claves = list(cliente.scan_iter(match=f"{prefijo}*", count=200))
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

    redis_url_real = get_settings().redis_url
    _limpiar_redis_prefijo(TEST_REDIS_PREFIX, redis_url=redis_url_real)

    crudo = leer_directorio(ORIGINALES, "original")
    docs, reporte = validar_y_transformar(crudo)
    assert reporte.ok, reporte.errores
    seed.cargar_en_mongo(docs, maximos_contadores(crudo), db_name=TEST_DB)
    base = get_db(client=get_mongo_client(), db_name=TEST_DB)

    monkeypatch.setattr("src.queries.q01.get_shared_db", lambda: base)
    monkeypatch.setenv("REDIS_PREFIX", TEST_REDIS_PREFIX)
    try:
        yield base
    finally:
        _limpiar_redis_prefijo(TEST_REDIS_PREFIX, redis_url=redis_url_real)
        base.client.drop_database(TEST_DB)
        base.client.close()


def test_devuelve_productos_activos_con_proveedor_completo(db) -> None:
    resultado = q01.ejecutar(db=db)
    ids = [prod["id_producto"] for prod in resultado]
    assert ids == [f"PRD{n:03d}" for n in range(1, 12)]
    assert "PRD012" not in ids
    assert "PRD013" not in ids

    campos_proveedor = {
        "id_proveedor",
        "razon_social",
        "cuit",
        "tipo",
        "ciudad",
        "provincia",
        "telefono",
        "activo",
    }
    for prod in resultado:
        assert list(prod)[0] == "id_producto"
        assert prod["activo"] is True
        assert prod["proveedor"] is not None
        assert list(prod["proveedor"])[0] == "id_proveedor"
        assert set(prod["proveedor"]) == campos_proveedor
        assert prod["proveedor"]["id_proveedor"] == prod["id_proveedor"]

    assert resultado[0]["nombre"] == "Paracetamol 500mg x30"
    assert resultado[0]["precio_unit"] == 2800
    assert resultado[0]["proveedor"] == {
        "id_proveedor": "PRV001",
        "razon_social": "Laboratorios Andinos S.A.",
        "cuit": "30-71234567-1",
        "tipo": "Laboratorio",
        "ciudad": "Buenos Aires",
        "provincia": "Buenos Aires",
        "telefono": "1143001100",
        "activo": True,
    }
    assert resultado[7]["id_producto"] == "PRD008"
    assert resultado[7]["proveedor"]["id_proveedor"] == "PRV004"


def test_incluye_producto_activo_con_proveedor_inactivo(db) -> None:
    # PRD013 referencia a PRV005, cuyo campo activo ya es False en los CSV originales.
    db["productos"].update_one({"_id": "PRD013"}, {"$set": {"activo": True}})
    db["proveedores"].update_one({"_id": "PRV002"}, {"$set": {"activo": False}})

    resultado = q01.ejecutar(db=db)
    por_id = {prod["id_producto"]: prod for prod in resultado}

    assert list(por_id) == [f"PRD{n:03d}" for n in range(1, 12)] + ["PRD013"]
    assert por_id["PRD013"]["proveedor"]["id_proveedor"] == "PRV005"
    assert por_id["PRD013"]["proveedor"]["razon_social"] == "BioPampa Laboratorios S.A."
    assert por_id["PRD013"]["proveedor"]["activo"] is False
    assert por_id["PRD004"]["proveedor"]["id_proveedor"] == "PRV002"
    assert por_id["PRD004"]["proveedor"]["activo"] is False


def test_sin_productos_activos_devuelve_lista_vacia(db) -> None:
    db["productos"].update_many({}, {"$set": {"activo": False}})
    assert q01.ejecutar(db=db) == []


def test_cache_aside_redis_miss_hit_ttl_e_invalidacion(db) -> None:
    if check_redis_health()["status"] != "ok":
        pytest.skip("Redis no disponible")

    redis_cli = get_redis_client()
    try:
        k_prod = clave_producto("PRD001")
        k_prov = clave_proveedor("PRV001")
        assert k_prod == f"{TEST_REDIS_PREFIX}producto:PRD001"
        assert k_prov == f"{TEST_REDIS_PREFIX}proveedor:PRV001"
        assert redis_cli.get(k_prod) is None
        assert redis_cli.get(k_prov) is None

        # 1) Cache miss: consulta MongoDB y puebla Redis con TTL <= 300s
        primera = q01.ejecutar(db=db)
        assert len(primera) == 11
        assert json.loads(redis_cli.get(k_prod))["_id"] == "PRD001"
        assert json.loads(redis_cli.get(k_prov))["_id"] == "PRV001"
        assert 0 < redis_cli.ttl(k_prod) <= 300
        assert 0 < redis_cli.ttl(k_prov) <= 300
        assert redis_cli.get(clave_producto("PRD012")) is None
        assert redis_cli.get(clave_proveedor("PRV005")) is None

        # 2) Cache hit: los cambios en MongoDB no alteran la respuesta mientras sigan en caché
        db["productos"].update_one({"_id": "PRD001"}, {"$set": {"precio_unit": 9999}})
        db["proveedores"].update_one(
            {"_id": "PRV001"},
            {"$set": {"razon_social": "Laboratorios Modificados S.A."}},
        )
        segunda = q01.ejecutar(db=db)
        assert segunda == primera
        assert segunda[0]["precio_unit"] == 2800
        assert segunda[0]["proveedor"]["razon_social"] == "Laboratorios Andinos S.A."

        # 3) Invalidación explícita: borra claves en Redis y recarga lo actualizado desde MongoDB
        assert redis_cli.delete(k_prod, k_prov) == 2
        tercera = q01.ejecutar(db=db)
        assert tercera[0]["precio_unit"] == 9999
        assert tercera[0]["proveedor"]["razon_social"] == "Laboratorios Modificados S.A."
        assert 0 < redis_cli.ttl(k_prod) <= 300
        assert 0 < redis_cli.ttl(k_prov) <= 300
    finally:
        redis_cli.close()


def test_fallback_a_mongodb_si_redis_no_disponible(db, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6399/0")
    resultado = q01.ejecutar(db=db)
    assert [prod["id_producto"] for prod in resultado] == [f"PRD{n:03d}" for n in range(1, 12)]
    assert resultado[0]["proveedor"]["id_proveedor"] == "PRV001"


def test_endpoint_cli_catalogo_y_registro(db, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    assert EJECUTORES["q01"] is q01.ejecutar
    assert get_query_metadata("q01")["implemented"] is True

    respuesta = TestClient(app).get("/api/queries/q01")
    assert respuesta.status_code == 200
    assert respuesta.json()["status"] == "ok"
    esperado = q01.ejecutar(db=db)
    assert respuesta.json()["resultado"] == esperado

    assert main.main(["--query", "q01"]) == 0
    assert json.loads(capsys.readouterr().out) == esperado

    simulado = [{"id_producto": "PRD001", "nombre": "Simulado", "proveedor": None}]
    monkeypatch.setitem(EJECUTORES, "q01", lambda: simulado)
    assert main.main(["--query", "q01"]) == 0
    assert json.loads(capsys.readouterr().out) == simulado
    resp_compartida = TestClient(app).get("/api/queries/q01")
    assert resp_compartida.status_code == 200
    assert resp_compartida.json()["resultado"] == simulado
