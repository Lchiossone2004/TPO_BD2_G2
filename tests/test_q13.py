"""Pruebas de q13 contra MongoDB"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import seed
from src.loading.validation import leer_directorio, maximos_contadores, validar_y_transformar
from src.infrastructure.mongo import check_mongo_health, get_db, get_mongo_client
from src.queries import q13
from src.services.exceptions import DNI_DUPLICADO, NO_ENCONTRADO, VALIDACION_ERROR, DomainError
from src.web.app import app

TEST_DB = "farmared_test"
ORIGINALES = Path(__file__).resolve().parent.parent / "data" / "original"
ALTA = dict(accion="alta", nombre="Ana", apellido="Paz", dni="30111222", email="ana@mail.com",
            telefono="1155001122", ciudad="Rosario", provincia="Santa Fe", obra_social="OSDE", nro_afiliado="OS-1")


@pytest.fixture()
def db(monkeypatch: pytest.MonkeyPatch):
    if check_mongo_health()["status"] != "ok":
        pytest.skip("MongoDB (rs0) no disponible")
    crudo = leer_directorio(ORIGINALES, "original")
    docs, reporte = validar_y_transformar(crudo)
    assert reporte.ok
    seed.cargar_en_mongo(docs, maximos_contadores(crudo), db_name=TEST_DB)
    base = get_db(client=get_mongo_client(), db_name=TEST_DB)
    monkeypatch.setattr("src.queries.q13.get_shared_db", lambda: base)
    monkeypatch.setattr("src.infrastructure.mongo.get_shared_db", lambda: base)
    yield base
    base.client.drop_database(TEST_DB)
    base.client.close()


def test_alta_genera_id_con_contador_y_guarda_activo(db) -> None:
    r = q13.ejecutar(db=db, **ALTA)
    assert r["antes"] is None and r["despues"]["_id"] == "C009" and r["despues"]["activo"] is True
    assert db["clientes"].find_one({"_id": "C009"})["dni"] == "30111222"
    assert db["contadores"].find_one({"_id": "cliente"})["valor"] == 9


def test_alta_con_dni_duplicado_se_rechaza_y_no_consume_id(db) -> None:
    with pytest.raises(DomainError) as exc:
        q13.ejecutar(db=db, **{**ALTA, "dni": "31245678"})  # DNI de C001
    assert exc.value.code == DNI_DUPLICADO and exc.value.status_code == 409
    assert db["clientes"].count_documents({}) == 8
    assert db["contadores"].find_one({"_id": "cliente"})["valor"] == 8  # la transacción revirtió el contador
    assert q13.ejecutar(db=db, **ALTA)["despues"]["_id"] == "C009"


def test_alta_sin_datos_obligatorios_se_rechaza(db) -> None:
    with pytest.raises(DomainError) as exc:
        q13.ejecutar(db=db, accion="alta", nombre="Ana")
    assert exc.value.code == VALIDACION_ERROR and "dni" in exc.value.details["campos"]


def test_modificacion_solo_cuatro_campos_con_antes_y_despues(db) -> None:
    r = q13.ejecutar(db=db, accion="modificacion", id_cliente="C001", email="nuevo@mail.com", telefono="1100000000",
                     obra_social="Galeno", nro_afiliado="GA-1")
    assert r["cambio"] is True
    assert r["antes"]["email"] == "lucia.f@gmail.com" and r["despues"]["email"] == "nuevo@mail.com"
    assert r["despues"]["obra_social"] == "Galeno" and r["despues"]["dni"] == r["antes"]["dni"]
    with pytest.raises(DomainError) as exc:
        q13.ejecutar(db=db, accion="modificacion", id_cliente="C001", ciudad="Córdoba")
    assert exc.value.code == VALIDACION_ERROR and exc.value.details["campos_no_modificables"] == ["ciudad"]
    assert db["clientes"].find_one({"_id": "C001"})["ciudad"] == "Buenos Aires"


def test_modificar_a_sin_cobertura_limpia_el_afiliado(db) -> None:
    r = q13.ejecutar(db=db, accion="modificacion", id_cliente="C001", obra_social="Sin cobertura")
    assert r["despues"]["nro_afiliado"] is None


def test_modificacion_de_cliente_inexistente(db) -> None:
    with pytest.raises(DomainError) as exc:
        q13.ejecutar(db=db, accion="modificacion", id_cliente="C999", email="x@y.com")
    assert exc.value.code == NO_ENCONTRADO and exc.value.status_code == 404


def test_baja_logica_conserva_el_dni_y_es_idempotente(db) -> None:
    r = q13.ejecutar(db=db, accion="baja", id_cliente="C002")
    assert r["antes"]["activo"] is True and r["despues"]["activo"] is False and r["cambio"] is True
    assert db["clientes"].find_one({"_id": "C002"})["dni"] == "28765432"
    assert q13.ejecutar(db=db, accion="baja", id_cliente="C002")["cambio"] is False
    with pytest.raises(DomainError) as exc:  # el DNI de un cliente dado de baja sigue ocupado
        q13.ejecutar(db=db, **{**ALTA, "dni": "28765432"})
    assert exc.value.code == DNI_DUPLICADO


def test_api_alta_201_y_error_409_por_dni_duplicado(db) -> None:
    http = TestClient(app)
    r = http.post("/api/services/clientes", json=ALTA)
    assert r.status_code == 201 and r.json()["despues"]["_id"] == "C009"
    assert http.get("/api/services/clientes/C009").json()["dni"] == "30111222"
    r = http.post("/api/services/clientes", json=ALTA)
    assert r.status_code == 409 and r.json()["error"]["code"] == DNI_DUPLICADO
    assert http.get("/api/services/clientes/C999").status_code == 404
