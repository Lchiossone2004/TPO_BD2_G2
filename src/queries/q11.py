"""q11 — Ingresos totales por farmacéutico en el mes calendario actual.

Motor: MongoDB. Agrega ``ventas`` en estado ``Completada`` dentro del mes
calendario de ``hoy()`` y resuelve ``ventas.id_farmaceutico`` →
``farmaceuticos._id`` mediante ``$lookup``, sin filtrar por actividad.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from src.clock import date_to_bson, hoy
from src.infrastructure.mongo import get_shared_db


def ventana(fecha_hoy: date) -> tuple[date, date]:
    """Calcula la ventana mensual semiabierta ``[desde, hasta_exclusivo)``.

    Motor: independiente (lógica de calendario previa a la consulta MongoDB).

    Parámetros:
        fecha_hoy: fecha calendario de referencia para determinar el mes actual.

    Retorna ``(desde, hasta_exclusivo)`` donde ``desde`` es el primer día del mes de
    ``fecha_hoy`` y ``hasta_exclusivo`` es el primer día del mes siguiente (cruzando de
    diciembre a enero del año siguiente cuando corresponda).
    """
    desde = fecha_hoy.replace(day=1)
    if fecha_hoy.month == 12:
        hasta_exclusivo = date(fecha_hoy.year + 1, 1, 1)
    else:
        hasta_exclusivo = date(fecha_hoy.year, fecha_hoy.month + 1, 1)
    return desde, hasta_exclusivo


def pipeline(desde: date, hasta_exclusivo: date) -> list[dict[str, Any]]:
    """Construye el pipeline de agregación de q11 sobre ``ventas``.

    Motor: MongoDB (colecciones ``ventas`` y ``farmaceuticos``).

    Parámetros:
        desde: primer día del mes calendario actual (incluido).
        hasta_exclusivo: primer día del mes calendario siguiente (excluido).

    Retorna las etapas de agregación que filtran ventas ``Completada`` en
    ``[desde, hasta_exclusivo)``, suman ingresos y cantidad de ventas por
    farmacéutico, enriquecen con ``farmaceuticos`` (incluyendo inactivos) y
    ordenan por ``ingresos_totales`` descendente e ``id_farmaceutico`` ascendente.
    """
    return [
        {
            "$match": {
                "estado": "Completada",
                "fecha": {"$gte": date_to_bson(desde), "$lt": date_to_bson(hasta_exclusivo)},
            }
        },
        {
            "$group": {
                "_id": "$id_farmaceutico",
                "ingresos_totales": {"$sum": "$total"},
                "cantidad_ventas": {"$sum": 1},
            }
        },
        {
            "$lookup": {
                "from": "farmaceuticos",
                "localField": "_id",
                "foreignField": "_id",
                "as": "farmaceutico",
            }
        },
        {"$unwind": "$farmaceutico"},
        {
            "$replaceWith": {
                "id_farmaceutico": "$_id",
                "nombre": "$farmaceutico.nombre",
                "apellido": "$farmaceutico.apellido",
                "matricula": "$farmaceutico.matricula",
                "id_sucursal": "$farmaceutico.id_sucursal",
                "activo": "$farmaceutico.activo",
                "ingresos_totales": "$ingresos_totales",
                "cantidad_ventas": "$cantidad_ventas",
            }
        },
        {"$sort": {"ingresos_totales": -1, "id_farmaceutico": 1}},
    ]


def ejecutar(*, db: Any = None) -> list[dict[str, Any]]:
    """Devuelve los ingresos totales por farmacéutico en el mes calendario actual.

    Motor: MongoDB.

    Parámetros:
        db: base de datos MongoDB (por defecto la compartida; se inyecta en los tests).

    Retorna una lista de ``{id_farmaceutico, nombre, apellido, matricula, id_sucursal,
    activo, ingresos_totales, cantidad_ventas}`` ordenada por ``ingresos_totales``
    descendente e ``id_farmaceutico`` ascendente en caso de empate. Considera solo
    ventas ``Completada`` del mes calendario de ``hoy()`` (calculada una sola vez por
    ejecución) e incluye farmacéuticos inactivos. Si no hay ventas completadas en el
    mes, devuelve ``[]``.
    """
    base = db if db is not None else get_shared_db()
    desde, hasta_exclusivo = ventana(hoy())
    return list(base["ventas"].aggregate(pipeline(desde, hasta_exclusivo)))
