"""Carga reproducible e idempotente de FarmaRed (`seed.py`).

Uso:
    python seed.py                          # genera adicionales (fecha base = hoy), valida y carga
    python seed.py --base-date 2026-10-13
    python seed.py --original-only          # solo los 9 CSV originales (pruebas con reloj fijo)
    python seed.py --dry-run                # valida sin tocar MongoDB ni Redis
    python seed.py --check                  # diagnóstico de CSV y conectividad
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from pathlib import Path
from typing import Any, Sequence

from src.loading import extra_data
from src.loading.mongo_schema import INDICES, VALIDADORES
from src.loading.validation import DATASETS, leer_directorio, maximos_contadores, validar_y_transformar
from src.clock import hoy
from src.infrastructure.mongo import check_mongo_health, get_db, get_mongo_client
from src.infrastructure.redis_client import check_redis_health, get_redis_client
from src.infrastructure.config import get_settings

PROJECT_ROOT = Path(__file__).resolve().parent
EXPECTED_CSV_FILES: tuple[str, ...] = tuple(f"{d}.csv" for d in DATASETS)
COLECCIONES = ("clientes", "sucursales", "farmaceuticos", "proveedores", "productos",
               "stock_lotes", "recetas", "ventas", "contadores")


def inspect_csv_directory(directory: Path) -> dict[str, dict[str, Any]]:
    """Inspecciona los 9 CSV esperados en `directory` y cuenta sus filas de datos."""
    results: dict[str, dict[str, Any]] = {}
    for filename in EXPECTED_CSV_FILES:
        file_path = directory / filename
        if not file_path.is_file():
            results[filename] = {"exists": False, "path": str(file_path), "rows": 0, "columns": []}
            continue
        with file_path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            columns = list(reader.fieldnames or [])
            rows = sum(1 for _ in reader)
        results[filename] = {"exists": True, "path": str(file_path), "rows": rows, "columns": columns}
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="seed.py", description="Carga idempotente de FarmaRed en MongoDB y Redis.")
    parser.add_argument("--check", action="store_true", help="Verifica los CSV y la conectividad con MongoDB (rs0) y Redis.")
    parser.add_argument("--dry-run", action="store_true", help="Genera y valida todo, pero no toca MongoDB ni Redis.")
    parser.add_argument("--original-only", action="store_true", help="Carga solo los 9 CSV originales (sin adicionales).")
    parser.add_argument("--base-date", type=date.fromisoformat, default=None, metavar="AAAA-MM-DD",
                        help="Fecha base de los escenarios relativos (default: hoy en Argentina).")
    parser.add_argument("--original-dir", type=Path, default=PROJECT_ROOT / "data" / "original")
    parser.add_argument("--additional-dir", type=Path, default=PROJECT_ROOT / "data" / "additional")
    return parser


def _print_csv_summary(label: str, directory: Path, stats: dict[str, dict[str, Any]]) -> bool:
    print(f"=== Datasets {label} ({directory}) ===")
    all_exist, total = True, 0
    for filename, info in stats.items():
        if info["exists"]:
            total += info["rows"]
            print(f"  [OK]    {filename:20s} -> {info['rows']:4d} filas ({len(info['columns'])} cols)")
        else:
            all_exist = False
            print(f"  [FALTA] {filename:20s} -> no encontrado")
    print(f"  Total filas ({label}): {total}\n")
    return all_exist


def run_check(dir_originales: Path, dir_adicionales: Path) -> int:
    """Diagnóstico: CSV presentes y conectividad con MongoDB y Redis (no modifica nada)."""
    all_orig_ok = _print_csv_summary("originales", dir_originales, inspect_csv_directory(dir_originales))
    adic = inspect_csv_directory(dir_adicionales)
    if any(i["exists"] for i in adic.values()):
        _print_csv_summary("adicionales", dir_adicionales, adic)
    else:
        print(f"=== Datasets adicionales ({dir_adicionales}) ===\n  [INFO] Aún no generados: se crean al correr `python seed.py`.\n")
    mongo = check_mongo_health()
    print("=== Conectividad MongoDB ===")
    if mongo["status"] == "ok":
        print(f"  [OK]    Base '{mongo['database']}' | replica_set={mongo.get('replica_set')} | "
              f"primary={mongo.get('is_writable_primary')} | colecciones={mongo['collection_count']}")
    else:
        print(f"  [ERROR] MongoDB no disponible: {mongo.get('error')}")
    redis_health = check_redis_health()
    print("\n=== Conectividad Redis ===")
    if redis_health["status"] == "ok":
        print(f"  [OK]    Redis disponible | prefix='{redis_health['prefix']}' | claves={redis_health['cached_keys_count']}")
    else:
        print(f"  [AVISO] Redis no disponible (tolerado): {redis_health['message']}")
    return 0 if all_orig_ok and mongo["status"] == "ok" else 1


def _leer_todo(args: argparse.Namespace, base: date) -> tuple[dict[str, list], dict[str, int]]:
    """Genera los adicionales (si corresponde) y devuelve las filas crudas combinadas."""
    crudo = leer_directorio(args.original_dir, "original")
    conteos_adic: dict[str, int] = {}
    if not args.original_only:
        conteos_adic = extra_data.escribir_csv(args.additional_dir, base)
        extra = leer_directorio(args.additional_dir, "additional")
        for dataset in DATASETS:
            crudo[dataset] = crudo[dataset] + extra[dataset]
    return crudo, conteos_adic


def _invalidar_redis() -> str:
    """Borra solo las claves del prefijo del proyecto. Tolera Redis caído."""
    settings = get_settings()
    try:
        cliente = get_redis_client()
        borradas = 0
        for clave in cliente.scan_iter(match=f"{settings.redis_prefix}*", count=200):
            borradas += cliente.delete(clave)
        cliente.close()
        return f"Redis: {borradas} claves '{settings.redis_prefix}*' invalidadas"
    except Exception as exc:  # Redis es solo caché: no bloquea la carga
        return f"Redis no disponible ({exc}); se omite la invalidación (la caché expira por TTL)"


def cargar_en_mongo(docs: dict[str, list[dict[str, Any]]], contadores: dict[str, int], db_name: str | None = None) -> dict[str, int]:
    """Resetea las colecciones del proyecto, crea validadores e índices e inserta los documentos."""
    cliente = get_mongo_client()
    try:
        db = get_db(client=cliente, db_name=db_name)
        for nombre in COLECCIONES:
            db.drop_collection(nombre)
        for nombre in COLECCIONES:
            db.create_collection(nombre, validator=VALIDADORES[nombre], validationLevel="strict", validationAction="error")
        conteos = {}
        for nombre in COLECCIONES[:-1]:
            if docs[nombre]:
                db[nombre].insert_many(docs[nombre])
            conteos[nombre] = len(docs[nombre])
        db["contadores"].insert_many([{"_id": k, "valor": v} for k, v in contadores.items()])
        for coleccion, claves, opciones in INDICES:
            db[coleccion].create_index(claves, **opciones)
        return conteos
    finally:
        cliente.close()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.check:
        return run_check(args.original_dir, args.additional_dir)

    base = args.base_date or hoy()
    crudo, conteos_adic = _leer_todo(args, base)
    docs, reporte = validar_y_transformar(crudo)

    modo = "solo originales" if args.original_only else f"originales + adicionales (fecha base {base.isoformat()})"
    print(f"=== Carga FarmaRed: {modo} ===")
    if not reporte.ok:
        print(f"\n[ERROR] {len(reporte.errores)} inconsistencias; no se modificó ninguna base:")
        for linea in reporte.errores:
            print(f"  - {linea}")
        return 1
    contadores = maximos_contadores(crudo)

    if args.dry_run:
        print("[DRY-RUN] Validación correcta; no se tocó MongoDB ni Redis.")
        for nombre in COLECCIONES[:-1]:
            print(f"  {nombre:15s} {len(docs[nombre]):4d} documentos")
        print(f"  contadores: {contadores}")
        return 0

    mongo = check_mongo_health()
    if mongo["status"] != "ok":
        print(f"[ERROR] MongoDB no disponible: {mongo.get('error')}")
        return 1
    conteos = cargar_en_mongo(docs, contadores)
    print("MongoDB: colecciones recreadas con validadores e índices")
    for nombre, cantidad in conteos.items():
        print(f"  {nombre:15s} {cantidad:4d} documentos")
    print(f"  contadores: {contadores} (el próximo ID usa valor + 1)")
    print(_invalidar_redis())
    print(f"Listo. Fecha base de la carga: {base.isoformat()} (Q5, Q6, Q11 y Q12 dependen del día).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
