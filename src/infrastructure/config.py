"""Configuración por variables de entorno para MongoDB y Redis."""

from __future__ import annotations

import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - fallback cuando python-dotenv aún no está instalado
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()

DEFAULT_MONGODB_URI = "mongodb://localhost:27017/?replicaSet=rs0&directConnection=true"
DEFAULT_MONGODB_DB = "farmared"
DEFAULT_REDIS_URL = "redis://localhost:6379/0"
DEFAULT_REDIS_TTL_SECONDS = 300
DEFAULT_REDIS_PREFIX = "farmared:"


@dataclass(frozen=True)
class Settings:
    """Parámetros de conexión y caché leídos desde variables de entorno."""

    mongodb_uri: str = DEFAULT_MONGODB_URI
    mongodb_db: str = DEFAULT_MONGODB_DB
    redis_url: str = DEFAULT_REDIS_URL
    redis_ttl_seconds: int = DEFAULT_REDIS_TTL_SECONDS
    redis_prefix: str = DEFAULT_REDIS_PREFIX


def get_settings() -> Settings:
    """Lee el entorno actualizado en cada llamada y construye `Settings`."""
    ttl_raw = os.getenv("REDIS_TTL_SECONDS", "").strip()
    ttl_seconds = int(ttl_raw) if ttl_raw else DEFAULT_REDIS_TTL_SECONDS

    return Settings(
        mongodb_uri=os.getenv("MONGODB_URI") or DEFAULT_MONGODB_URI,
        mongodb_db=os.getenv("MONGODB_DB") or DEFAULT_MONGODB_DB,
        redis_url=os.getenv("REDIS_URL") or DEFAULT_REDIS_URL,
        redis_ttl_seconds=ttl_seconds,
        redis_prefix=os.getenv("REDIS_PREFIX") or DEFAULT_REDIS_PREFIX,
    )


__all__ = [
    "DEFAULT_MONGODB_DB",
    "DEFAULT_MONGODB_URI",
    "DEFAULT_REDIS_PREFIX",
    "DEFAULT_REDIS_TTL_SECONDS",
    "DEFAULT_REDIS_URL",
    "Settings",
    "get_settings",
]
