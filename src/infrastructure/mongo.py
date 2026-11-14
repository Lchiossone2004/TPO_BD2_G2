"""Cliente y diagnóstico de salud para MongoDB (Replica Set)."""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Any

from src.infrastructure.config import get_settings

try:
    from pymongo import MongoClient
except ImportError:  # pragma: no cover - permite importar módulos base sin pymongo instalado
    MongoClient = None  # type: ignore[assignment,misc]

if TYPE_CHECKING:
    from pymongo.database import Database


def get_mongo_client(
    uri: str | None = None,
    server_selection_timeout_ms: int = 3000,
) -> MongoClient:
    """Crea un `MongoClient` configurado con `tz_aware=True`."""
    if MongoClient is None:
        raise RuntimeError("El paquete 'pymongo' no está instalado; instala requirements.txt.")

    resolved_uri = uri or get_settings().mongodb_uri
    return MongoClient(
        resolved_uri,
        tz_aware=True,
        serverSelectionTimeoutMS=server_selection_timeout_ms,
    )


def get_db(client: MongoClient | None = None, db_name: str | None = None) -> Database:
    """Obtiene la referencia a la base de datos MongoDB configurada."""
    resolved_client = client if client is not None else get_mongo_client()
    resolved_db_name = db_name or get_settings().mongodb_db
    return resolved_client[resolved_db_name]


@lru_cache(maxsize=1)
def get_shared_client() -> MongoClient:
    """Cliente único del proceso (API, CLI): evita abrir una conexión por pedido."""
    return get_mongo_client()


def get_shared_db() -> Database:
    """Base de datos configurada usando el cliente compartido del proceso."""
    return get_db(client=get_shared_client())


def check_mongo_health() -> dict[str, Any]:
    """Ejecuta `ping` y `hello` sobre MongoDB y devuelve un dict JSON-serializable."""
    settings = get_settings()
    db_name = settings.mongodb_db
    client: MongoClient | None = None

    try:
        client = get_mongo_client(
            uri=settings.mongodb_uri,
            server_selection_timeout_ms=2000,
        )
        admin = client.admin
        admin.command("ping")
        hello = admin.command("hello")
        db = get_db(client=client, db_name=db_name)
        collections = sorted(db.list_collection_names())

        return {
            "status": "ok",
            "engine": "mongodb",
            "database": db_name,
            "replica_set": hello.get("setName"),
            "is_writable_primary": bool(hello.get("isWritablePrimary", False)),
            "hosts": list(hello.get("hosts", [])),
            "collections": collections,
            "collection_count": len(collections),
            "error": None,
        }
    except Exception as exc:
        return {
            "status": "error",
            "engine": "mongodb",
            "database": db_name,
            "replica_set": None,
            "is_writable_primary": False,
            "hosts": [],
            "collections": [],
            "collection_count": 0,
            "error": str(exc),
        }
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


__all__ = ["check_mongo_health", "get_db", "get_mongo_client", "get_shared_client", "get_shared_db"]
