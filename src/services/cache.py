"""Servicio compartido de caché cache-aside en Redis para productos y proveedores."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import Any

from src.infrastructure.config import get_settings
from src.infrastructure.redis_client import RedisError, get_redis_client
from src.services.serialization import a_json

logger = logging.getLogger(__name__)


def clave_producto(id_producto: str, prefix: str | None = None) -> str:
    """Construye la clave Redis para un documento de producto."""
    prefijo = get_settings().redis_prefix if prefix is None else prefix
    return f"{prefijo}producto:{id_producto}"


def clave_proveedor(id_proveedor: str, prefix: str | None = None) -> str:
    """Construye la clave Redis para un documento de proveedor."""
    prefijo = get_settings().redis_prefix if prefix is None else prefix
    return f"{prefijo}proveedor:{id_proveedor}"


def formatear_producto(doc: dict[str, Any]) -> dict[str, Any]:
    """Formatea un documento de producto exponiendo ``id_producto`` como primera clave."""
    return {
        "id_producto": doc["_id"],
        "nombre": doc["nombre"],
        "principio_activo": doc["principio_activo"],
        "categoria": doc["categoria"],
        "presentacion": doc["presentacion"],
        "condicion_venta": doc["condicion_venta"],
        "precio_unit": doc["precio_unit"],
        "id_proveedor": doc["id_proveedor"],
        "activo": doc["activo"],
    }


def formatear_proveedor(doc: dict[str, Any]) -> dict[str, Any]:
    """Formatea un documento de proveedor exponiendo ``id_proveedor`` como primera clave."""
    return {
        "id_proveedor": doc["_id"],
        "razon_social": doc["razon_social"],
        "cuit": doc["cuit"],
        "tipo": doc["tipo"],
        "ciudad": doc["ciudad"],
        "provincia": doc["provincia"],
        "telefono": doc["telefono"],
        "activo": doc["activo"],
    }


def _consultar_mongo_por_lotes(db: Any, coleccion: str, ids: list[str]) -> dict[str, dict[str, Any]]:
    """Lee en una sola consulta los documentos de ``coleccion`` cuyos ``_id`` estén en ``ids``."""
    if not ids:
        return {}
    return {doc["_id"]: doc for doc in db[coleccion].find({"_id": {"$in": ids}})}


def _poblar_redis(
    client: Any,
    claves_por_id: dict[str, str],
    docs: dict[str, dict[str, Any]],
    ttl_seconds: int,
) -> None:
    """Guarda en Redis los documentos obtenidos de MongoDB en una sola tubería con TTL."""
    if not docs:
        return
    try:
        pipe = client.pipeline()
        for item_id, doc in docs.items():
            payload = json.dumps(a_json(doc), ensure_ascii=False)
            pipe.set(claves_por_id[item_id], payload, ex=ttl_seconds)
        pipe.execute()
    except (RedisError, OSError, Exception) as exc:
        logger.warning("No se pudo poblar la caché Redis (%s); se continúa sin bloquear.", exc)


def _obtener_por_lotes(
    db: Any,
    coleccion: str,
    tipo_clave: str,
    ids: Sequence[str],
    *,
    redis_client: Any = None,
) -> dict[str, dict[str, Any]]:
    """Resuelve entidades por ID usando cache-aside en Redis con fallback transparente a MongoDB."""
    ids_unicos = sorted({str(item_id).strip() for item_id in ids if item_id and str(item_id).strip()})
    if not ids_unicos:
        return {}

    settings = get_settings()
    claves_por_id = {
        item_id: f"{settings.redis_prefix}{tipo_clave}:{item_id}" for item_id in ids_unicos
    }

    own_client = redis_client is None
    client = redis_client
    resultado: dict[str, dict[str, Any]] = {}
    faltantes: list[str] = []

    try:
        if client is None:
            client = get_redis_client(url=settings.redis_url)
        valores = client.mget([claves_por_id[item_id] for item_id in ids_unicos])
        for item_id, raw in zip(ids_unicos, valores):
            if raw is None:
                faltantes.append(item_id)
                continue
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict) and "_id" in parsed:
                    resultado[item_id] = parsed
                else:
                    faltantes.append(item_id)
            except (json.JSONDecodeError, TypeError) as exc:
                logger.warning("Entrada corrupta en caché Redis para %s (%s); se recarga desde MongoDB.", claves_por_id[item_id], exc)
                faltantes.append(item_id)
    except (RedisError, OSError, Exception) as exc:
        logger.warning("Redis no disponible en lectura cache-aside (%s); fallback directo a MongoDB.", exc)
        if own_client and client is not None:
            try:
                client.close()
            except Exception:
                pass
        return _consultar_mongo_por_lotes(db, coleccion, ids_unicos)

    try:
        if faltantes:
            desde_mongo = _consultar_mongo_por_lotes(db, coleccion, faltantes)
            resultado.update(desde_mongo)
            _poblar_redis(client, claves_por_id, desde_mongo, settings.redis_ttl_seconds)
    finally:
        if own_client and client is not None:
            try:
                client.close()
            except Exception:
                pass

    return resultado


def obtener_productos(
    db: Any,
    ids_producto: Sequence[str],
    *,
    redis_client: Any = None,
) -> dict[str, dict[str, Any]]:
    """Resuelve productos por ID con caché cache-aside en Redis y fallback a MongoDB."""
    return _obtener_por_lotes(db, "productos", "producto", ids_producto, redis_client=redis_client)


def obtener_proveedores(
    db: Any,
    ids_proveedor: Sequence[str],
    *,
    redis_client: Any = None,
) -> dict[str, dict[str, Any]]:
    """Resuelve proveedores por ID con caché cache-aside en Redis y fallback a MongoDB."""
    return _obtener_por_lotes(db, "proveedores", "proveedor", ids_proveedor, redis_client=redis_client)


__all__ = [
    "clave_producto",
    "clave_proveedor",
    "formatear_producto",
    "formatear_proveedor",
    "obtener_productos",
    "obtener_proveedores",
]
