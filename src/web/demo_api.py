"""Endpoints de apoyo para la demo: datos de referencia, instantáneas antes/después y reinicio."""

from __future__ import annotations

import contextlib
import io
from typing import Any

from fastapi import APIRouter

from src.clock import bson_to_date, hoy
from src.infrastructure.mongo import get_shared_db
from src.services.exceptions import NO_ENCONTRADO, DomainError
from src.services.serialization import a_json

router = APIRouter(prefix="/api/demo", tags=["Demo"])


@router.get("/reference", summary="Datos de referencia para armar pedidos (selectores de la consola)")
def reference() -> dict[str, Any]:
    db = get_shared_db()
    sucursales = {s["_id"]: s for s in db["sucursales"].find()}
    return a_json({
        "clientes": [{"id": c["_id"], "nombre": f"{c['nombre']} {c['apellido']}", "activo": c["activo"],
                      "obra_social": c["obra_social"], "dni": c["dni"]}
                     for c in db["clientes"].find().sort("_id", 1)],
        "farmaceuticos": [{"id": f["_id"], "nombre": f"{f['nombre']} {f['apellido']}", "activo": f["activo"],
                           "id_sucursal": f["id_sucursal"],
                           "tipo_sucursal": sucursales.get(f["id_sucursal"], {}).get("tipo")}
                          for f in db["farmaceuticos"].find().sort("_id", 1)],
        "sucursales": [{"id": s["_id"], "nombre": s["nombre"], "tipo": s["tipo"], "activo": s["activo"]}
                       for s in sucursales.values()],
        "productos": [{"id": p["_id"], "nombre": p["nombre"], "condicion": p["condicion_venta"],
                       "precio": p["precio_unit"], "activo": p["activo"]}
                      for p in db["productos"].find().sort("_id", 1)],
        "recetas": [{"id": r["_id"], "id_cliente": r["id_cliente"], "tipo": r["tipo"], "estado": r["estado"],
                     "realizadas": r["dispensas_realizadas"], "autorizadas": r["dispensas_autorizadas"],
                     "proxima_dispensa": r["proxima_dispensa"]}
                    for r in db["recetas"].find().sort("_id", 1)],
        "ventas": [{"id": v["_id"], "estado": v["estado"], "origen": v.get("origen"),
                    "stock_aplicado": v.get("stock_aplicado"), "id_cliente": v["id_cliente"], "total": v["total"]}
                   for v in db["ventas"].find().sort("_id", 1)],
    })


@router.get("/snapshot", summary="Estado de lotes, receta y contadores involucrados en una operación")
def snapshot(id_cliente: str | None = None, id_farmaceutico: str | None = None, id_receta: str | None = None,
             productos: str = "", id_venta: str | None = None) -> dict[str, Any]:
    """Se consulta antes y después de q14/q15 para mostrar qué cambió (y qué no) en MongoDB."""
    db = get_shared_db()
    venta = None
    ids_producto = [p.strip() for p in productos.split(",") if p.strip()]
    if id_venta:
        venta = db["ventas"].find_one({"_id": id_venta})
        if venta is None:
            raise DomainError(NO_ENCONTRADO, f"No existe la venta {id_venta}.", 404, {"id_venta": id_venta})
        id_farmaceutico = venta["id_farmaceutico"]
        ids_producto = sorted({i["id_producto"] for i in venta["items"]})
        id_receta = id_receta or venta.get("id_receta")
    farmaceutico = db["farmaceuticos"].find_one({"_id": id_farmaceutico}) if id_farmaceutico else None
    id_sucursal = farmaceutico["id_sucursal"] if farmaceutico else None
    manana = hoy()
    lotes = []
    if id_sucursal and ids_producto:
        for lote in db["stock_lotes"].find({"id_sucursal": id_sucursal, "id_producto": {"$in": ids_producto}}).sort(
                [("id_producto", 1), ("vencimiento", 1), ("_id", 1)]):
            lotes.append({"id_lote": lote["_id"], "id_producto": lote["id_producto"], "nro_lote": lote["nro_lote"],
                          "unidades": lote["unidades"], "vencimiento": lote["vencimiento"],
                          "vigente": bson_to_date(lote["vencimiento"]) >= manana})
    receta = db["recetas"].find_one({"_id": id_receta}) if id_receta else None
    contadores = {c["_id"]: c["valor"] for c in db["contadores"].find()}
    return a_json({
        "fecha": manana, "id_sucursal": id_sucursal, "lotes": lotes, "receta": receta, "venta": venta,
        "contadores": contadores, "total_ventas": db["ventas"].count_documents({}),
    })


@router.post("/reset", summary="Recarga los datos (seed) y recrea el escenario técnico de q15")
def reset() -> dict[str, Any]:
    """Deja la base como al empezar la demo: CSV originales + adicionales con fecha base de hoy + fixture q15."""
    import seed
    from src.loading.fixtures import crear_fixture_q15

    salida = io.StringIO()
    with contextlib.redirect_stdout(salida):
        codigo = seed.main([])
    if codigo != 0:
        return {"status": "error", "log": salida.getvalue()}
    crear_fixture_q15(get_shared_db())
    return {"status": "ok", "log": salida.getvalue() + "Escenario técnico de q15 creado (venta V900).\n"}


@router.post("/fixture-q15", summary="Recrea la venta técnica V900 de q15 (caso normal o sin stock)")
def fixture_q15(caso: str = "normal") -> dict[str, Any]:
    from src.loading.fixtures import CANTIDAD, crear_fixture_q15

    venta = crear_fixture_q15(get_shared_db(), 5000 if caso == "sin_stock" else CANTIDAD)
    return a_json({"status": "ok", "caso": caso, "venta": venta})


@router.get("/collections", summary="Colecciones de MongoDB con su cantidad de documentos (vista en vivo)")
def collections() -> dict[str, Any]:
    db = get_shared_db()
    nombres = sorted(n for n in db.list_collection_names() if not n.startswith("system."))
    return {"collections": [{"name": n, "count": db[n].count_documents({})} for n in nombres]}


@router.get("/collection/{name}", summary="Contenido de una colección (solo lectura, para mostrar en vivo)")
def collection(name: str, limit: int = 300, desc: bool = False) -> dict[str, Any]:
    db = get_shared_db()
    if name not in db.list_collection_names() or name.startswith("system."):
        raise DomainError(NO_ENCONTRADO, f"No existe la colección {name}.", 404, {"coleccion": name})
    limit = max(1, min(limit, 1000))
    docs = list(db[name].find().sort("_id", -1 if desc else 1).limit(limit))
    return a_json({"name": name, "count": db[name].count_documents({}), "shown": len(docs), "docs": docs})
