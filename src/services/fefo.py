"""Asignación y descuento de stock FEFO sobre ``stock_lotes``"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.services.exceptions import STOCK_INSUFICIENTE, DomainError


def agrupar_cantidades(items: list[dict[str, Any]]) -> dict[str, int]:
    """Suma las cantidades de productos repetidos: ``{id_producto: cantidad_total}``."""
    total: dict[str, int] = {}
    for item in items:
        total[item["id_producto"]] = total.get(item["id_producto"], 0) + int(item["cantidad"])
    return total


def descontar_fefo(
    db: Any,
    session: Any,
    id_sucursal: str,
    requeridos: dict[str, int],
    hoy_bson: datetime,
) -> list[dict[str, Any]]:
    """Descuenta ``requeridos`` de los lotes vigentes de la sucursal y devuelve las asignaciones.

    Lotes elegibles: ``unidades > 0`` y ``vencimiento >= hoy`` (los vencidos se omiten), en orden
    ``(vencimiento, _id)``. Cada descuento es un ``update_one`` condicional ``unidades >= tomar``.
    Si algún producto no alcanza se lanza ``STOCK_INSUFICIENTE``; la transacción llamadora se aborta
    y no queda ningún descuento parcial.
    """
    lotes = db["stock_lotes"]
    asignaciones: list[dict[str, Any]] = []
    for id_producto in sorted(requeridos):  # orden fijo: evita bloqueos cruzados entre pedidos
        pendiente = requeridos[id_producto]
        disponible = 0
        cursor = lotes.find(
            {"id_producto": id_producto, "id_sucursal": id_sucursal,
             "unidades": {"$gt": 0}, "vencimiento": {"$gte": hoy_bson}},
            session=session,
        ).sort([("vencimiento", 1), ("_id", 1)])
        for lote in cursor:
            disponible += lote["unidades"]
            tomar = min(pendiente, lote["unidades"])
            resultado = lotes.update_one(
                {"_id": lote["_id"], "unidades": {"$gte": tomar}},
                {"$inc": {"unidades": -tomar}},
                session=session,
            )
            if resultado.modified_count != 1:  # otro pedido tomó stock de este lote
                raise DomainError(
                    STOCK_INSUFICIENTE, f"El lote {lote['_id']} cambió durante la operación.", 409,
                    {"id_producto": id_producto, "id_lote": lote["_id"]},
                )
            asignaciones.append({"id_producto": id_producto, "id_lote": lote["_id"], "unidades": tomar})
            pendiente -= tomar
            if pendiente == 0:
                break
        if pendiente > 0:
            raise DomainError(
                STOCK_INSUFICIENTE,
                f"Stock vigente insuficiente de {id_producto} en la sucursal {id_sucursal}.",
                409,
                {"id_producto": id_producto, "id_sucursal": id_sucursal,
                 "requerido": requeridos[id_producto], "disponible_vigente": disponible},
            )
    return asignaciones
