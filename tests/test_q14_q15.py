"""Pruebas de q14 (venta integrada) y q15 (descuento FEFO) contra MongoDB"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import seed
from src.clock import fixed_clock
from src.infrastructure.mongo import check_mongo_health, get_db, get_mongo_client
from src.loading.fixtures import crear_fixture_q15
from src.loading.validation import leer_directorio, maximos_contadores, validar_y_transformar
from src.queries import q14, q15
from src.services.exceptions import (
    CLIENTE_INACTIVO, FARMACEUTICO_INVALIDO, NO_ENCONTRADO, OPERACION_CONFLICTO, PRODUCTO_INACTIVO,
    RECETA_INVALIDA, RECETA_VENCIDA, STOCK_INSUFICIENTE, VALIDACION_ERROR, DomainError,
)
from src.web.app import app

TEST_DB = "farmared_test"
ORIGINALES = Path(__file__).resolve().parent.parent / "data" / "original"
HOY = date(2026, 10, 13)


def dt(y: int, m: int, d: int) -> datetime:
    return datetime(y, m, d, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def reloj():
    with fixed_clock(HOY):
        yield


@pytest.fixture()
def db(monkeypatch: pytest.MonkeyPatch):
    if check_mongo_health()["status"] != "ok":
        pytest.skip("MongoDB (rs0) no disponible")
    crudo = leer_directorio(ORIGINALES, "original")
    docs, reporte = validar_y_transformar(crudo)
    assert reporte.ok
    seed.cargar_en_mongo(docs, maximos_contadores(crudo), db_name=TEST_DB)
    base = get_db(client=get_mongo_client(), db_name=TEST_DB)
    monkeypatch.setattr("src.infrastructure.mongo.get_shared_db", lambda: base)
    monkeypatch.setattr("src.queries.q14.get_shared_db", lambda: base)
    monkeypatch.setattr("src.queries.q15.get_shared_db", lambda: base)
    yield base
    base.client.drop_database(TEST_DB)
    base.client.close()


def venta(db, **kw):
    datos = dict(id_cliente="C001", id_farmaceutico="F001", medio_pago="Efectivo",
                 items=[{"id_producto": "PRD001", "cantidad": 2}], id_operacion="op-1")
    datos.update(kw)
    return q14.ejecutar(db=db, **datos)


def unidades(db, id_lote):
    return db["stock_lotes"].find_one({"_id": id_lote})["unidades"]


def estado_global(db):
    return (db["ventas"].count_documents({}), db["contadores"].find_one({"_id": "venta"})["valor"],
            db["contadores"].find_one({"_id": "detalle"})["valor"], sorted((l["_id"], l["unidades"]) for l in db["stock_lotes"].find()),
            sorted((r["_id"], r["dispensas_realizadas"], r["estado"]) for r in db["recetas"].find()))


def codigo(exc_info) -> str:
    return exc_info.value.code


# ---------------------------------------------------------------- q14: camino feliz

def test_venta_libre_registra_completada_con_id_total_y_stock(db) -> None:
    r = venta(db, items=[{"id_producto": "PRD001", "cantidad": 2}, {"id_producto": "PRD002", "cantidad": 1}])
    v = r["venta"]
    assert v["_id"] == "V017" and v["estado"] == "Completada" and v["tipo"] == "Venta libre"
    assert v["total"] == 2 * 2800 + 3500 and v["origen"] == "servicio" and v["stock_aplicado"] is True
    assert [i["id_detalle"] for i in v["items"]] == ["D023", "D024"]
    assert unidades(db, "L001") == 118 and unidades(db, "L004") == 89  # sucursal S001
    assert db["ventas"].find_one({"_id": "V017"})["id_operacion"] == "op-1"
    assert db["contadores"].find_one({"_id": "venta"})["valor"] == 17


def test_productos_repetidos_se_agrupan(db) -> None:
    r = venta(db, items=[{"id_producto": "PRD001", "cantidad": 2}, {"id_producto": "PRD001", "cantidad": 3}])
    assert len(r["venta"]["items"]) == 1 and r["venta"]["items"][0]["cantidad"] == 5
    assert unidades(db, "L001") == 115


def test_fefo_consume_primero_el_lote_que_vence_antes_y_omite_vencidos(db) -> None:
    db["stock_lotes"].insert_many([
        {"_id": "LT0", "id_producto": "PRD001", "id_sucursal": "S001", "nro_lote": "T0", "unidades": 50, "vencimiento": dt(2026, 10, 1)},
        {"_id": "LT1", "id_producto": "PRD001", "id_sucursal": "S001", "nro_lote": "T1", "unidades": 5, "vencimiento": dt(2026, 12, 1)},
        {"_id": "LT2", "id_producto": "PRD001", "id_sucursal": "S001", "nro_lote": "T2", "unidades": 5, "vencimiento": dt(2027, 1, 1)},
    ])
    r = venta(db, items=[{"id_producto": "PRD001", "cantidad": 8}])
    assert r["venta"]["asignaciones_stock"] == [
        {"id_producto": "PRD001", "id_lote": "LT1", "unidades": 5},
        {"id_producto": "PRD001", "id_lote": "LT2", "unidades": 3}]
    assert unidades(db, "LT0") == 50 and unidades(db, "LT1") == 0 and unidades(db, "LT2") == 2 and unidades(db, "L001") == 120


def test_receta_simple_queda_completada(db) -> None:
    r = venta(db, id_cliente="C007", id_farmaceutico="F006", id_receta="RC006", medio_pago="Obra social",
              items=[{"id_producto": "PRD004", "cantidad": 2}])
    assert r["venta"]["tipo"] == "Con receta" and r["receta_despues"]["estado"] == "Completada"
    rc = db["recetas"].find_one({"_id": "RC006"})
    assert rc["estado"] == "Completada" and rc["dispensas_realizadas"] == 1 and rc["proxima_dispensa"] is None


def test_receta_prolongada_fija_proxima_dispensa_a_30_dias(db) -> None:
    venta(db, id_cliente="C006", id_farmaceutico="F002", id_receta="RC004", medio_pago="Obra social",
          items=[{"id_producto": "PRD006", "cantidad": 1}])
    rc = db["recetas"].find_one({"_id": "RC004"})
    assert rc["estado"] == "Vigente" and rc["dispensas_realizadas"] == 2
    assert rc["proxima_dispensa"].date() == date(2026, 11, 12)


def test_receta_prolongada_en_ultima_dispensa_se_completa(db) -> None:
    venta(db, id_cliente="C006", id_farmaceutico="F002", id_receta="RC003", medio_pago="Obra social",
          items=[{"id_producto": "PRD006", "cantidad": 1}])
    rc = db["recetas"].find_one({"_id": "RC003"})
    assert rc["estado"] == "Completada" and rc["dispensas_realizadas"] == 3 and rc["proxima_dispensa"] is None


def test_una_dispensa_por_venta_aunque_haya_varios_items(db) -> None:
    venta(db, id_cliente="C006", id_farmaceutico="F001", id_receta="RC004", medio_pago="Obra social",
          items=[{"id_producto": "PRD006", "cantidad": 1}, {"id_producto": "PRD003", "cantidad": 1}])
    assert db["recetas"].find_one({"_id": "RC004"})["dispensas_realizadas"] == 2


# ---------------------------------------------------------------- q14: rechazos sin efectos

@pytest.mark.parametrize("kw, cod", [
    (dict(id_cliente="C008"), CLIENTE_INACTIVO),
    (dict(id_cliente="C999"), NO_ENCONTRADO),
    (dict(id_farmaceutico="F004"), FARMACEUTICO_INVALIDO),            # inactivo
    (dict(id_farmaceutico="F007"), FARMACEUTICO_INVALIDO),            # sucursal Droguería
    (dict(id_farmaceutico="F999"), NO_ENCONTRADO),
    (dict(items=[{"id_producto": "PRD012", "cantidad": 1}]), PRODUCTO_INACTIVO),
    (dict(items=[{"id_producto": "PRD999", "cantidad": 1}]), NO_ENCONTRADO),
    (dict(items=[{"id_producto": "PRD003", "cantidad": 1}]), RECETA_INVALIDA),   # bajo receta sin receta
    (dict(id_receta="RC006"), RECETA_INVALIDA),                       # receta sin producto que la requiera
    (dict(id_cliente="C001", id_receta="RC006", items=[{"id_producto": "PRD004", "cantidad": 1}]), RECETA_INVALIDA),  # otro cliente
    (dict(id_cliente="C002", id_receta="RC009", items=[{"id_producto": "PRD004", "cantidad": 1}]), RECETA_VENCIDA),
    (dict(id_cliente="C001", id_receta="RC001", items=[{"id_producto": "PRD003", "cantidad": 1}]), RECETA_INVALIDA),  # completada
    (dict(items=[]), VALIDACION_ERROR),
    (dict(items=[{"id_producto": "PRD001", "cantidad": 0}]), VALIDACION_ERROR),
    (dict(items=[{"id_producto": "PRD001", "cantidad": 1.5}]), VALIDACION_ERROR),
    (dict(medio_pago="Cheque"), VALIDACION_ERROR),
])
def test_rechazos_no_dejan_venta_descuento_ni_contador(db, kw, cod) -> None:
    antes = estado_global(db)
    with pytest.raises(DomainError) as exc:
        venta(db, **kw)
    assert codigo(exc) == cod
    assert estado_global(db) == antes


def test_stock_insuficiente_aborta_todo_incluida_la_receta(db) -> None:
    antes = estado_global(db)
    with pytest.raises(DomainError) as exc:
        venta(db, id_cliente="C006", id_farmaceutico="F002", id_receta="RC004", medio_pago="Obra social",
              items=[{"id_producto": "PRD006", "cantidad": 100}])  # hay 60 en S001
    assert codigo(exc) == STOCK_INSUFICIENTE and exc.value.details["disponible_vigente"] == 60
    assert estado_global(db) == antes


def test_stock_insuficiente_en_un_segundo_item_revierte_el_descuento_del_primero(db) -> None:
    antes = estado_global(db)
    with pytest.raises(DomainError) as exc:
        venta(db, items=[{"id_producto": "PRD001", "cantidad": 5}, {"id_producto": "PRD002", "cantidad": 1000}])
    assert codigo(exc) == STOCK_INSUFICIENTE
    assert unidades(db, "L001") == 120 and estado_global(db) == antes


def test_lotes_vencidos_no_cuentan_como_stock(db) -> None:
    # PRD003 en S001: L005 (40, vence 2026-11-30) y L015 (100, vence 2027-06-30). El 2026-12-01 L005 ya venció.
    antes = estado_global(db)
    with fixed_clock(date(2026, 12, 1)):
        with pytest.raises(DomainError) as exc:
            venta(db, id_cliente="C007", id_receta="RC006", medio_pago="Obra social",
                  items=[{"id_producto": "PRD003", "cantidad": 101}])
    assert codigo(exc) == STOCK_INSUFICIENTE and exc.value.details["disponible_vigente"] == 100
    assert estado_global(db) == antes


# ---------------------------------------------------------------- q14: idempotencia

def test_reintento_con_mismo_id_operacion_y_mismo_pedido_devuelve_la_venta(db) -> None:
    a = venta(db)
    b = venta(db)
    assert a["idempotente"] is False and b["idempotente"] is True and a["venta"]["_id"] == b["venta"]["_id"]
    assert db["ventas"].count_documents({"origen": "servicio"}) == 1 and unidades(db, "L001") == 118


def test_mismo_id_operacion_con_otro_pedido_se_rechaza(db) -> None:
    venta(db)
    with pytest.raises(DomainError) as exc:
        venta(db, items=[{"id_producto": "PRD001", "cantidad": 3}])
    assert codigo(exc) == OPERACION_CONFLICTO and exc.value.status_code == 409
    assert unidades(db, "L001") == 118


def test_el_orden_y_el_desglose_de_items_no_cambian_la_huella(db) -> None:
    venta(db, items=[{"id_producto": "PRD002", "cantidad": 1}, {"id_producto": "PRD001", "cantidad": 2}])
    r = venta(db, items=[{"id_producto": "PRD001", "cantidad": 1}, {"id_producto": "PRD001", "cantidad": 1},
                         {"id_producto": "PRD002", "cantidad": 1}])
    assert r["idempotente"] is True


# ---------------------------------------------------------------- q14: concurrencia

def _en_paralelo(funciones):
    barrera = threading.Barrier(len(funciones))

    def correr(f):
        barrera.wait()
        try:
            return ("ok", f())
        except DomainError as exc:
            return ("error", exc)

    with ThreadPoolExecutor(len(funciones)) as pool:
        return list(pool.map(correr, funciones))


def test_dos_ventas_concurrentes_nunca_dejan_stock_negativo(db) -> None:
    db["stock_lotes"].delete_many({"id_producto": "PRD001", "id_sucursal": "S001"})
    db["stock_lotes"].insert_one({"_id": "LC", "id_producto": "PRD001", "id_sucursal": "S001", "nro_lote": "C",
                                  "unidades": 10, "vencimiento": dt(2027, 6, 1)})
    res = _en_paralelo([lambda i=i: venta(db, id_operacion=f"conc-{i}", items=[{"id_producto": "PRD001", "cantidad": 6}])
                        for i in range(2)])
    assert [r[0] for r in res].count("ok") == 1
    errores = [r[1] for r in res if r[0] == "error"]
    assert len(errores) == 1 and errores[0].code == STOCK_INSUFICIENTE
    assert unidades(db, "LC") == 4 and db["ventas"].count_documents({"origen": "servicio"}) == 1


def test_mismo_id_operacion_concurrente_confirma_una_sola_venta(db) -> None:
    res = _en_paralelo([lambda: venta(db, id_operacion="misma") for _ in range(4)])
    assert all(r[0] == "ok" for r in res)
    assert sorted(r[1]["idempotente"] for r in res) == [False, True, True, True]
    assert db["ventas"].count_documents({"id_operacion": "misma"}) == 1 and unidades(db, "L001") == 118


def test_dos_ventas_concurrentes_sobre_la_misma_receta_consumen_una_sola_dispensa(db) -> None:
    res = _en_paralelo([lambda i=i: venta(db, id_operacion=f"rc-{i}", id_cliente="C007", id_farmaceutico="F006",
                                          id_receta="RC006", medio_pago="Obra social",
                                          items=[{"id_producto": "PRD004", "cantidad": 1}]) for i in range(2)])
    assert [r[0] for r in res].count("ok") == 1
    assert db["recetas"].find_one({"_id": "RC006"})["dispensas_realizadas"] == 1
    assert unidades(db, "L007") == 21


# ---------------------------------------------------------------- q15

def test_q15_descuenta_fefo_marca_y_registra_asignaciones(db) -> None:
    crear_fixture_q15(db)
    r = q15.ejecutar("V900", db=db)
    assert r["aplicado_ahora"] is True
    assert r["asignaciones"] == [{"id_producto": "PRD002", "id_lote": "LFX-1", "unidades": 2},
                                 {"id_producto": "PRD002", "id_lote": "LFX-2", "unidades": 2}]
    assert unidades(db, "LFX-1") == 0 and unidades(db, "LFX-2") == 3 and unidades(db, "L004") == 90
    assert db["ventas"].find_one({"_id": "V900"})["stock_aplicado"] is True


def test_q15_repetida_no_descuenta_dos_veces(db) -> None:
    crear_fixture_q15(db)
    q15.ejecutar("V900", db=db)
    r = q15.ejecutar("V900", db=db)
    assert r["aplicado_ahora"] is False and len(r["asignaciones"]) == 2 and unidades(db, "LFX-2") == 3


def test_q15_con_venta_historica_informa_la_limitacion_y_no_descuenta(db) -> None:
    antes = estado_global(db)
    r = q15.ejecutar("V013", db=db)  # Completada de los CSV: stock_aplicado = true, sin desglose por lote
    assert r["aplicado_ahora"] is False and r["asignaciones"] == [] and "histórico" in r["nota"]
    assert estado_global(db) == antes


def test_q15_con_venta_de_q14_devuelve_sus_asignaciones(db) -> None:
    v = venta(db)["venta"]
    r = q15.ejecutar(v["_id"], db=db)
    assert r["aplicado_ahora"] is False and r["asignaciones"] == v["asignaciones_stock"] and unidades(db, "L001") == 118


@pytest.mark.parametrize("id_venta, cod", [("V011", VALIDACION_ERROR), ("V015", VALIDACION_ERROR),  # Pendiente, Anulada
                                           ("V999", NO_ENCONTRADO), ("", VALIDACION_ERROR)])
def test_q15_rechaza_ventas_no_elegibles(db, id_venta, cod) -> None:
    with pytest.raises(DomainError) as exc:
        q15.ejecutar(id_venta, db=db)
    assert codigo(exc) == cod


def test_q15_con_stock_insuficiente_no_modifica_nada(db) -> None:
    crear_fixture_q15(db)
    db["ventas"].update_one({"_id": "V900"}, {"$set": {"items.0.cantidad": 5000}})
    lotes = sorted((l["_id"], l["unidades"]) for l in db["stock_lotes"].find())
    with pytest.raises(DomainError) as exc:
        q15.ejecutar("V900", db=db)
    assert codigo(exc) == STOCK_INSUFICIENTE
    assert db["ventas"].find_one({"_id": "V900"})["stock_aplicado"] is False
    assert sorted((l["_id"], l["unidades"]) for l in db["stock_lotes"].find()) == lotes


def test_q15_concurrente_sobre_la_misma_venta_descuenta_una_sola_vez(db) -> None:
    crear_fixture_q15(db)
    res = _en_paralelo([lambda: q15.ejecutar("V900", db=db) for _ in range(3)])
    assert all(r[0] == "ok" for r in res)
    assert sorted(r[1]["aplicado_ahora"] for r in res) == [False, False, True]
    assert unidades(db, "LFX-1") == 0 and unidades(db, "LFX-2") == 3


# ---------------------------------------------------------------- API

def test_api_ventas_y_descuento(db) -> None:
    cliente = TestClient(app)
    cuerpo = {"id_cliente": "C001", "id_farmaceutico": "F001", "medio_pago": "Efectivo", "id_operacion": "api-1",
              "items": [{"id_producto": "PRD001", "cantidad": 1}]}
    r1 = cliente.post("/api/services/ventas", json=cuerpo)
    r2 = cliente.post("/api/services/ventas", json=cuerpo)
    assert r1.status_code == 201 and r2.status_code == 200 and r2.json()["idempotente"] is True
    assert r1.json()["venta"]["fecha"] == "2026-10-13"
    malo = cliente.post("/api/services/ventas", json={**cuerpo, "id_operacion": "api-2", "id_cliente": "C008"})
    assert malo.status_code == 422 and malo.json()["error"]["code"] == CLIENTE_INACTIVO
    crear_fixture_q15(db)
    ok = cliente.post("/api/services/stock/descontar", json={"id_venta": "V900"})
    assert ok.status_code == 200 and ok.json()["aplicado_ahora"] is True
    assert cliente.get("/api/services/ventas/V900").json()["stock_aplicado"] is True
