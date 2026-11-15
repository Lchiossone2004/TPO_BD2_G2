"""q09 — Ventas libres con total menor a $5.000, excluyendo anuladas.

Motor: MongoDB. Consulta sobre ``ventas`` con sus ``items`` embebidos,
sin cruces con otras colecciones.
"""

from __future__ import annotations

from typing import Any

from src.infrastructure.mongo import get_shared_db


def pipeline() -> list[dict[str, Any]]:
    """Filtra las ventas libres de bajo importe y prepara los datos de la venta."""
    return [
        {
            "$match": {
                "tipo": "Venta libre",
                "total": {"$lt": 5000},
                "estado": {"$ne": "Anulada"},
            }
        },
        {
            "$replaceWith": {
                "id_venta": "$_id",
                "id_cliente": "$id_cliente",
                "id_farmaceutico": "$id_farmaceutico",
                "id_receta": "$id_receta",
                "fecha": "$fecha",
                "tipo": "$tipo",
                "medio_pago": "$medio_pago",
                "total": "$total",
                "estado": "$estado",
                "items": "$items",
            }
        },
        {"$sort": {"fecha": 1, "id_venta": 1}},
    ]


def ejecutar(*, db: Any = None) -> list[dict[str, Any]]:
    """Devuelve ventas de tipo Venta libre con total estrictamente menor a 5000 ARS.

    Parámetros:
        db: base MongoDB (por defecto la compartida del proceso; se inyecta en los tests).

    Retorna una lista de ``{id_venta, id_cliente, id_farmaceutico, id_receta,
    fecha, tipo, medio_pago, total, estado, items}``, ordenada por fecha e ID.
    Incluye Completadas y Pendientes; excluye Anuladas y ventas Con receta.
    Una venta de exactamente $5.000 queda excluida. Se usa el total registrado
    y los precios históricos de sus ítems, sin consultar el catálogo actual.
    No filtra por fecha ni actividad de otras entidades. Sin coincidencias
    devuelve ``[]``. Solo lectura, sin parámetros de negocio.
    """
    base = db if db is not None else get_shared_db()
    return list(base["ventas"].aggregate(pipeline()))
