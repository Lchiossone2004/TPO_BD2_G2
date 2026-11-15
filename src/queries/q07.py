"""q07 — Top 5 de productos más vendidos por unidades, solo ventas Completadas.

Motor: MongoDB. Se agregan los ``items`` embebidos en ``ventas`` y se resuelve
``items.id_producto`` → ``productos._id`` mediante ``$lookup``.
"""

from __future__ import annotations

from typing import Any

from src.infrastructure.mongo import get_shared_db


def pipeline() -> list[dict[str, Any]]:
    """Suma unidades por producto y obtiene los primeros cinco con sus nombres."""
    return [
        {"$match": {"estado": "Completada"}},
        {"$unwind": "$items"},
        {"$group": {"_id": "$items.id_producto", "unidades_vendidas": {"$sum": "$items.cantidad"}}},
        {"$sort": {"unidades_vendidas": -1, "_id": 1}},
        {"$limit": 5},
        {
            "$lookup": {
                "from": "productos",
                "localField": "_id",
                "foreignField": "_id",
                "as": "producto",
            }
        },
        {"$unwind": "$producto"},
        {
            "$replaceWith": {
                "id_producto": "$_id",
                "nombre": "$producto.nombre",
                "unidades_vendidas": "$unidades_vendidas",
            }
        },
        {"$sort": {"unidades_vendidas": -1, "id_producto": 1}},
    ]


def ejecutar(*, db: Any = None) -> list[dict[str, Any]]:
    """Devuelve hasta cinco productos ordenados por unidades vendidas descendentes.

    Parámetros:
        db: base MongoDB (por defecto la compartida del proceso; se inyecta en los tests).

    Retorna una lista de ``{id_producto, nombre, unidades_vendidas}``, con ID
    ascendente como desempate. Suma cantidades de todos los ítems de ventas
    Completadas, incluso si un producto aparece varias veces en la misma venta.
    Excluye ventas Pendientes y Anuladas. No filtra productos por actividad ni
    ventas por fecha: se considera todo el historial de ventas completadas.
    Con menos de cinco productos devuelve los disponibles; sin ventas
    completadas devuelve ``[]``. Solo lectura, sin parámetros de negocio.
    """
    base = db if db is not None else get_shared_db()
    return list(base["ventas"].aggregate(pipeline()))
