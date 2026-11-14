"""Validadores ``$jsonSchema`` e índices de las colecciones de MongoDB"""

from __future__ import annotations

from typing import Any

from pymongo import ASCENDING

from src.loading.validation import ENUMS

S = {"bsonType": "string"}
SN = {"bsonType": ["string", "null"]}
B = {"bsonType": "bool"}
D = {"bsonType": "date"}
DN = {"bsonType": ["date", "null"]}
I = {"bsonType": ["int", "long"]}
I0 = {"bsonType": ["int", "long"], "minimum": 0}
I1 = {"bsonType": ["int", "long"], "minimum": 1}


def _enum(clave: str) -> dict[str, Any]:
    return {"bsonType": "string", "enum": list(ENUMS[clave])}


def _schema(props: dict[str, Any], opcionales: tuple[str, ...] = ()) -> dict[str, Any]:
    requeridos = ["_id"] + [k for k in props if k not in opcionales]
    return {"$jsonSchema": {"bsonType": "object", "required": requeridos,
                            "properties": {"_id": S, **props}}}


ITEM = {"bsonType": "object",
        "required": ["id_detalle", "id_producto", "nombre_producto", "cantidad", "precio_unit"],
        "properties": {"id_detalle": S, "id_producto": S, "nombre_producto": S, "cantidad": I1, "precio_unit": I0}}
ASIGNACION = {"bsonType": "object", "required": ["id_lote", "unidades"],
              "properties": {"id_lote": S, "unidades": I1}}

VALIDADORES: dict[str, dict[str, Any]] = {
    "clientes": _schema({"nombre": S, "apellido": S, "dni": S, "email": SN, "telefono": SN, "ciudad": S,
                         "provincia": S, "obra_social": S, "nro_afiliado": SN, "activo": B}),
    "sucursales": _schema({"nombre": S, "tipo": _enum("sucursal.tipo"), "direccion": S, "ciudad": S,
                           "provincia": S, "telefono": S, "activo": B}),
    "farmaceuticos": _schema({"nombre": S, "apellido": S, "matricula": S, "cargo": _enum("farmaceutico.cargo"),
                              "id_sucursal": S, "activo": B}),
    "proveedores": _schema({"razon_social": S, "cuit": S, "tipo": _enum("proveedor.tipo"), "ciudad": S,
                            "provincia": S, "telefono": S, "activo": B}),
    "productos": _schema({"nombre": S, "principio_activo": S, "categoria": S, "presentacion": S,
                          "condicion_venta": _enum("producto.condicion_venta"), "precio_unit": I0,
                          "id_proveedor": S, "activo": B}),
    "recetas": _schema({"id_cliente": S, "medico": S, "matricula_medico": S, "fecha_emision": D,
                        "tipo": _enum("receta.tipo"), "dispensas_autorizadas": I1, "dispensas_realizadas": I0,
                        "proxima_dispensa": DN, "estado": _enum("receta.estado")}),
    "stock_lotes": _schema({"id_producto": S, "id_sucursal": S, "nro_lote": S, "unidades": I0, "vencimiento": D}),
    "ventas": _schema({"id_cliente": S, "id_farmaceutico": S, "id_receta": SN, "fecha": D,
                       "tipo": _enum("venta.tipo"), "medio_pago": _enum("venta.medio_pago"), "total": I0,
                       "estado": _enum("venta.estado"), "origen": {"bsonType": "string", "enum": ["csv", "servicio"]},
                       "id_operacion": SN, "huella_solicitud": SN, "stock_aplicado": B,
                       "asignaciones_stock": {"bsonType": "array", "items": ASIGNACION},
                       "items": {"bsonType": "array", "minItems": 1, "items": ITEM}}),
    "contadores": {"$jsonSchema": {"bsonType": "object", "required": ["_id", "valor"],
                                   "properties": {"_id": S, "valor": I0}}},
}

# (colección, claves, opciones)
INDICES: list[tuple[str, list[tuple[str, int]], dict[str, Any]]] = [
    ("clientes", [("dni", ASCENDING)], {"unique": True, "name": "uq_dni"}),
    ("farmaceuticos", [("matricula", ASCENDING)], {"unique": True, "name": "uq_matricula"}),
    ("farmaceuticos", [("id_sucursal", ASCENDING)], {"name": "ix_sucursal"}),
    ("productos", [("activo", ASCENDING)], {"name": "ix_activo"}),
    ("recetas", [("id_cliente", ASCENDING), ("fecha_emision", ASCENDING)], {"name": "ix_cliente_emision"}),
    ("recetas", [("tipo", ASCENDING), ("estado", ASCENDING), ("proxima_dispensa", ASCENDING)], {"name": "ix_prolongadas"}),
    ("ventas", [("id_cliente", ASCENDING), ("fecha", ASCENDING)], {"name": "ix_cliente_fecha"}),
    ("ventas", [("id_farmaceutico", ASCENDING), ("fecha", ASCENDING), ("estado", ASCENDING)], {"name": "ix_farmaceutico_fecha_estado"}),
    ("ventas", [("estado", ASCENDING), ("fecha", ASCENDING)], {"name": "ix_estado_fecha"}),
    ("ventas", [("tipo", ASCENDING), ("total", ASCENDING)], {"name": "ix_tipo_total"}),
    ("ventas", [("id_operacion", ASCENDING)],
     {"unique": True, "name": "uq_id_operacion", "partialFilterExpression": {"id_operacion": {"$type": "string"}}}),
    ("stock_lotes", [("id_producto", ASCENDING), ("id_sucursal", ASCENDING), ("vencimiento", ASCENDING), ("_id", ASCENDING)], {"name": "ix_fefo"}),
    ("stock_lotes", [("unidades", ASCENDING)], {"name": "ix_unidades"}),
]
