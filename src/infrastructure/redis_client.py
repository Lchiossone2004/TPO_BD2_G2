"""Cliente y diagnóstico de salud tolerante a fallos para Redis (caché)."""

from __future__ import annotations

from typing import Any

from src.infrastructure.config import get_settings

try:
    import redis
    from redis.exceptions import RedisError
except ImportError:  # pragma: no cover - permite importar módulos base sin redis instalado
    redis = None  # type: ignore[assignment]

    class RedisError(Exception):
        """Fallback de excepción cuando el paquete `redis` no está instalado."""


_MSG_OK = "Caché activa (cache-aside para productos y proveedores)"
_MSG_DEGRADED = "Redis no disponible; consultas operan con fallback directo a MongoDB"


def get_redis_client(url: str | None = None) -> redis.Redis:
    """Crea un cliente `redis.Redis` con timeouts acotados y decodificación UTF-8."""
    if redis is None:
        raise RuntimeError("El paquete 'redis' no está instalado; instala requirements.txt.")

    resolved_url = url or get_settings().redis_url
    return redis.Redis.from_url(
        resolved_url,
        decode_responses=True,
        socket_connect_timeout=1.0,
        socket_timeout=1.0,
    )


def check_redis_health() -> dict[str, Any]:
    """Verifica conectividad con Redis y cuenta las claves del prefijo configurado."""
    settings = get_settings()
    client: Any = None

    try:
        client = get_redis_client(url=settings.redis_url)
        if not client.ping():
            raise ConnectionError("Redis ping devolvió False")

        pattern = f"{settings.redis_prefix}*"
        cached_keys_count = sum(1 for _ in client.scan_iter(match=pattern, count=100))

        return {
            "status": "ok",
            "engine": "redis",
            "available": True,
            "ttl_seconds": settings.redis_ttl_seconds,
            "prefix": settings.redis_prefix,
            "cached_keys_count": cached_keys_count,
            "message": _MSG_OK,
            "error": None,
        }
    except (RedisError, Exception) as exc:
        return {
            "status": "degraded",
            "engine": "redis",
            "available": False,
            "ttl_seconds": settings.redis_ttl_seconds,
            "prefix": settings.redis_prefix,
            "cached_keys_count": 0,
            "message": _MSG_DEGRADED,
            "error": str(exc),
        }
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


__all__ = ["check_redis_health", "get_redis_client"]
