"""q06 — Recetas prolongadas Vigentes con próxima dispensa anterior a hoy.

Motor: MongoDB. Se filtra ``recetas`` y se resuelve la referencia
``recetas.id_cliente`` → ``clientes._id`` mediante ``$lookup``.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from src.clock import date_to_bson, hoy
from src.infrastructure.mongo import get_shared_db


def pipeline(fecha_hoy: date) -> list[dict[str, Any]]:
    """Filtra las dispensas atrasadas y agrega los datos del cliente."""
    return [
        {
            "$match": {
                "tipo": "Tratamiento prolongado",
                "estado": "Vigente",
                "proxima_dispensa": {"$ne": None, "$lt": date_to_bson(fecha_hoy)},
            }
        },
        {
            "$lookup": {
                "from": "clientes",
                "localField": "id_cliente",
                "foreignField": "_id",
                "as": "cliente",
            }
        },
        {"$unwind": "$cliente"},
        {
            "$replaceWith": {
                "id_receta": "$_id",
                "id_cliente": "$id_cliente",
                "medico": "$medico",
                "matricula_medico": "$matricula_medico",
                "fecha_emision": "$fecha_emision",
                "tipo": "$tipo",
                "dispensas_autorizadas": "$dispensas_autorizadas",
                "dispensas_realizadas": "$dispensas_realizadas",
                "proxima_dispensa": "$proxima_dispensa",
                "estado": "$estado",
                "cliente": {
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
                },
            }
        },
        {"$sort": {"proxima_dispensa": 1, "id_receta": 1}},
    ]


def ejecutar(*, db: Any = None) -> list[dict[str, Any]]:
    """Devuelve recetas prolongadas Vigentes con la próxima dispensa atrasada.

    Parámetros:
        db: base MongoDB (por defecto la compartida del proceso; se inyecta en los tests).

    Retorna una lista con los datos de la receta y ``cliente`` anidado, ordenada
    por próxima dispensa ascendente e ID de receta en los empates. Incluye
    clientes inactivos: el enunciado no filtra por actividad. Excluye próximas
    dispensas nulas, futuras o de hoy, recetas Simples/Archivadas y recetas
    Completadas/Vencidas. Sin coincidencias devuelve ``[]``.

    ``hoy()`` se calcula una sola vez, en Buenos Aires, y se convierte a BSON
    Date con el helper compartido. Solo consulta: no vence recetas ni modifica
    dispensas. No recibe parámetros de negocio.
    """
    base = db if db is not None else get_shared_db()
    return list(base["recetas"].aggregate(pipeline(hoy())))
