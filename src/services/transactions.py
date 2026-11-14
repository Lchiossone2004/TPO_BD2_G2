"""Ayudas comunes para ejecutar callbacks dentro de una transacción de MongoDB"""

from __future__ import annotations

from typing import Any, Callable

from pymongo import MongoClient


def ejecutar_en_transaccion(client: MongoClient, callback: Callable[[Any], Any]) -> Any:
    """Ejecuta ``callback(session)`` con ``with_transaction``"""
    with client.start_session() as session:
        return session.with_transaction(callback)
