"""q14 — Registro de venta integrada: venta + receta + descuento FEFO en una única transacción MongoDB."""

from __future__ import annotations

import hashlib
import json
import re
import sys
import uuid
from datetime import timedelta
from typing import Any

from pymongo import ReturnDocument
from pymongo.errors import ConnectionFailure, DuplicateKeyError, ExecutionTimeout, PyMongoError, WTimeoutError

from src.clock import bson_to_date, date_to_bson, hoy
from src.infrastructure.mongo import get_shared_db
from src.services.exceptions import (
    CLIENTE_INACTIVO,
    FARMACEUTICO_INVALIDO,
    NO_ENCONTRADO,
    OPERACION_CONFLICTO,
    PRODUCTO_INACTIVO,
    RECETA_INVALIDA,
    RECETA_VENCIDA,
    RESULTADO_POR_VERIFICAR,
    VALIDACION_ERROR,
    DomainError,
)
from src.services.fefo import agrupar_cantidades, descontar_fefo
from src.services.transactions import ejecutar_en_transaccion

MEDIOS_PAGO = ("Efectivo", "Débito", "Crédito", "Transferencia", "Obra social")
DIAS_PROLONGADA = 30


def _error(mensaje: str, **detalles: Any) -> DomainError:
    return DomainError(VALIDACION_ERROR, mensaje, 400, detalles or None)


def _normalizar_items(items: Any) -> list[dict[str, Any]]:
    """Acepta lista de dicts, JSON o ``PRD001:2,PRD002:1`` (CLI) y valida cantidades enteras positivas."""
    if isinstance(items, str):
        texto = items.strip()
        if texto.startswith("["):
            try:
                items = json.loads(texto)
            except json.JSONDecodeError as exc:
                raise _error("items no es un JSON válido.", detalle=str(exc)) from exc
        else:
            items = [{"id_producto": p.split(":")[0], "cantidad": p.split(":")[1] if ":" in p else "1"}
                     for p in texto.split(",") if p.strip()]
    if not isinstance(items, list) or not items:
        raise _error("La venta debe tener al menos un ítem.", campo="items")
    normalizados = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise _error("Cada ítem debe ser un objeto {id_producto, cantidad}.", indice=i)
        id_producto = str(item.get("id_producto") or "").strip()
        cantidad = item.get("cantidad")
        if isinstance(cantidad, str) and re.fullmatch(r"\d+", cantidad.strip()):
            cantidad = int(cantidad.strip())
        if not id_producto:
            raise _error("Falta id_producto en un ítem.", indice=i)
        if isinstance(cantidad, bool) or not isinstance(cantidad, int) or cantidad <= 0:
            raise _error("La cantidad debe ser un entero positivo.", indice=i, id_producto=id_producto)
        normalizados.append({"id_producto": id_producto, "cantidad": cantidad})
    return normalizados


