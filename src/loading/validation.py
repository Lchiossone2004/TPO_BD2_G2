"""Lectura, validación y transformación de los CSV de FarmaRed a documentos de MongoDB."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from src.clock import date_to_bson

DATASETS = ("clientes", "sucursales", "farmaceuticos", "proveedores", "productos",
            "stock_lotes", "recetas", "ventas", "detalle_ventas")

ENUMS: dict[str, tuple[str, ...]] = {
    "sucursal.tipo": ("Farmacia", "Droguería"),
    "farmaceutico.cargo": ("Director Técnico", "Farmacéutico"),
    "proveedor.tipo": ("Laboratorio", "Droguería"),
    "producto.condicion_venta": ("Venta libre", "Bajo receta", "Bajo receta archivada"),
    "receta.tipo": ("Simple", "Archivada", "Tratamiento prolongado"),
    "receta.estado": ("Vigente", "Completada", "Vencida"),
    "venta.tipo": ("Venta libre", "Con receta"),
    "venta.medio_pago": ("Efectivo", "Débito", "Crédito", "Transferencia", "Obra social"),
    "venta.estado": ("Completada", "Pendiente", "Anulada"),
}

# (campo, tipo, obligatorio, enum)   tipos: str, int, bool, date
SPEC: dict[str, list[tuple[str, str, bool, str | None]]] = {
    "clientes": [("nombre", "str", True, None), ("apellido", "str", True, None), ("dni", "str", True, None),
                 ("email", "str", False, None), ("telefono", "str", False, None), ("ciudad", "str", True, None),
                 ("provincia", "str", True, None), ("obra_social", "str", True, None),
                 ("nro_afiliado", "str", False, None), ("activo", "bool", True, None)],
    "sucursales": [("nombre", "str", True, None), ("tipo", "str", True, "sucursal.tipo"),
                   ("direccion", "str", True, None), ("ciudad", "str", True, None), ("provincia", "str", True, None),
                   ("telefono", "str", True, None), ("activo", "bool", True, None)],
    "farmaceuticos": [("nombre", "str", True, None), ("apellido", "str", True, None), ("matricula", "str", True, None),
                      ("cargo", "str", True, "farmaceutico.cargo"), ("id_sucursal", "str", True, None),
                      ("activo", "bool", True, None)],
    "proveedores": [("razon_social", "str", True, None), ("cuit", "str", True, None),
                    ("tipo", "str", True, "proveedor.tipo"), ("ciudad", "str", True, None),
                    ("provincia", "str", True, None), ("telefono", "str", True, None), ("activo", "bool", True, None)],
    "productos": [("nombre", "str", True, None), ("principio_activo", "str", True, None),
                  ("categoria", "str", True, None), ("presentacion", "str", True, None),
                  ("condicion_venta", "str", True, "producto.condicion_venta"), ("precio_unit", "int", True, None),
                  ("id_proveedor", "str", True, None), ("activo", "bool", True, None)],
    "recetas": [("id_cliente", "str", True, None), ("medico", "str", True, None), ("matricula_medico", "str", True, None),
                ("fecha_emision", "date", True, None), ("tipo", "str", True, "receta.tipo"),
                ("dispensas_autorizadas", "int", True, None), ("dispensas_realizadas", "int", True, None),
                ("proxima_dispensa", "date", False, None), ("estado", "str", True, "receta.estado")],
    "stock_lotes": [("id_producto", "str", True, None), ("id_sucursal", "str", True, None),
                    ("nro_lote", "str", True, None), ("unidades", "int", True, None), ("vencimiento", "date", True, None)],
    "ventas": [("id_cliente", "str", True, None), ("id_farmaceutico", "str", True, None),
               ("id_receta", "str", False, None), ("fecha", "date", True, None),
               ("tipo", "str", True, "venta.tipo"), ("medio_pago", "str", True, "venta.medio_pago"),
               ("total", "int", True, None), ("estado", "str", True, "venta.estado")],
    "detalle_ventas": [("id_venta", "str", True, None), ("id_producto", "str", True, None),
                       ("cantidad", "int", True, None), ("precio_unit", "int", True, None)],
}
ID_FIELD = {"clientes": "id_cliente", "sucursales": "id_sucursal", "farmaceuticos": "id_farmaceutico",
            "proveedores": "id_proveedor", "productos": "id_producto", "stock_lotes": "id_lote",
            "recetas": "id_receta", "ventas": "id_venta", "detalle_ventas": "id_detalle"}
ID_PATTERN = {"clientes": r"C\d+", "sucursales": r"S\d+", "farmaceuticos": r"F\d+", "proveedores": r"PRV\d+",
              "productos": r"PRD\d+", "stock_lotes": r"L\d+", "recetas": r"RC\d+", "ventas": r"V\d+",
              "detalle_ventas": r"D\d+"}
NON_NEGATIVE = {"precio_unit", "unidades", "total", "dispensas_realizadas"}
POSITIVE = {"cantidad", "dispensas_autorizadas"}


@dataclass
class Reporte:
    """Acumula los errores de validación (dataset, fila, mensaje)."""
    errores: list[str] = field(default_factory=list)

    def error(self, dataset: str, origen: str, id_: str, mensaje: str) -> None:
        self.errores.append(f"[{dataset}] {origen} {id_}: {mensaje}")

    @property
    def ok(self) -> bool:
        return not self.errores


def leer_directorio(directorio: Path, etiqueta: str) -> dict[str, list[tuple[str, dict[str, str]]]]:
    """Lee los CSV presentes de un directorio. Devuelve filas con su origen (``etiqueta:archivo:línea``)."""
    resultado: dict[str, list[tuple[str, dict[str, str]]]] = {d: [] for d in DATASETS}
    for dataset in DATASETS:
        ruta = directorio / f"{dataset}.csv"
        if not ruta.is_file():
            continue
        with ruta.open("r", encoding="utf-8", newline="") as fh:
            for n, fila in enumerate(csv.DictReader(fh), start=2):
                resultado[dataset].append((f"{etiqueta}/{ruta.name}:{n}", {k: (v or "").strip() for k, v in fila.items() if k}))
    return resultado


def _convertir(valor: str, tipo: str) -> Any:
    if tipo == "str":
        return valor
    if tipo == "int":
        if not re.fullmatch(r"-?\d+", valor):
            raise ValueError(f"no es un entero: {valor!r}")
        return int(valor)
    if tipo == "bool":
        if valor not in ("True", "False"):
            raise ValueError(f"booleano inválido (se espera True/False): {valor!r}")
        return valor == "True"
    if tipo == "date":
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", valor):
            raise ValueError(f"fecha inválida (se espera AAAA-MM-DD): {valor!r}")
        return date.fromisoformat(valor)
    raise ValueError(tipo)


def validar_y_transformar(
    crudo: dict[str, list[tuple[str, dict[str, str]]]],
) -> tuple[dict[str, list[dict[str, Any]]], Reporte]:
    """Valida tipos, enums, unicidad, referencias y reglas de negocio; arma los documentos finales."""
    rep = Reporte()
    tipado: dict[str, list[dict[str, Any]]] = {d: [] for d in DATASETS}

    # 1) Tipos, obligatorios, enums, IDs únicos y rangos
    for dataset in DATASETS:
        vistos: set[str] = set()
        idf = ID_FIELD[dataset]
        for origen, fila in crudo[dataset]:
            id_ = fila.get(idf, "")
            if not re.fullmatch(ID_PATTERN[dataset], id_):
                rep.error(dataset, origen, id_ or "(sin id)", f"{idf} inválido (patrón {ID_PATTERN[dataset]})")
                continue
            if id_ in vistos:
                rep.error(dataset, origen, id_, "ID duplicado")
                continue
            vistos.add(id_)
            doc: dict[str, Any] = {"_origen": origen, idf: id_}
            for campo, tipo, oblig, enum in SPEC[dataset]:
                bruto = fila.get(campo)
                if bruto is None:
                    rep.error(dataset, origen, id_, f"falta la columna {campo}")
                    continue
                if bruto == "":
                    if oblig:
                        rep.error(dataset, origen, id_, f"{campo} es obligatorio")
                    doc[campo] = None
                    continue
                try:
                    valor = _convertir(bruto, tipo)
                except ValueError as exc:
                    rep.error(dataset, origen, id_, f"{campo}: {exc}")
                    continue
                if enum and valor not in ENUMS[enum]:
                    rep.error(dataset, origen, id_, f"{campo}={valor!r} fuera de {ENUMS[enum]}")
                if campo in NON_NEGATIVE and valor < 0:
                    rep.error(dataset, origen, id_, f"{campo} no puede ser negativo")
                if campo in POSITIVE and valor <= 0:
                    rep.error(dataset, origen, id_, f"{campo} debe ser mayor que 0")
                doc[campo] = valor
            tipado[dataset].append(doc)

    ids = {d: {doc[ID_FIELD[d]] for doc in tipado[d]} for d in DATASETS}

    def ref(dataset: str, doc: dict[str, Any], campo: str, destino: str) -> None:
        valor = doc.get(campo)
        if valor is not None and valor not in ids[destino]:
            rep.error(dataset, doc["_origen"], doc[ID_FIELD[dataset]], f"{campo}={valor} no existe en {destino}")

    # 2) Unicidad de DNI y matrícula (índices únicos)
    for dataset, campo in (("clientes", "dni"), ("farmaceuticos", "matricula")):
        vistos = {}
        for doc in tipado[dataset]:
            v = doc.get(campo)
            if v in vistos:
                rep.error(dataset, doc["_origen"], doc[ID_FIELD[dataset]], f"{campo} {v} repetido (ya en {vistos[v]})")
            elif v is not None:
                vistos[v] = doc[ID_FIELD[dataset]]

    # 3) Referencias
    for doc in tipado["farmaceuticos"]:
        ref("farmaceuticos", doc, "id_sucursal", "sucursales")
    for doc in tipado["productos"]:
        ref("productos", doc, "id_proveedor", "proveedores")
    for doc in tipado["stock_lotes"]:
        ref("stock_lotes", doc, "id_producto", "productos")
        ref("stock_lotes", doc, "id_sucursal", "sucursales")
    for doc in tipado["recetas"]:
        ref("recetas", doc, "id_cliente", "clientes")
    for doc in tipado["ventas"]:
        ref("ventas", doc, "id_cliente", "clientes")
        ref("ventas", doc, "id_farmaceutico", "farmaceuticos")
        ref("ventas", doc, "id_receta", "recetas")
    for doc in tipado["detalle_ventas"]:
        ref("detalle_ventas", doc, "id_venta", "ventas")
        ref("detalle_ventas", doc, "id_producto", "productos")

    # 4) Reglas de recetas
    for doc in tipado["recetas"]:
        aut, real = doc.get("dispensas_autorizadas"), doc.get("dispensas_realizadas")
        if aut is None or real is None:
            continue
        rid, org = doc["id_receta"], doc["_origen"]
        if not 0 <= real <= aut:
            rep.error("recetas", org, rid, f"dispensas_realizadas={real} fuera de 0..{aut}")
        if doc.get("tipo") == "Tratamiento prolongado" and not 1 <= aut <= 3:
            rep.error("recetas", org, rid, f"prolongada con {aut} dispensas autorizadas (permitido 1 a 3)")
        if doc.get("tipo") in ("Simple", "Archivada") and aut != 1:
            rep.error("recetas", org, rid, f"{doc['tipo']} debe tener 1 dispensa autorizada (tiene {aut})")

    # 5) Ventas con ítems embebidos y total consistente
    productos = {d["id_producto"]: d for d in tipado["productos"]}
    por_venta: dict[str, list[dict[str, Any]]] = {}
    for det in tipado["detalle_ventas"]:
        por_venta.setdefault(det["id_venta"], []).append(det)
    ventas_docs: list[dict[str, Any]] = []
    for v in tipado["ventas"]:
        items_raw = por_venta.get(v["id_venta"], [])
        if not items_raw:
            rep.error("ventas", v["_origen"], v["id_venta"], "la venta no tiene detalle (items no puede ser vacío)")
            continue
        suma = sum((i.get("cantidad") or 0) * (i.get("precio_unit") or 0) for i in items_raw)
        if v.get("total") is not None and suma != v["total"]:
            rep.error("ventas", v["_origen"], v["id_venta"], f"total={v['total']} no coincide con la suma del detalle ({suma})")
        items = [{"id_detalle": i["id_detalle"], "id_producto": i["id_producto"],
                  "nombre_producto": (productos.get(i["id_producto"]) or {}).get("nombre"),
                  "cantidad": i["cantidad"], "precio_unit": i["precio_unit"]} for i in items_raw]
        ventas_docs.append({**v, "items": items})

    # 6) Documentos finales (_id, fechas BSON, campos técnicos)
    docs: dict[str, list[dict[str, Any]]] = {}
    for dataset in DATASETS:
        if dataset == "detalle_ventas":
            continue
        salida = []
        fuente = ventas_docs if dataset == "ventas" else tipado[dataset]
        for doc in fuente:
            nuevo = {k: v for k, v in doc.items() if k != "_origen"}
            nuevo["_id"] = nuevo.pop(ID_FIELD[dataset])
            for k, v in list(nuevo.items()):
                if isinstance(v, date):
                    nuevo[k] = date_to_bson(v)
            if dataset == "ventas":
                nuevo.update(origen="csv", id_operacion=None, huella_solicitud=None,
                             stock_aplicado=nuevo["estado"] == "Completada", asignaciones_stock=[])
            salida.append(nuevo)
        docs[dataset] = salida
    return docs, rep


def maximos_contadores(crudo: dict[str, list[tuple[str, dict[str, str]]]]) -> dict[str, int]:
    """Mayor sufijo numérico presente de cliente, venta y detalle (para inicializar ``contadores``)."""
    def maximo(dataset: str) -> int:
        idf = ID_FIELD[dataset]
        numeros = [int(re.sub(r"\D", "", fila[idf])) for _, fila in crudo[dataset] if re.fullmatch(ID_PATTERN[dataset], fila.get(idf, ""))]
        return max(numeros, default=0)
    return {"cliente": maximo("clientes"), "venta": maximo("ventas"), "detalle": maximo("detalle_ventas")}
