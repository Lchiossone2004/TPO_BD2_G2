"""q10 — Clientes distintos atendidos en una sucursal determinada.

Motor: MongoDB. Parte de ``farmaceuticos`` filtrados por ``id_sucursal`` (sin filtrar
``activo``), une ``ventas`` por ``id_farmaceutico`` (sin filtrar estado de venta), agrupa
los clientes distintos y resuelve sus datos desde ``clientes`` (sin filtrar actividad).
"""

from __future__ import annotations

from typing import Any

from src.infrastructure.mongo import get_shared_db
from src.services.exceptions import NO_ENCONTRADO, VALIDACION_ERROR, DomainError


def pipeline(id_sucursal: str) -> list[dict[str, Any]]:
    """Construye el pipeline de agregación de q10 sobre ``farmaceuticos`` en MongoDB.

    Parámetros:
        id_sucursal: ID normalizado de la sucursal a consultar (ej. ``"S002"``).

    Retorna la secuencia de etapas de agregación que obtiene los clientes distintos
    atendidos por farmacéuticos de la sucursal (activos o inactivos) y en cualquier
    estado de venta, ordenados por ``id_cliente`` ascendente.
    """
    return [
        {"$match": {"id_sucursal": id_sucursal}},
        {
            "$lookup": {
                "from": "ventas",
                "localField": "_id",
                "foreignField": "id_farmaceutico",
                "as": "ventas",
            }
        },
        {"$unwind": "$ventas"},
        {"$group": {"_id": "$ventas.id_cliente"}},
        {
            "$lookup": {
                "from": "clientes",
                "localField": "_id",
                "foreignField": "_id",
                "as": "cliente",
            }
        },
        {"$unwind": "$cliente"},
        {
            "$replaceWith": {
                "id_cliente": "$cliente._id",
                "nombre": "$cliente.nombre",
                "apellido": "$cliente.apellido",
                "dni": "$cliente.dni",
                "email": "$cliente.email",
                "telefono": "$cliente.telefono",
                "ciudad": "$cliente.ciudad",
                "provincia": "$cliente.provincia",
                "obra_social": "$cliente.obra_social",
                "nro_afiliado": "$cliente.nro_afiliado",
                "activo": "$cliente.activo",
            }
        },
        {"$sort": {"id_cliente": 1}},
    ]


def ejecutar(id_sucursal: str | None = None, *, db: Any = None) -> list[dict[str, Any]]:
    """Devuelve todos los clientes distintos atendidos en la sucursal indicada.

    Motor: MongoDB (agregación sobre ``farmaceuticos`` con ``$lookup`` a ``ventas`` y ``clientes``).

    Parámetros:
        id_sucursal: ID de la sucursal (ej. ``"S002"``). Obligatorio y no vacío.
        db: base de datos MongoDB (por defecto la compartida del proceso; se inyecta en tests).

    Retorna una lista de diccionarios con los datos del cliente (``id_cliente`` como primera
    clave), ordenada ascendentemente por ``id_cliente`` y sin duplicados. Incluye clientes
    inactivos, ventas en cualquier estado (``Completada``, ``Pendiente``, ``Anulada``) y
    ventas registradas por farmacéuticos inactivos. Si la sucursal existe pero no registra
    ventas, retorna ``[]``.

    Errores:
        DomainError(VALIDACION_ERROR, 400): si ``id_sucursal`` falta, es ``None`` o queda vacío.
        DomainError(NO_ENCONTRADO, 404): si no existe ninguna sucursal con ese ``_id``.
    """
    id_sucursal = (id_sucursal or "").strip()
    if not id_sucursal:
        raise DomainError(
            VALIDACION_ERROR,
            "La consulta requiere id_sucursal.",
            400,
            {"campo": "id_sucursal"},
        )
    base = db if db is not None else get_shared_db()
    if base["sucursales"].find_one({"_id": id_sucursal}) is None:
        raise DomainError(
            NO_ENCONTRADO,
            f"No existe la sucursal {id_sucursal}.",
            404,
            {"id_sucursal": id_sucursal},
        )
    return list(base["farmaceuticos"].aggregate(pipeline(id_sucursal)))
