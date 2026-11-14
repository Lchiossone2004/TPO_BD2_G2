"""Interfaz de línea de comandos (CLI) para FarmaRed S.A.

Provee diagnóstico de conectividad (`--health`), listado del catálogo Q1–Q15 (`--list`)
y punto de entrada para ejecutar consultas y servicios (`--query <qXX>`).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from src.clock import AR_TZ, format_iso_date, hoy
from src.infrastructure.mongo import check_mongo_health
from src.infrastructure.redis_client import check_redis_health
from src.queries import EJECUTORES
from src.queries.catalog import QUERIES_CATALOG, get_query_metadata
from src.services.exceptions import NO_IMPLEMENTADO, VALIDACION_ERROR, DomainError
from src.services.serialization import a_json


def build_parser() -> argparse.ArgumentParser:
    """Construye el parser de argumentos CLI."""
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="CLI de gestión y consultas para FarmaRed S.A. (MongoDB + Redis).",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--health",
        action="store_true",
        help="Verifica conectividad con MongoDB y Redis y muestra la fecha de negocio en JSON.",
    )
    group.add_argument(
        "--list",
        action="store_true",
        help="Lista las 15 consultas y servicios (Q1–Q15) registrados en el catálogo.",
    )
    group.add_argument(
        "--query",
        metavar="qXX",
        help="Ejecuta o informa el estado de la consulta o servicio indicado (ej. q01).",
    )
    parser.add_argument(
        "--param",
        action="append",
        default=[],
        metavar="clave=valor",
        help="Parámetro de la consulta (repetible), ej. --param accion=alta --param dni=30111222.",
    )
    return parser


def _handle_health() -> int:
    mongo_health = check_mongo_health()
    redis_health = check_redis_health()
    mongo_ok = mongo_health.get("status") == "ok"

    payload = {
        "status": "ok" if mongo_ok else "error",
        "business_date": format_iso_date(hoy()),
        "timezone": str(AR_TZ),
        "mongodb": mongo_health,
        "redis": redis_health,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if mongo_ok else 1


def _handle_list() -> int:
    print("Catálogo de consultas y servicios FarmaRed S.A. (Q1–Q15):\n")
    for item in QUERIES_CATALOG:
        engines = ", ".join(item["engines"])
        params = ", ".join(item["parameters"]) if item["parameters"] else "sin parámetros"
        status_label = "implementada" if item["implemented"] else "pendiente (Fase 3)"
        print(
            f"- {item['id']} (Q{item['number']:02d}) | {item['type']:10s} | "
            f"{item['method']:4s} {item['endpoint']} | Motores: [{engines}] | "
            f"{item['title']} | Parámetros: {params} | Estado: {status_label}"
        )
    return 0


def _handle_query(query_id: str, raw_params: Sequence[str] = ()) -> int:
    meta = get_query_metadata(query_id)
    if meta is None:
        print(
            f"Error: consulta '{query_id}' desconocida. Usa --list para ver Q1–Q15.",
            file=sys.stderr,
        )
        return 1

    if not meta.get("implemented", False):
        err = DomainError(
            code=NO_IMPLEMENTADO,
            message=(
                f"La consulta {meta['id']} ({meta['title']}) aún no está implementada "
                "en esta etapa base (corresponde a la Fase 3 del plan)."
            ),
            status_code=501,
            details={
                "id": meta["id"],
                "endpoint": meta["endpoint"],
                "method": meta["method"],
                "engines": meta["engines"],
                "parameters": meta["parameters"],
            },
        )
        print(json.dumps(err.to_dict(), indent=2, ensure_ascii=False))
        return 0

    executor = EJECUTORES.get(meta["id"])
    if executor is None:
        print(json.dumps(DomainError(NO_IMPLEMENTADO, f"{meta['id']} no tiene ejecutor registrado.", 501).to_dict(),
                         indent=2, ensure_ascii=False))
        return 1
    try:
        params = dict(item.split("=", 1) for item in raw_params)
        result = executor(**params)
    except (ValueError, TypeError) as exc:
        err = DomainError(VALIDACION_ERROR, f"Parámetros inválidos ({exc}). Parámetros válidos: "
                          f"{', '.join(meta['parameters']) or 'ninguno'}; formato clave=valor.", 400)
        print(json.dumps(err.to_dict(), indent=2, ensure_ascii=False))
        return 1
    except DomainError as err:
        print(json.dumps(err.to_dict(), indent=2, ensure_ascii=False))
        return 1
    print(json.dumps(a_json(result), indent=2, ensure_ascii=False))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Punto de entrada principal de la CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.health:
        return _handle_health()
    if args.list:
        return _handle_list()
    if args.query:
        return _handle_query(args.query, args.param)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
