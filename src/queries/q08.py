"""q08 — Lotes con menos de 50 unidades enriquecidos con producto, sucursal y proveedor.

Motores: MongoDB + Redis. Se consultan en MongoDB ``stock_lotes`` (``unidades < 50``,
incluyendo cero y lotes vencidos) y ``sucursales`` en lote; ``productos`` y
``proveedores`` se resuelven mediante caché cache-aside en Redis con fallback
transparente a MongoDB, sin filtrar por actividad de ninguna entidad.
"""

from __future__ import annotations

from typing import Any

from src.infrastructure.mongo import get_shared_db
from src.services.cache import (
    formatear_producto,
    formatear_proveedor,
    obtener_productos,
    obtener_proveedores,
)

UMBRAL_UNIDADES = 50


def _formatear_sucursal(doc: dict[str, Any]) -> dict[str, Any]:
    """Formatea un documento de sucursal exponiendo ``id_sucursal`` como primera clave."""
    return {
        "id_sucursal": doc["_id"],
        "nombre": doc["nombre"],
        "tipo": doc["tipo"],
        "direccion": doc["direccion"],
        "ciudad": doc["ciudad"],
        "provincia": doc["provincia"],
        "telefono": doc["telefono"],
        "activo": doc["activo"],
    }


def _formatear_lote(
    lote: dict[str, Any],
    producto: dict[str, Any],
    sucursal: dict[str, Any],
    proveedor: dict[str, Any],
) -> dict[str, Any]:
    """Combina un lote de stock con su producto, sucursal y proveedor formateados."""
    return {
        "id_lote": lote["_id"],
        "nro_lote": lote["nro_lote"],
        "unidades": lote["unidades"],
        "vencimiento": lote["vencimiento"],
        "id_producto": lote["id_producto"],
        "id_sucursal": lote["id_sucursal"],
        "producto": formatear_producto(producto),
        "sucursal": _formatear_sucursal(sucursal),
        "proveedor": formatear_proveedor(proveedor),
    }


def ejecutar(*, db: Any = None, redis_client: Any = None) -> list[dict[str, Any]]:
    """Devuelve los lotes con menos de 50 unidades junto con producto, sucursal y proveedor.

    Motores:
        - MongoDB: lectura de ``stock_lotes`` (``unidades < 50``) y resolución en lote de ``sucursales``.
        - Redis (cache-aside con fallback a MongoDB): resolución de ``productos`` y ``proveedores``.

    Parámetros:
        db: base de datos MongoDB a consultar (por defecto la compartida del proceso).
        redis_client: cliente Redis opcional inyectado (si es ``None``, se obtiene por configuración).

    Retorna:
        Lista de diccionarios ``{id_lote, nro_lote, unidades, vencimiento, id_producto,
        id_sucursal, producto, sucursal, proveedor}`` ordenada por ``unidades`` ascendente e
        ``id_lote`` ascendente. Incluye lotes con ``0`` unidades, lotes vencidos y entidades
        inactivas (producto, proveedor o sucursal). Sin coincidencias devuelve ``[]``.
    """
    base = db if db is not None else get_shared_db()
    lotes = list(
        base["stock_lotes"]
        .find({"unidades": {"$lt": UMBRAL_UNIDADES}})
        .sort([("unidades", 1), ("_id", 1)])
    )
    if not lotes:
        return []

    ids_sucursal = sorted({lote["id_sucursal"] for lote in lotes})
    sucursales = {
        suc["_id"]: suc
        for suc in base["sucursales"].find({"_id": {"$in": ids_sucursal}})
    }
    productos = obtener_productos(
        base,
        [lote["id_producto"] for lote in lotes],
        redis_client=redis_client,
    )
    proveedores = obtener_proveedores(
        base,
        [prod["id_proveedor"] for prod in productos.values()],
        redis_client=redis_client,
    )

    resultado: list[dict[str, Any]] = []
    for lote in lotes:
        prod = productos[lote["id_producto"]]
        suc = sucursales[lote["id_sucursal"]]
        prov = proveedores[prod["id_proveedor"]]
        resultado.append(_formatear_lote(lote, prod, suc, prov))
    return resultado
