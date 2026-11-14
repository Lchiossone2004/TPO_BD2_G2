"""q02 — Ventas 'Pendiente' con el farmacéutico asignado (nombre, matrícula y sucursal) y el total.

Motor: MongoDB (agregación sobre ``ventas`` con ``$lookup`` a ``farmaceuticos`` y ``sucursales``).
"""

from __future__ import annotations

from typing import Any

from src.infrastructure.mongo import get_shared_db


def pipeline() -> list[dict[str, Any]]:
    return [
        {"$match": {"estado": "Pendiente"}},
        {
            "$lookup": {
                "from": "farmaceuticos",
                "localField": "id_farmaceutico",
                "foreignField": "_id",
                "as": "farmaceutico",
            }
        },
        {"$unwind": "$farmaceutico"},
        {
            "$lookup": {
                "from": "sucursales",
                "localField": "farmaceutico.id_sucursal",
                "foreignField": "_id",
                "as": "sucursal",
            }
        },
        {"$unwind": "$sucursal"},
        # $replaceWith conserva el orden declarado de los campos (un $project lo reordena).
        {
            "$replaceWith": {
                "id_venta": "$_id",
                "fecha": "$fecha",
                "total": "$total",
                "farmaceutico": {
                    "id_farmaceutico": "$farmaceutico._id",
                    "nombre": "$farmaceutico.nombre",
                    "apellido": "$farmaceutico.apellido",
                    "matricula": "$farmaceutico.matricula",
                },
                "sucursal": {
                    "id_sucursal": "$sucursal._id",
                    "nombre": "$sucursal.nombre",
                },
            }
        },
        {"$sort": {"fecha": 1, "id_venta": 1}},
    ]


def ejecutar(*, db: Any = None) -> list[dict[str, Any]]:
    """Devuelve las ventas pendientes con el farmacéutico asignado y su sucursal.

    Parámetros:
        db: base de datos MongoDB a usar (por defecto la compartida del proceso; se inyecta en los tests).

    Retorna una lista de ``{id_venta, fecha, total, farmaceutico{...}, sucursal{...}}`` ordenada
    por fecha e ID. Las pendientes no descuentan stock ni computan ingresos, pero se listan igual.
    """
    base = db if db is not None else get_shared_db()
    return list(base["ventas"].aggregate(pipeline()))
