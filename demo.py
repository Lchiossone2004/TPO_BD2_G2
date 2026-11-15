"""Arranque de la demo con un solo comando.

    python demo.py             # levanta Docker, deja los datos listos, inicia la web y abre el navegador
    python demo.py --reset     # además recarga los datos (seed) y recrea el escenario de q15
    python demo.py --no-docker # si MongoDB y Redis ya están corriendo
    python demo.py --down      # apaga los contenedores y termina

Qué hace, en orden: docker compose up -d, espera a MongoDB (rs0) y Redis, carga los datos si la base está
vacía (o con --reset), crea la venta técnica V900 de q15 si falta y arranca la consola en http://127.0.0.1:8000.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def paso(texto: str) -> None:
    print(f"\n==> {texto}", flush=True)


def docker(*args: str) -> int:
    if shutil.which("docker") is None:
        print("[ERROR] No se encontró Docker. Instalalo/abrilo, o usá --no-docker si MongoDB y Redis ya corren.")
        return 1
    return subprocess.call(["docker", "compose", *args], cwd=ROOT)


def esperar_motores(timeout: int = 120) -> bool:
    from src.infrastructure.mongo import check_mongo_health
    from src.infrastructure.redis_client import check_redis_health

    inicio = time.time()
    mongo_ok = redis_ok = False
    while time.time() - inicio < timeout:
        mongo_ok = mongo_ok or check_mongo_health()["status"] == "ok"
        redis_ok = redis_ok or check_redis_health()["status"] == "ok"
        if mongo_ok and redis_ok:
            return True
        print("    esperando a MongoDB (rs0) y Redis…", flush=True)
        time.sleep(3)
    print(f"[ERROR] No respondieron a tiempo: MongoDB={'ok' if mongo_ok else 'no'}, Redis={'ok' if redis_ok else 'no'}.")
    return False


def preparar_datos(reset: bool) -> int:
    from src.infrastructure.mongo import get_mongo_client, get_db
    from src.loading.fixtures import crear_fixture_q15

    cliente = get_mongo_client()
    db = get_db(client=cliente)
    try:
        vacia = db["ventas"].count_documents({}) == 0 or db["clientes"].count_documents({}) == 0
        if reset or vacia:
            paso("Cargando datos (seed): CSV originales + adicionales con fecha base de hoy")
            import seed

            if seed.main([]) != 0:
                return 1
            crear_fixture_q15(db)
            print("Escenario técnico de q15 creado (venta V900).")
        else:
            print("La base ya tiene datos; se conservan (usá --reset para recargarlos).")
            if db["ventas"].count_documents({"_id": "V900"}) == 0:
                crear_fixture_q15(db)
                print("Se recreó el escenario técnico de q15 (venta V900).")
    finally:
        cliente.close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Levanta la demo de FarmaRed.")
    ap.add_argument("--reset", action="store_true", help="Recarga los datos y recrea el escenario de q15.")
    ap.add_argument("--no-docker", action="store_true", help="No ejecuta docker compose (los motores ya están corriendo).")
    ap.add_argument("--no-browser", action="store_true", help="No abre el navegador.")
    ap.add_argument("--down", action="store_true", help="Apaga los contenedores y termina.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()

    if args.down:
        return docker("down")
    if not args.no_docker:
        paso("Levantando MongoDB (rs0) y Redis con Docker")
        if docker("up", "-d") != 0:
            return 1
    paso("Esperando a los motores")
    if not esperar_motores():
        return 1
    if preparar_datos(args.reset) != 0:
        return 1

    url = f"http://{args.host}:{args.port}"
    paso(f"Consola lista en {url}   (Swagger: {url}/docs)   — Ctrl+C para detener la web")
    if not args.no_browser:
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()
    import uvicorn

    uvicorn.run("src.web.app:app", host=args.host, port=args.port, log_level="warning")
    print("\nWeb detenida. Los contenedores siguen corriendo; apagalos con: python demo.py --down")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nDetenido.")
