"""q15 — Descuento de stock FEFO de una venta ya registrada"""

from __future__ import annotations

from typing import Any

from src.clock import date_to_bson, hoy
from src.infrastructure.mongo import get_shared_db
from src.services.exceptions import NO_ENCONTRADO, VALIDACION_ERROR, DomainError
from src.services.fefo import agrupar_cantidades, descontar_fefo
from src.services.transactions import ejecutar_en_transaccion

NOTA_HISTORICA = (
    "La venta ya tenía el stock aplicado y no registra desglose por lote (dato histórico cargado desde CSV): "
    "no se descontó nada."
)


def _resultado(venta: dict[str, Any], aplicado_ahora: bool, nota: str | None = None) -> dict[str, Any]:
    return {
        "id_venta": venta["_id"],
        "aplicado_ahora": aplicado_ahora,
        "stock_aplicado": True,
        "asignaciones": venta.get("asignaciones_stock", []),
        "nota": nota,
    }


def ejecutar(id_venta: str | None = None, *, db: Any = None) -> dict[str, Any]:
    """Descuenta el stock de ``id_venta`` en los lotes de la sucursal de su farmacéutico (FEFO).

    - Venta con ``stock_aplicado = true``: devuelve las asignaciones registradas, sin descontar de nuevo.
    - Venta Pendiente o Anulada: se rechaza.
    - Venta Completada sin stock aplicado: descuento + marca en una única transacción; si algún producto no
      alcanza, se aborta todo. No modifica la receta.
    """
    id_venta = (str(id_venta).strip() if id_venta is not None else "")
    if not id_venta:
        raise DomainError(VALIDACION_ERROR, "q15 requiere id_venta.", 400, {"campo": "id_venta"})
    base = db if db is not None else get_shared_db()
    hoy_bson = date_to_bson(hoy())

    def operacion(session: Any) -> dict[str, Any]:
        venta = base["ventas"].find_one({"_id": id_venta}, session=session)
        if venta is None:
            raise DomainError(NO_ENCONTRADO, f"No existe la venta {id_venta}.", 404, {"id_venta": id_venta})
        if venta["estado"] != "Completada":
            raise DomainError(
                VALIDACION_ERROR,
                f"Solo se descuenta stock de ventas Completadas; {id_venta} está {venta['estado']}.",
                422, {"id_venta": id_venta, "estado": venta["estado"]},
            )
        if venta["stock_aplicado"]:
            return _resultado(venta, False, None if venta.get("asignaciones_stock") else NOTA_HISTORICA)

        # Reserva la venta: si otro pedido la tomó a la vez, el motor reintenta y ve stock_aplicado = true.
        marca = base["ventas"].update_one(
            {"_id": id_venta, "stock_aplicado": False, "estado": "Completada"},
            {"$set": {"stock_aplicado": True}}, session=session,
        )
        if marca.modified_count != 1:
            actual = base["ventas"].find_one({"_id": id_venta}, session=session)
            return _resultado(actual, False)
        farmaceutico = base["farmaceuticos"].find_one({"_id": venta["id_farmaceutico"]}, session=session)
        if farmaceutico is None:
            raise DomainError(NO_ENCONTRADO, f"No existe el farmacéutico {venta['id_farmaceutico']}.", 404)
        asignaciones = descontar_fefo(
            base, session, farmaceutico["id_sucursal"], agrupar_cantidades(venta["items"]), hoy_bson
        )
        base["ventas"].update_one({"_id": id_venta}, {"$set": {"asignaciones_stock": asignaciones}}, session=session)
        venta["asignaciones_stock"] = asignaciones
        return _resultado(venta, True)

    return ejecutar_en_transaccion(base.client, operacion)
