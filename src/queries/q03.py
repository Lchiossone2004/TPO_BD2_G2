"""q03 — Historial completo de un cliente: ventas y recetas en una única línea de tiempo.

Motor: MongoDB. Se parte de ``ventas`` (con sus ítems embebidos) y se une ``recetas`` con
``$unionWith``; ambas se normalizan a la forma ``{fecha, tipo, id, detalle}`` y se ordenan juntas.
"""

from __future__ import annotations

from typing import Any

from src.infrastructure.mongo import get_shared_db
from src.services.exceptions import NO_ENCONTRADO, VALIDACION_ERROR, DomainError


def pipeline(id_cliente: str) -> list[dict[str, Any]]:
    """Pipeline de q03: ventas del cliente + recetas del cliente (``$unionWith``), ordenadas."""
    return [
        {"$match": {"id_cliente": id_cliente}},
        {
            "$replaceWith": {
                "fecha": "$fecha",
                "tipo": "venta",
                "id": "$_id",
                "detalle": {
                    "estado": "$estado",
                    "tipo_venta": "$tipo",
                    "medio_pago": "$medio_pago",
                    "total": "$total",
                    "id_farmaceutico": "$id_farmaceutico",
                    "id_receta": "$id_receta",
                    "items": "$items",
                },
            }
        },
        {
            "$unionWith": {
                "coll": "recetas",
                "pipeline": [
                    {"$match": {"id_cliente": id_cliente}},
                    {
                        "$replaceWith": {
                            "fecha": "$fecha_emision",
                            "tipo": "receta",
                            "id": "$_id",
                            "detalle": {
                                "estado": "$estado",
                                "tipo_receta": "$tipo",
                                "medico": "$medico",
                                "matricula_medico": "$matricula_medico",
                                "dispensas_autorizadas": "$dispensas_autorizadas",
                                "dispensas_realizadas": "$dispensas_realizadas",
                                "proxima_dispensa": "$proxima_dispensa",
                            },
                        }
                    },
                ],
            }
        },
        # Desempate en la misma fecha: tipo (receta antes que venta) y luego ID.
        {"$sort": {"fecha": 1, "tipo": 1, "id": 1}},
    ]


def ejecutar(id_cliente: str | None = None, *, db: Any = None) -> dict[str, Any]:
    """Devuelve el historial cronológico (ventas y recetas) del cliente indicado.

    Parámetros:
        id_cliente: ID del cliente (ej. ``C001``). Obligatorio. Se acepta también un cliente dado de baja.
        db: base de datos MongoDB (por defecto la compartida; se inyecta en los tests).

    Retorna ``{"cliente": {...}, "historial": [{fecha, tipo, id, detalle}, ...]}`` con ``tipo`` igual a
    ``"venta"`` o ``"receta"``, ordenado por fecha, tipo e ID. Incluye ventas en cualquier estado.
    Errores: ``VALIDACION_ERROR`` si falta ``id_cliente`` y ``NO_ENCONTRADO`` si el cliente no existe.
    """
    id_cliente = (id_cliente or "").strip()
    if not id_cliente:
        raise DomainError(VALIDACION_ERROR, "La consulta requiere id_cliente.", 400, {"campo": "id_cliente"})
    base = db if db is not None else get_shared_db()
    cliente = base["clientes"].find_one({"_id": id_cliente})
    if cliente is None:
        raise DomainError(NO_ENCONTRADO, f"No existe el cliente {id_cliente}.", 404, {"id_cliente": id_cliente})
    historial = list(base["ventas"].aggregate(pipeline(id_cliente)))
    return {"cliente": cliente, "historial": historial}
