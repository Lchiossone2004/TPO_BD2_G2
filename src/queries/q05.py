"""q05 — Farmacéuticos activos y cantidad de ventas de los últimos 60 días (sin anuladas).

Motor: MongoDB. Se parte de ``farmaceuticos`` (activo = true) y se hace ``$lookup`` con
sub-pipeline hacia ``ventas``, de modo que los farmacéuticos sin ventas aparezcan con 0.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from src.clock import date_to_bson, hoy
from src.infrastructure.mongo import get_shared_db

DIAS_VENTANA = 60


def ventana(fecha_hoy: date) -> tuple[date, date]:
    """Ventana [hoy - 60 días, hoy], ambos extremos incluidos (sin fechas futuras)."""
    return fecha_hoy - timedelta(days=DIAS_VENTANA), fecha_hoy


def pipeline(desde: date, hasta: date) -> list[dict[str, Any]]:
    """Pipeline de agregación de q05 para la ventana ``[desde, hasta]``."""
    return [
        {"$match": {"activo": True}},
        {
            "$lookup": {
                "from": "ventas",
                "let": {"id_farmaceutico": "$_id"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {"$eq": ["$id_farmaceutico", "$$id_farmaceutico"]},
                            "estado": {"$ne": "Anulada"},
                            "fecha": {"$gte": date_to_bson(desde), "$lte": date_to_bson(hasta)},
                        }
                    },
                    {"$project": {"_id": 1}},
                ],
                "as": "ventas",
            }
        },
        {
            "$replaceWith": {
                "id_farmaceutico": "$_id",
                "nombre": "$nombre",
                "apellido": "$apellido",
                "matricula": "$matricula",
                "id_sucursal": "$id_sucursal",
                "cantidad_ventas": {"$size": "$ventas"},
            }
        },
        {"$sort": {"cantidad_ventas": -1, "id_farmaceutico": 1}},
    ]


def ejecutar(*, db: Any = None) -> list[dict[str, Any]]:
    """Devuelve cada farmacéutico activo con su cantidad de ventas en los últimos 60 días.

    Parámetros:
        db: base de datos MongoDB (por defecto la compartida; se inyecta en los tests).

    Retorna una lista de ``{id_farmaceutico, nombre, apellido, matricula, id_sucursal,
    cantidad_ventas}`` ordenada por cantidad descendente e ID. Cuenta ventas Completadas y
    Pendientes (excluye Anuladas) y siempre incluye a los activos con 0. La fecha de referencia
    sale de ``hoy()``, calculada una sola vez por ejecución.
    """
    base = db if db is not None else get_shared_db()
    desde, hasta = ventana(hoy())
    return list(base["farmaceuticos"].aggregate(pipeline(desde, hasta)))