def calcular_huella(id_cliente: str, id_farmaceutico: str, id_receta: str | None, medio_pago: str,
                    requeridos: dict[str, int]) -> str:
    """SHA-256 de los argumentos normalizados (productos agrupados y ordenados)."""
    canon = {"id_cliente": id_cliente, "id_farmaceutico": id_farmaceutico, "id_receta": id_receta,
             "medio_pago": medio_pago, "items": sorted(requeridos.items())}
    return hashlib.sha256(json.dumps(canon, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _replica(venta: dict[str, Any], huella: str) -> dict[str, Any]:
    """Resultado para un pedido repetido: devuelve la venta ya confirmada o rechaza si el pedido cambió."""
    if venta.get("huella_solicitud") != huella:
        raise DomainError(
            OPERACION_CONFLICTO,
            "El id_operacion ya se usó con un pedido distinto; use otro id_operacion para un pedido nuevo.",
            409, {"id_operacion": venta.get("id_operacion"), "id_venta": venta["_id"]},
        )
    return {"venta": venta, "idempotente": True, "receta_antes": None, "receta_despues": None}


def _nuevo_estado_receta(receta: dict[str, Any], fecha_venta: Any) -> dict[str, Any]:
    realizadas = receta["dispensas_realizadas"] + 1
    if receta["tipo"] == "Tratamiento prolongado" and realizadas < receta["dispensas_autorizadas"]:
        proxima = date_to_bson(bson_to_date(fecha_venta) + timedelta(days=DIAS_PROLONGADA))
        return {"dispensas_realizadas": realizadas, "proxima_dispensa": proxima, "estado": "Vigente"}
    return {"dispensas_realizadas": realizadas, "proxima_dispensa": None, "estado": "Completada"}


def ejecutar(
    id_cliente: str | None = None,
    id_farmaceutico: str | None = None,
    id_receta: str | None = None,
    medio_pago: str | None = None,
    items: Any = None,
    id_operacion: str | None = None,
    *,
    db: Any = None,
) -> dict[str, Any]:
    """Registra una venta Completada validando, descontando stock FEFO y actualizando la receta, todo o nada."""
    id_cliente = (id_cliente or "").strip()
    id_farmaceutico = (id_farmaceutico or "").strip()
    id_receta = (id_receta or "").strip() or None
    medio_pago = (medio_pago or "").strip()
    faltan = [n for n, v in (("id_cliente", id_cliente), ("id_farmaceutico", id_farmaceutico),
                             ("medio_pago", medio_pago)) if not v]
    if faltan:
        raise _error("Faltan datos obligatorios.", campos=faltan)
    if medio_pago not in MEDIOS_PAGO:
        raise _error("medio_pago inválido.", validos=list(MEDIOS_PAGO))
    requeridos = agrupar_cantidades(_normalizar_items(items))
    generado = not (id_operacion or "").strip()
    id_operacion = str(uuid.uuid4()) if generado else id_operacion.strip()
    if generado:
        print(f"id_operacion generado: {id_operacion} (reutilícelo para reintentar el mismo pedido)", file=sys.stderr)
    huella = calcular_huella(id_cliente, id_farmaceutico, id_receta, medio_pago, requeridos)

    base = db if db is not None else get_shared_db()
    fecha = date_to_bson(hoy())

    def operacion(session: Any) -> dict[str, Any]:
        # El callback puede repetirse (with_transaction): solo lee/escribe con la sesión, sin efectos externos.
        previa = base["ventas"].find_one({"id_operacion": id_operacion}, session=session)
        if previa is not None:
            return _replica(previa, huella)

        cliente = base["clientes"].find_one({"_id": id_cliente}, session=session)
        if cliente is None:
            raise DomainError(NO_ENCONTRADO, f"No existe el cliente {id_cliente}.", 404, {"id_cliente": id_cliente})
        if not cliente["activo"]:
            raise DomainError(CLIENTE_INACTIVO, f"El cliente {id_cliente} está inactivo.", 422, {"id_cliente": id_cliente})

        farmaceutico = base["farmaceuticos"].find_one({"_id": id_farmaceutico}, session=session)
        if farmaceutico is None:
            raise DomainError(NO_ENCONTRADO, f"No existe el farmacéutico {id_farmaceutico}.", 404,
                              {"id_farmaceutico": id_farmaceutico})
        sucursal = base["sucursales"].find_one({"_id": farmaceutico["id_sucursal"]}, session=session)
        if not farmaceutico["activo"] or sucursal is None or sucursal["tipo"] != "Farmacia":
            raise DomainError(
                FARMACEUTICO_INVALIDO,
                f"El farmacéutico {id_farmaceutico} debe estar activo y pertenecer a una sucursal tipo Farmacia.",
                422, {"id_farmaceutico": id_farmaceutico, "activo": farmaceutico["activo"],
                      "tipo_sucursal": sucursal["tipo"] if sucursal else None},
            )

        productos = {p["_id"]: p for p in base["productos"].find({"_id": {"$in": list(requeridos)}}, session=session)}
        for id_producto in sorted(requeridos):
            if id_producto not in productos:
                raise DomainError(NO_ENCONTRADO, f"No existe el producto {id_producto}.", 404, {"id_producto": id_producto})
            if not productos[id_producto]["activo"]:
                raise DomainError(PRODUCTO_INACTIVO, f"El producto {id_producto} está inactivo.", 422,
                                  {"id_producto": id_producto})

        con_receta = [p for p in requeridos if productos[p]["condicion_venta"] != "Venta libre"]
        receta = None
        if con_receta and not id_receta:
            raise DomainError(RECETA_INVALIDA, "La venta incluye productos bajo receta: se requiere id_receta.", 422,
                              {"productos_bajo_receta": con_receta})
        if id_receta:
            if not con_receta:
                raise DomainError(RECETA_INVALIDA, "Se informó una receta pero ningún producto la requiere.", 422,
                                  {"id_receta": id_receta})
            receta = base["recetas"].find_one({"_id": id_receta}, session=session)
            if receta is None:
                raise DomainError(NO_ENCONTRADO, f"No existe la receta {id_receta}.", 404, {"id_receta": id_receta})
            if receta["id_cliente"] != id_cliente:
                raise DomainError(RECETA_INVALIDA, "La receta pertenece a otro cliente.", 422,
                                  {"id_receta": id_receta, "id_cliente": id_cliente})
            if receta["estado"] == "Vencida":
                raise DomainError(RECETA_VENCIDA, f"La receta {id_receta} está vencida.", 422, {"id_receta": id_receta})
            if receta["estado"] != "Vigente" or receta["dispensas_realizadas"] >= receta["dispensas_autorizadas"]:
                raise DomainError(RECETA_INVALIDA, f"La receta {id_receta} no tiene dispensas disponibles.", 422,
                                  {"id_receta": id_receta, "estado": receta["estado"]})

        # IDs desde contadores: si la transacción aborta, el $inc se revierte y no quedan huecos.
        c_venta = base["contadores"].find_one_and_update(
            {"_id": "venta"}, {"$inc": {"valor": 1}}, return_document=ReturnDocument.AFTER, session=session)
        c_detalle = base["contadores"].find_one_and_update(
            {"_id": "detalle"}, {"$inc": {"valor": len(requeridos)}}, return_document=ReturnDocument.AFTER,
            session=session)
        id_venta = f"V{c_venta['valor']:03d}"
        primero = c_detalle["valor"] - len(requeridos) + 1

        asignaciones = descontar_fefo(base, session, farmaceutico["id_sucursal"], requeridos, fecha)

        receta_despues = None
        if receta is not None:
            nuevo = _nuevo_estado_receta(receta, fecha)
            actualizada = base["recetas"].update_one(
                {"_id": id_receta, "id_cliente": id_cliente, "estado": "Vigente",
                 "dispensas_realizadas": receta["dispensas_realizadas"]},
                {"$set": nuevo}, session=session)
            if actualizada.modified_count != 1:
                raise DomainError(RECETA_INVALIDA, f"La receta {id_receta} cambió durante la operación.", 409,
                                  {"id_receta": id_receta})
            receta_despues = {**receta, **nuevo}

        detalle = [
            {"id_detalle": f"D{primero + i:03d}", "id_producto": p, "nombre_producto": productos[p]["nombre"],
             "cantidad": requeridos[p], "precio_unit": productos[p]["precio_unit"]}
            for i, p in enumerate(sorted(requeridos))
        ]
        venta = {
            "_id": id_venta, "id_cliente": id_cliente, "id_farmaceutico": id_farmaceutico, "id_receta": id_receta,
            "fecha": fecha, "tipo": "Con receta" if con_receta else "Venta libre", "medio_pago": medio_pago,
            "total": sum(d["cantidad"] * d["precio_unit"] for d in detalle), "estado": "Completada",
            "origen": "servicio", "id_operacion": id_operacion, "huella_solicitud": huella,
            "stock_aplicado": True, "asignaciones_stock": asignaciones, "items": detalle,
        }
        base["ventas"].insert_one(venta, session=session)
        return {"venta": venta, "idempotente": False, "receta_antes": receta, "receta_despues": receta_despues}

    def buscar_confirmada() -> dict[str, Any] | None:
        return base["ventas"].find_one({"id_operacion": id_operacion})

    try:
        resultado = ejecutar_en_transaccion(base.client, operacion)
    except DuplicateKeyError:
        # Otro pedido con el mismo id_operacion confirmó primero: se compara la huella.
        confirmada = buscar_confirmada()
        if confirmada is None:
            raise
        resultado = _replica(confirmada, huella)
    except PyMongoError as exc:
        # Commit incierto / timeout: se resuelve por id_operacion, sin crear otra venta ni compensar a mano.
        incierto = isinstance(exc, (ConnectionFailure, ExecutionTimeout, WTimeoutError)) or exc.has_error_label(
            "UnknownTransactionCommitResult")
        if not incierto:
            raise  # otros errores del motor (p. ej. validador) no son un resultado incierto
        try:
            confirmada = buscar_confirmada()
        except PyMongoError:
            confirmada = None
        if confirmada is None:
            raise DomainError(
                RESULTADO_POR_VERIFICAR,
                "No se pudo confirmar el resultado. Consulte o reintente con el mismo id_operacion.",
                503, {"id_operacion": id_operacion, "causa": type(exc).__name__},
            ) from exc
        resultado = _replica(confirmada, huella)
    resultado["id_operacion"] = id_operacion
    resultado["id_operacion_generado"] = generado
    return resultado
