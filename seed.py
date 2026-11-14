"""Script base de verificación y preparación de carga idempotente (`seed.py`).

Etapa actual (Fase 1 / base):
- Verifica la existencia y cantidad de filas de los 9 CSV originales en `data/originales/`.
- Inspecciona si existen CSV adicionales en `data/adicionales/`.
- Verifica la conectividad con MongoDB (Replica Set `rs0`) y Redis (tolerando Redis caído).

La carga completa idempotente (reset de base/prefijo, validación integral de tipos y
reglas, creación de índices y población de `contadores`) corresponde a la Fase 2 del plan.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any, Sequence

from src.infrastructure.mongo import check_mongo_health
from src.infrastructure.redis_client import check_redis_health

PROJECT_ROOT = Path(__file__).resolve().parent

EXPECTED_CSV_FILES: tuple[str, ...] = (
    "clientes.csv",
    "sucursales.csv",
    "farmaceuticos.csv",
    "proveedores.csv",
    "productos.csv",
    "stock_lotes.csv",
    "recetas.csv",
    "ventas.csv",
    "detalle_ventas.csv",
)


def inspect_csv_directory(directory: Path) -> dict[str, dict[str, Any]]:
    """Inspecciona los 9 CSV esperados en `directory` y cuenta sus filas de datos."""
    results: dict[str, dict[str, Any]] = {}
    for filename in EXPECTED_CSV_FILES:
        file_path = directory / filename
        if not file_path.is_file():
            results[filename] = {
                "exists": False,
                "path": str(file_path),
                "rows": 0,
                "columns": [],
            }
            continue

        with file_path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            columns = list(reader.fieldnames or [])
            rows = sum(1 for _ in reader)

        results[filename] = {
            "exists": True,
            "path": str(file_path),
            "rows": rows,
            "columns": columns,
        }
    return results


def build_parser() -> argparse.ArgumentParser:
    """Construye el parser de argumentos CLI de `seed.py`."""
    parser = argparse.ArgumentParser(
        prog="seed.py",
        description=(
            "Verificación base de datasets CSV y conectividad con MongoDB/Redis. "
            "La carga completa idempotente se implementa en la Fase 2 del plan."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verifica los 9 CSV originales y la conectividad con MongoDB (rs0) y Redis.",
    )
    parser.add_argument(
        "--dir-originales",
        type=Path,
        default=PROJECT_ROOT / "data" / "originales",
        help="Directorio de los 9 CSV originales (default: data/originales).",
    )
    parser.add_argument(
        "--dir-adicionales",
        type=Path,
        default=PROJECT_ROOT / "data" / "adicionales",
        help="Directorio de los 9 CSV adicionales (default: data/adicionales).",
    )
    return parser


def _print_csv_summary(label: str, directory: Path, stats: dict[str, dict[str, Any]]) -> bool:
    print(f"=== Datasets {label} ({directory}) ===")
    all_exist = True
    total_rows = 0
    for filename, info in stats.items():
        if info["exists"]:
            total_rows += info["rows"]
            print(f"  [OK]    {filename:20s} -> {info['rows']:4d} filas ({len(info['columns'])} cols)")
        else:
            all_exist = False
            print(f"  [FALTA] {filename:20s} -> no encontrado")
    print(f"  Total filas ({label}): {total_rows}\n")
    return all_exist


def run_check(dir_originales: Path, dir_adicionales: Path) -> int:
    """Ejecuta la verificación completa de CSV y conectividad con MongoDB y Redis."""
    orig_stats = inspect_csv_directory(dir_originales)
    all_orig_ok = _print_csv_summary("originales", dir_originales, orig_stats)

    adic_stats = inspect_csv_directory(dir_adicionales)
    adic_present = sum(1 for info in adic_stats.values() if info["exists"])
    if adic_present > 0:
        _print_csv_summary("adicionales", dir_adicionales, adic_stats)
    else:
        print(
            f"=== Datasets adicionales ({dir_adicionales}) ===\n"
            "  [INFO] Sin archivos adicionales todavía (corresponden a la Fase 2 del plan).\n"
        )

    mongo = check_mongo_health()
    print("=== Conectividad MongoDB ===")
    if mongo["status"] == "ok":
        rs_name = mongo.get("replica_set")
        primary = mongo.get("is_writable_primary")
        print(
            f"  [OK]    Base '{mongo['database']}' accesible | "
            f"replica_set={rs_name} | is_writable_primary={primary} | "
            f"colecciones={mongo['collection_count']}"
        )
        if rs_name != "rs0":
            print(
                f"  [AVISO] Se esperaba replica_set='rs0' para transacciones ACID, "
                f"se detectó {rs_name!r}."
            )
    else:
        print(f"  [ERROR] MongoDB no disponible: {mongo.get('error')}")

    redis_health = check_redis_health()
    print("\n=== Conectividad Redis ===")
    if redis_health["status"] == "ok":
        print(
            f"  [OK]    Redis disponible | prefix='{redis_health['prefix']}' | "
            f"claves={redis_health['cached_keys_count']}"
        )
    else:
        print(
            f"  [AVISO] Redis no disponible (tolerado): {redis_health['message']} "
            f"({redis_health.get('error')})"
        )

    print(
        "\nNota: la carga completa idempotente (validaciones, índices, contadores e "
        "invalidación de caché) corresponde a la Fase 2 de plan.md."
    )

    if not all_orig_ok or mongo["status"] != "ok":
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Punto de entrada principal de `seed.py`."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.check:
        return run_check(args.dir_originales, args.dir_adicionales)

    orig_stats = inspect_csv_directory(args.dir_originales)
    all_orig_ok = _print_csv_summary("originales", args.dir_originales, orig_stats)
    print(
        "Nota: este script es el esqueleto base (Fase 1). La carga completa idempotente "
        "de datasets originales + adicionales corresponde a la Fase 2 de plan.md.\n"
        "Ejecuta `python3 seed.py --check` para verificar también conectividad con MongoDB y Redis."
    )
    return 0 if all_orig_ok else 1


if __name__ == "__main__":
    sys.exit(main())
