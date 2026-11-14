"""Fixture para demostrar q15 sola (no forma parte de los CSV ni del flujo normal de q14)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from src.clock import date_to_bson, hoy

ID_VENTA = "V900"
LOTES = (("LFX-1", "FX-Q15-A", 2, 30), ("LFX-2", "FX-Q15-B", 5, 90))  # (_id, nro_lote, unidades, días a vencer)
ID_PRODUCTO = "PRD002"
ID_FARMACEUTICO = "F001"
ID_CLIENTE = "C001"
CANTIDAD = 4


def crear_fixture_q15(db: Any) -> dict[str, Any]:
    """Inserta (o restaura) el escenario y devuelve la venta creada."""
    farmaceutico = db["farmaceuticos"].find_one({"_id": ID_FARMACEUTICO})
    producto = db["productos"].find_one({"_id": ID_PRODUCTO})
    if farmaceutico is None or producto is None:
        raise RuntimeError("Faltan datos base: cargue la base con `python seed.py` antes del fixture.")
    base = hoy()
    db["stock_lotes"].delete_many({"_id": {"$in": [l[0] for l in LOTES]}})
    db["ventas"].delete_one({"_id": ID_VENTA})
    db["stock_lotes"].insert_many([
        {"_id": id_lote, "id_producto": ID_PRODUCTO, "id_sucursal": farmaceutico["id_sucursal"],
         "nro_lote": nro, "unidades": unidades, "vencimiento": date_to_bson(base + timedelta(days=dias))}
        for id_lote, nro, unidades, dias in LOTES
    ])
    venta = {
        "_id": ID_VENTA, "id_cliente": ID_CLIENTE, "id_farmaceutico": ID_FARMACEUTICO, "id_receta": None,
        "fecha": date_to_bson(base), "tipo": "Venta libre", "medio_pago": "Efectivo",
        "total": CANTIDAD * producto["precio_unit"], "estado": "Completada", "origen": "servicio",
        "id_operacion": None, "huella_solicitud": None, "stock_aplicado": False, "asignaciones_stock": [],
        "items": [{"id_detalle": "D900", "id_producto": ID_PRODUCTO, "nombre_producto": producto["nombre"],
                   "cantidad": CANTIDAD, "precio_unit": producto["precio_unit"]}],
    }
    db["ventas"].insert_one(venta)
    return venta


if __name__ == "__main__":
    import json

    from src.infrastructure.mongo import get_shared_db
    from src.services.serialization import a_json

    print(json.dumps(a_json(crear_fixture_q15(get_shared_db())), indent=2, ensure_ascii=False))
