"""q04 — Clientes con más de una receta registrada, indicando la cantidad.

Motor: MongoDB. Se agrupan las recetas por cliente y se resuelve la referencia
``recetas.id_cliente`` → ``clientes._id`` mediante ``$lookup``.
"""

from __future__ import annotations

from typing import Any

from src.infrastructure.mongo import get_shared_db


def pipeline() -> list[dict[str, Any]]:
    """Agrupa recetas por cliente, conserva cantidades mayores a uno y agrega sus datos."""
    return [
        {"$group": {"_id": "$id_cliente", "cantidad_recetas": {"$sum": 1}}},
        {"$match": {"cantidad_recetas": {"$gt": 1}}},
        {
            "$lookup": {
                "from": "clientes",
                "localField": "_id",
                "foreignField": "_id",
                "as": "cliente",
            }
        },
        {"$unwind": "$cliente"},
        # Como en q02/q05/q12, $replaceWith define la forma y el orden de los campos.
        {
            "$replaceWith": {
                "id_cliente": "$_id",
                "nombre": "$cliente.nombre",
                "apellido": "$cliente.apellido",
                "dni": "$cliente.dni",
                "email": "$cliente.email",
                "telefono": "$cliente.telefono",
                "obra_social": "$cliente.obra_social",
                "activo": "$cliente.activo",
                "cantidad_recetas": "$cantidad_recetas",
            }
        },
        {"$sort": {"cantidad_recetas": -1, "id_cliente": 1}},
    ]


def ejecutar(*, db: Any = None) -> list[dict[str, Any]]:
    """Devuelve los clientes con más de una receta, contando todos los estados.

    Parámetros:
        db: base MongoDB (por defecto la compartida del proceso; se inyecta en los tests).

    Retorna una lista de ``{id_cliente, nombre, apellido, dni, email, telefono,
    obra_social, activo, cantidad_recetas}``, ordenada por cantidad descendente
    e ID de cliente en los empates. Incluye clientes inactivos y recetas Vigentes,
    Completadas y Vencidas. Cada receta cuenta una vez, no por sus dispensas.
    Sin clientes que cumplan la condición devuelve ``[]``. Es una consulta de
    solo lectura, sin parámetros de negocio ni dependencia de la fecha actual.
    """
    base = db if db is not None else get_shared_db()
    return list(base["recetas"].aggregate(pipeline()))
