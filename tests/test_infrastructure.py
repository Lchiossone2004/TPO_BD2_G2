"""Pruebas de Fase 0 y Fase 1: datasets originales, reloj, MongoDB rs0 (ACID), Redis y Web FastAPI."""

from __future__ import annotations

import csv
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.clock import AR_TZ, bson_to_date, date_to_bson, fixed_clock, format_iso_date, hoy
from src.infrastructure.mongo import check_mongo_health, get_db, get_mongo_client
from src.infrastructure.redis_client import check_redis_health, get_redis_client
from src.web.app import app

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ORIGINALES_DIR = PROJECT_ROOT / "data" / "originales"

EXPECTED_CSV_COUNTS = {
    "clientes.csv": 8,
    "sucursales.csv": 5,
    "farmaceuticos.csv": 7,
    "proveedores.csv": 5,
    "productos.csv": 13,
    "stock_lotes.csv": 18,
    "recetas.csv": 9,
    "ventas.csv": 16,
    "detalle_ventas.csv": 22,
}


class _DeliberateTransactionAbort(RuntimeError):
    """Error intencional para validar el rollback atómico de transacciones MongoDB."""


def test_original_csv_datasets_present_and_complete() -> None:
    """Verifica que los 9 CSV originales estén extraídos en data/originales/ con sus conteos."""
    total_rows = 0
    for filename, expected_count in EXPECTED_CSV_COUNTS.items():
        path = ORIGINALES_DIR / filename
        assert path.is_file(), f"Falta el archivo original {path}"
        with path.open("r", encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == expected_count, f"{filename}: esperado {expected_count}, obtenido {len(rows)}"
        total_rows += len(rows)
    assert total_rows == 103


def test_clock_buenos_aires_and_bson_roundtrip() -> None:
    """Verifica hoy(), fixed_clock() y conversión BSON UTC medianoche sin corrimiento de día."""
    assert str(AR_TZ) == "America/Argentina/Buenos_Aires"
    assert isinstance(hoy(), date)

    target = date(2026, 10, 13)
    with fixed_clock(target) as active:
        assert active == target
        assert hoy() == target

        bson_dt = date_to_bson(hoy())
        assert isinstance(bson_dt, datetime)
        assert bson_dt == datetime(2026, 10, 13, 0, 0, 0, tzinfo=timezone.utc)
        assert bson_to_date(bson_dt) == target
        assert format_iso_date(bson_dt) == "2026-10-13"

    # Simulación de timestamp posterior a las 21:00 AR (00:00+ UTC del día siguiente en reloj real)
    utc_midnight = datetime(2026, 10, 13, 0, 0, 0, tzinfo=timezone.utc)
    assert bson_to_date(utc_midnight) == date(2026, 10, 13)


def test_mongodb_replica_set_health() -> None:
    """Confirma que MongoDB está operativo como primario del Replica Set rs0."""
    health = check_mongo_health()
    assert health["status"] == "ok", f"MongoDB health error: {health}"
    assert health["replica_set"] == "rs0"
    assert health["is_writable_primary"] is True
    assert health["database"] == "farmared"


def test_mongodb_multidocument_transaction_commit_and_rollback() -> None:
    """Spike Fase 0: valida commit atómico y rollback deliberado multi-documento en rs0."""
    client = get_mongo_client()
    db = get_db(client=client)
    ventas_col = db["_test_spike_ventas"]
    stock_col = db["_test_spike_stock"]

    try:
        ventas_col.drop()
        stock_col.drop()

        # Pre-cargar un lote inicial fuera de la transacción de prueba
        stock_col.insert_one({"_id": "L-SPIKE-1", "unidades": 10})

        # 1) Commit exitoso: descuenta stock e inserta venta en una sola transacción
        with client.start_session() as session:

            def _commit_tx(s) -> None:
                res = stock_col.update_one(
                    {"_id": "L-SPIKE-1", "unidades": {"$gte": 4}},
                    {"$inc": {"unidades": -4}},
                    session=s,
                )
                assert res.modified_count == 1
                ventas_col.insert_one({"_id": "V-SPIKE-OK", "unidades": 4}, session=s)

            session.with_transaction(_commit_tx)

        assert stock_col.find_one({"_id": "L-SPIKE-1"})["unidades"] == 6
        assert ventas_col.find_one({"_id": "V-SPIKE-OK"}) is not None

        # 2) Rollback deliberado: modifica stock e inserta venta, luego aborta antes del commit
        with pytest.raises(_DeliberateTransactionAbort):
            with client.start_session() as session:

                def _abort_tx(s) -> None:
                    stock_col.update_one(
                        {"_id": "L-SPIKE-1"},
                        {"$inc": {"unidades": -6}},
                        session=s,
                    )
                    ventas_col.insert_one({"_id": "V-SPIKE-ABORT", "unidades": 6}, session=s)
                    raise _DeliberateTransactionAbort("Fallo deliberado antes del commit")

                session.with_transaction(_abort_tx)

        # Ningún cambio parcial debe haber persistido tras el abort
        assert stock_col.find_one({"_id": "L-SPIKE-1"})["unidades"] == 6
        assert ventas_col.find_one({"_id": "V-SPIKE-ABORT"}) is None
    finally:
        ventas_col.drop()
        stock_col.drop()
        client.close()


def test_redis_connectivity_ttl_and_degraded_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifica conexión Redis, lectura/escritura con TTL y modo degradado ante Redis caído."""
    health = check_redis_health()
    assert health["status"] == "ok", f"Redis health error: {health}"
    assert health["available"] is True
    assert health["ttl_seconds"] == 300

    r = get_redis_client()
    test_key = "farmared:test:spike"
    try:
        r.set(test_key, '{"id":"PRD001","nombre":"Paracetamol"}', ex=30)
        assert r.get(test_key) == '{"id":"PRD001","nombre":"Paracetamol"}'
        assert 0 < r.ttl(test_key) <= 30
    finally:
        r.delete(test_key)
        r.close()

    # Simular indisponibilidad de Redis sin bloquear ni lanzar excepción no controlada
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6399/0")
    degraded = check_redis_health()
    assert degraded["status"] == "degraded"
    assert degraded["available"] is False
    assert "fallback" in degraded["message"].lower()


def test_web_app_initial_endpoints() -> None:
    """Verifica la aplicación FastAPI inicial, estáticos HTML, health, arquitectura y catálogo Q1–Q15."""
    client = TestClient(app)

    home_resp = client.get("/")
    assert home_resp.status_code == 200
    assert "FarmaRed" in home_resp.text

    health_resp = client.get("/api/health")
    assert health_resp.status_code == 200
    health_data = health_resp.json()
    assert health_data["status"] == "ok"
    assert health_data["timezone"] == "America/Argentina/Buenos_Aires"
    assert health_data["mongodb"]["status"] == "ok"
    assert health_data["mongodb"]["replica_set"] == "rs0"
    assert health_data["redis"]["status"] == "ok"

    arch_resp = client.get("/api/architecture")
    assert arch_resp.status_code == 200
    arch_data = arch_resp.json()
    assert len(arch_data["collections"]) == 9
    assert len(arch_data["redis_keys"]) == 2
    assert arch_data["motors"]["mongodb"]["deployment"] == "Replica Set rs0"

    queries_resp = client.get("/api/queries")
    assert queries_resp.status_code == 200
    queries_data = queries_resp.json()
    assert queries_data["total"] == 15
    assert len(queries_data["queries"]) == 15

    pending_resp = client.get("/api/queries/q01")
    assert pending_resp.status_code == 501
    assert pending_resp.json()["status"] == "pending"

    not_found_resp = client.get("/api/queries/q99")
    assert not_found_resp.status_code == 404
    assert not_found_resp.json()["error"]["code"] == "NO_ENCONTRADO"
