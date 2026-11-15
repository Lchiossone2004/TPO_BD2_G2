"""q01 — Productos activos con todos los datos de su proveedor.

Motores: MongoDB + Redis (cache-aside). Consulta en MongoDB los IDs de productos
activos y resuelve cada producto y su proveedor mediante ``src.services.cache``
(claves ``producto:<id>`` y ``proveedor:<id>`` en Redis con fallback transparente
a MongoDB), sin filtrar la actividad del proveedor.
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


def ejecutar(*, db: Any = None, redis_client: Any = None) -> list[dict[str, Any]]:
    """Devuelve los productos activos ordenados por ID con todos los datos de su proveedor.

    Motores:
        MongoDB (fuente autoritativa para filtrar ``productos.activo == True`` y fallback
        ante indisponibilidad de Redis) y Redis (caché cache-aside por ID para productos
        y proveedores).

    Parámetros:
        db: base de datos MongoDB a utilizar (por defecto la compartida del proceso;
            se inyecta en las pruebas).
        redis_client: cliente Redis opcional; si no se especifica, ``src.services.cache``
            administra uno según la configuración vigente (con fallback automático a
            MongoDB si Redis no está disponible).

    Retorna:
        Lista ordenada por ``id_producto`` ascendente donde cada elemento expone
        ``id_producto`` como primera clave (junto a ``nombre``, ``principio_activo``,
        ``categoria``, ``presentacion``, ``condicion_venta``, ``precio_unit``,
        ``id_proveedor`` y ``activo``) y la clave ``proveedor`` con el detalle completo
        del proveedor asociado (sin filtrar ``proveedor.activo``) o ``None`` si no
        existiera. Si no hay productos activos devuelve ``[]``.
    """
    base = db if db is not None else get_shared_db()
    ids_productos = [
        doc["_id"]
        for doc in base["productos"].find({"activo": True}, {"_id": 1}).sort("_id", 1)
    ]
    if not ids_productos:
        return []

    productos_por_id = obtener_productos(base, ids_productos, redis_client=redis_client)
    ids_proveedores = [
        prod["id_proveedor"]
        for prod in productos_por_id.values()
        if prod.get("id_proveedor")
    ]
    proveedores_por_id = obtener_proveedores(base, ids_proveedores, redis_client=redis_client)

    resultado: list[dict[str, Any]] = []
    for id_producto in sorted(ids_productos):
        prod = productos_por_id.get(id_producto)
        if prod is None:
            continue
        prov = proveedores_por_id.get(prod.get("id_proveedor") or "")
        item = formatear_producto(prod)
        item["proveedor"] = formatear_proveedor(prov) if prov is not None else None
        resultado.append(item)
    return resultado
