"""q12 — Clientes sin ventas registradas en el último año.

Motor: MongoDB. Se parte de ``clientes`` y se hace ``$lookup`` con sub-pipeline hacia ``ventas`` en la
ventana [hoy - 1 año, hoy]; quedan los clientes cuyo resultado es vacío (anti-join). Cualquier venta
registrada cuenta como actividad (Completada, Pendiente o Anulada).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from src.clock import date_to_bson, hoy
from src.infrastructure.mongo import get_shared_db


def ventana(fecha_hoy: date) -> tuple[date, date]:
    """Ventana [mismo día del año anterior, hoy], ambos incluidos (29/02 → 28/02 si no existe)."""
    try:
        desde = fecha_hoy.replace(year=fecha_hoy.year - 1)
    except ValueError:  # hoy es 29 de febrero y el año anterior no es bisiesto
        desde = fecha_hoy.replace(year=fecha_hoy.year - 1, day=28)
    return desde, fecha_hoy


def pipeline(desde: date, hasta: date) -> list[dict[str, Any]]:
    """Pipeline de q12: anti-join clientes → ventas dentro de ``[desde, hasta]``."""
    return [
        {
            "$lookup": {
                "from": "ventas",
                "let": {"id_cliente": "$_id"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {"$eq": ["$id_cliente", "$$id_cliente"]},
                            "fecha": {"$gte": date_to_bson(desde), "$lte": date_to_bson(hasta)},
                        }
                    },
                    {"$limit": 1},  # alcanza con saber que existe al menos una
                    {"$project": {"_id": 1}},
                ],
                "as": "ventas_recientes",
            }
        },
        {"$match": {"ventas_recientes": {"$size": 0}}},
        {
            "$replaceWith": {
                "id_cliente": "$_id",
                "nombre": "$nombre",
                "apellido": "$apellido",
                "dni": "$dni",
                "email": "$email",
                "telefono": "$telefono",
                "obra_social": "$obra_social",
                "activo": "$activo",
            }
        },
        {"$sort": {"id_cliente": 1}},
    ]


def ejecutar(*, db: Any = None) -> list[dict[str, Any]]:
    """Devuelve los clientes sin ninguna venta registrada en el último año.

    Parámetros:
        db: base de datos MongoDB (por defecto la compartida; se inyecta en los tests).

    Retorna una lista de ``{id_cliente, nombre, apellido, dni, email, telefono, obra_social, activo}``
    ordenada por ID. Incluye también clientes dados de baja (campo ``activo``), porque el enunciado
    no filtra por actividad. La fecha de referencia sale de ``hoy()``, una sola vez por ejecución.
    """
    base = db if db is not None else get_shared_db()
    desde, hasta = ventana(hoy())
    return list(base["clientes"].aggregate(pipeline(desde, hasta)))
