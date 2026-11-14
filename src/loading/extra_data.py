"""Generador reproducible de los datasets adicionales (nueve CSV, al menos 10 filas cada uno)."""

from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path
from typing import Any

FILES: dict[str, list[str]] = {
    "clientes": ["id_cliente", "nombre", "apellido", "dni", "email", "telefono", "ciudad", "provincia", "obra_social", "nro_afiliado", "activo"],
    "sucursales": ["id_sucursal", "nombre", "tipo", "direccion", "ciudad", "provincia", "telefono", "activo"],
    "farmaceuticos": ["id_farmaceutico", "nombre", "apellido", "matricula", "cargo", "id_sucursal", "activo"],
    "proveedores": ["id_proveedor", "razon_social", "cuit", "tipo", "ciudad", "provincia", "telefono", "activo"],
    "productos": ["id_producto", "nombre", "principio_activo", "categoria", "presentacion", "condicion_venta", "precio_unit", "id_proveedor", "activo"],
    "stock_lotes": ["id_lote", "id_producto", "id_sucursal", "nro_lote", "unidades", "vencimiento"],
    "recetas": ["id_receta", "id_cliente", "medico", "matricula_medico", "fecha_emision", "tipo", "dispensas_autorizadas", "dispensas_realizadas", "proxima_dispensa", "estado"],
    "ventas": ["id_venta", "id_cliente", "id_farmaceutico", "id_receta", "fecha", "tipo", "medio_pago", "total", "estado"],
    "detalle_ventas": ["id_detalle", "id_venta", "id_producto", "cantidad", "precio_unit"],
}


def _rows(columns: list[str], data: list[tuple[Any, ...]]) -> list[dict[str, Any]]:
    return [dict(zip(columns, row)) for row in data]


def generar(base: date) -> dict[str, list[dict[str, Any]]]:
    """Devuelve las filas adicionales de cada dataset para la fecha base indicada."""
    d = lambda n: (base - timedelta(days=n)).isoformat()  # noqa: E731 - base menos n días
    f = lambda n: (base + timedelta(days=n)).isoformat()  # noqa: E731 - base más n días
    mes = base.replace(day=1).isoformat()  # siempre dentro del mes actual y <= base
    hoy_iso = base.isoformat()
    T, F = "True", "False"

    sucursales = _rows(FILES["sucursales"], [
        ("S006", "Farmacia Mar del Plata", "Farmacia", "Av. Colón 2210", "Mar del Plata", "Buenos Aires", "2234006006", T),
        ("S007", "Farmacia Mendoza Centro", "Farmacia", "Av. San Martín 1180", "Mendoza", "Mendoza", "2614007007", T),
        ("S008", "Farmacia Tucumán", "Farmacia", "Calle 24 de Septiembre 650", "San Miguel de Tucumán", "Tucumán", "3814008008", T),
        ("S009", "Farmacia Salta Norte", "Farmacia", "Av. Belgrano 940", "Salta", "Salta", "3874009009", T),
        ("S010", "Droguería Cuyo", "Droguería", "Ruta 7 km 5", "Mendoza", "Mendoza", "2614010010", T),
        ("S011", "Farmacia La Plata", "Farmacia", "Calle 7 N° 845", "La Plata", "Buenos Aires", "2214011011", T),
        ("S012", "Farmacia Neuquén", "Farmacia", "Av. Argentina 1320", "Neuquén", "Neuquén", "2994012012", T),
        ("S013", "Farmacia Quilmes", "Farmacia", "Av. Mitre 310", "Quilmes", "Buenos Aires", "1142013013", T),
        ("S014", "Droguería Litoral", "Droguería", "Ruta 11 km 8", "Santa Fe", "Santa Fe", "3424014014", T),
        ("S015", "Farmacia Bahía Blanca", "Farmacia", "Calle Alsina 215", "Bahía Blanca", "Buenos Aires", "2914015015", F),
    ])

    farmaceuticos = _rows(FILES["farmaceuticos"], [
        ("F008", "Valeria", "Ortiz", "MN-18502", "Director Técnico", "S006", T),
        ("F009", "Diego", "Herrera", "MN-18517", "Farmacéutico", "S006", T),
        ("F010", "Lorena", "Molina", "MN-18533", "Director Técnico", "S007", T),
        ("F011", "Tomás", "Aguirre", "MN-18548", "Farmacéutico", "S008", T),
        ("F012", "Paula", "Rivero", "MN-18561", "Director Técnico", "S009", T),
        ("F013", "Gabriel", "Suárez", "MN-18577", "Director Técnico", "S010", T),  # Droguería, sin ventas
        ("F014", "Camila", "Duarte", "MN-18590", "Farmacéutico", "S011", T),
        ("F015", "Nicolás", "Peralta", "MN-18604", "Farmacéutico", "S012", T),    # activo, sin ventas
        ("F016", "Agustina", "Roldán", "MN-18619", "Farmacéutico", "S013", F),    # inactiva con ventas
        ("F017", "Esteban", "Medina", "MN-18633", "Director Técnico", "S014", T),  # Droguería, sin ventas
    ])

    proveedores = _rows(FILES["proveedores"], [
        ("PRV006", "Laboratorios del Plata S.A.", "30-71600111-2", "Laboratorio", "Buenos Aires", "Buenos Aires", "1143006600", T),
        ("PRV007", "Droguería Norte S.R.L.", "30-70700222-4", "Droguería", "San Miguel de Tucumán", "Tucumán", "3814007700", T),
        ("PRV008", "NutriSalud S.A.", "30-71800333-6", "Laboratorio", "Rosario", "Santa Fe", "3414008800", T),
        ("PRV009", "Mayorista Cuyo S.A.", "30-70900444-8", "Droguería", "Mendoza", "Mendoza", "2614009900", T),
        ("PRV010", "Insumos Médicos Atlántico S.R.L.", "30-71000555-1", "Droguería", "Mar del Plata", "Buenos Aires", "2234010100", F),
        ("PRV011", "Laboratorio Patagónico S.A.", "30-71100666-3", "Laboratorio", "Neuquén", "Neuquén", "2994011100", T),
        ("PRV012", "Distribuidora Federal S.A.", "30-71200777-5", "Droguería", "Córdoba", "Córdoba", "3514012200", T),
        ("PRV013", "GenéricosPlus S.A.", "30-71300888-7", "Laboratorio", "La Plata", "Buenos Aires", "2214013300", T),
        ("PRV014", "Droguería Costa S.R.L.", "30-71400999-9", "Droguería", "Mar del Plata", "Buenos Aires", "2234014400", T),
        ("PRV015", "Química Austral S.A.", "30-71501010-2", "Laboratorio", "Bahía Blanca", "Buenos Aires", "2914015500", F),
    ])

    productos = _rows(FILES["productos"], [
        ("PRD014", "Diclofenac gel 60g", "Diclofenac", "Antiinflamatorio", "Gel 60 g", "Venta libre", 3100, "PRV006", T),
        ("PRD015", "Enalapril 10mg x30", "Enalapril", "Antihipertensivo", "Comprimidos x30", "Bajo receta", 3300, "PRV007", T),
        ("PRD016", "Clonazepam 2mg x30", "Clonazepam", "Ansiolítico", "Comprimidos x30", "Bajo receta archivada", 6800, "PRV009", T),
        ("PRD017", "Azitromicina 500mg x3", "Azitromicina", "Antibiótico", "Comprimidos x3", "Bajo receta", 8200, "PRV006", T),
        ("PRD018", "Vitamina C 1g x20", "Ácido ascórbico", "Suplemento", "Comprimidos efervescentes x20", "Venta libre", 2900, "PRV008", T),
        ("PRD019", "Insulina glargina 100UI/ml", "Insulina glargina", "Antidiabético", "Pluma 3 ml", "Bajo receta", 21500, "PRV007", T),
        ("PRD020", "Ibuprofeno pediátrico 100mg/5ml", "Ibuprofeno", "Antiinflamatorio", "Suspensión 120 ml", "Venta libre", 3400, "PRV008", T),
        ("PRD021", "Barbijo quirúrgico x50", "No aplica", "Insumo", "Caja x50", "Venta libre", 4100, "PRV010", F),
        ("PRD022", "Cetirizina 10mg x10", "Cetirizina", "Antihistamínico", "Comprimidos x10", "Venta libre", 2600, "PRV006", T),
        ("PRD023", "Lansoprazol 30mg x28", "Lansoprazol", "Gastroprotector", "Cápsulas x28", "Bajo receta", 5200, "PRV009", T),
    ])
    precio = {p["id_producto"]: p["precio_unit"] for p in productos}

    clientes = _rows(FILES["clientes"], [
        ("C009", "Valentina", "Ríos", "36521478", "val.rios@gmail.com", "1145009009", "Buenos Aires", "Buenos Aires", "OSDE", "OS-455120", T),
        ("C010", "Joaquín", "Molina", "29874512", "joaquin.m@gmail.com", "2614010010", "Mendoza", "Mendoza", "Swiss Medical", "SM-310778", T),
        ("C011", "Agustina", "Peralta", "41236985", "agus.p@gmail.com", "2234011011", "Mar del Plata", "Buenos Aires", "PAMI", "PA-882014", T),
        ("C012", "Leandro", "Suárez", "32654789", "leandro.s@gmail.com", "3814012012", "San Miguel de Tucumán", "Tucumán", "Galeno", "GA-771233", F),  # inactivo
        ("C013", "Marina", "Sosa", "27458963", "", "3874013013", "Salta", "Salta", "Sin cobertura", "", T),  # email y afiliado nulos
        ("C014", "Bruno", "Castro", "38741256", "bruno.c@gmail.com", "2214014014", "La Plata", "Buenos Aires", "IOMA", "IO-651207", T),
        ("C015", "Daniela", "Vera", "35698741", "dani.v@gmail.com", "2994015015", "Neuquén", "Neuquén", "OSDE", "OS-233901", T),  # sin ventas
        ("C016", "Gonzalo", "Ibáñez", "30258741", "gonzalo.i@gmail.com", "1142016016", "Quilmes", "Buenos Aires", "Sin cobertura", "", T),  # sin ventas
        ("C017", "Rosa", "Domínguez", "12365478", "rosa.d@gmail.com", "3424017017", "Santa Fe", "Santa Fe", "PAMI", "PA-410096", T),  # varias recetas
        ("C018", "Tamara", "Luna", "42587963", "tamara.l@gmail.com", "2914018018", "Bahía Blanca", "Buenos Aires", "Galeno", "GA-118542", T),  # última venta > 1 año
    ])

    recetas = _rows(FILES["recetas"], [
        ("RC010", "C017", "Dr. Marcelo Funes", "MP-60110", d(60), "Tratamiento prolongado", 3, 1, d(10), "Vigente"),   # q06: próxima dispensa vencida
        ("RC011", "C017", "Dr. Marcelo Funes", "MP-60110", d(45), "Tratamiento prolongado", 2, 1, d(3), "Vigente"),    # q06: próxima dispensa vencida
        ("RC012", "C017", "Dra. Elena Barrios", "MP-61220", d(20), "Simple", 1, 1, "", "Completada"),
        ("RC013", "C009", "Dr. Hernán Vidal", "MP-62330", d(30), "Tratamiento prolongado", 3, 1, f(10), "Vigente"),    # próxima dispensa futura
        ("RC014", "C010", "Dra. Sandra Quiroz", "MP-63440", d(15), "Simple", 1, 0, "", "Vigente"),
        ("RC015", "C011", "Dr. Ignacio Paredes", "MP-64550", d(5), "Archivada", 1, 0, "", "Vigente"),
        ("RC016", "C014", "Dra. Julia Ferrero", "MP-65660", d(120), "Simple", 1, 0, "", "Vencida"),
        ("RC017", "C009", "Dr. Hernán Vidal", "MP-62330", hoy_iso, "Simple", 1, 1, "", "Completada"),
        ("RC018", "C013", "Dr. Ricardo Salomón", "MP-66770", d(90), "Tratamiento prolongado", 3, 3, "", "Completada"),
        ("RC019", "C012", "Dra. Sandra Quiroz", "MP-63440", d(8), "Simple", 1, 0, "", "Vigente"),                      # cliente inactivo
    ])

    stock_lotes = _rows(FILES["stock_lotes"], [
        ("L019", "PRD014", "S001", "L-2602A", 30, f(120)),   # FEFO: 3 lotes del mismo producto; sale primero el que vence antes
        ("L020", "PRD014", "S001", "L-2603B", 60, f(400)),
        ("L021", "PRD014", "S001", "L-2604C", 200, f(700)),
        ("L022", "PRD015", "S002", "L-2605A", 12, f(250)),   # < 50
        ("L023", "PRD016", "S003", "L-2606D", 25, f(300)),   # < 50, bajo receta archivada
        ("L024", "PRD017", "S001", "L-2501X", 45, d(30)),    # vencido
        ("L025", "PRD019", "S006", "L-2607F", 8, f(25)),     # < 50 y próximo a vencer
        ("L026", "PRD018", "S007", "L-2608G", 300, f(500)),
        ("L027", "PRD020", "S008", "L-2609H", 49, f(60)),    # límite: 49 entra en q08
        ("L028", "PRD022", "S001", "L-2610J", 50, f(90)),    # límite: 50 no entra en q08
    ])

    # Ventas: (id, cliente, farmacéutico, receta, fecha, tipo, medio, estado, [(producto, cantidad)])
    L, R = "Venta libre", "Con receta"
    ventas_def = [
        ("V017", "C009", "F008", "RC017", hoy_iso, R, "Obra social", "Completada", [("PRD015", 1)]),
        ("V018", "C011", "F008", "", mes, L, "Efectivo", "Completada", [("PRD014", 1), ("PRD018", 2)]),
        ("V019", "C014", "F016", "", mes, L, "Débito", "Completada", [("PRD020", 1)]),          # farmacéutica inactiva, mes actual (q11)
        ("V020", "C009", "F010", "RC013", d(30), R, "Obra social", "Completada", [("PRD019", 1)]),
        ("V021", "C010", "F011", "", d(40), L, "Débito", "Completada", [("PRD022", 2)]),
        ("V022", "C013", "F012", "", d(15), L, "Efectivo", "Completada", [("PRD018", 1)]),       # libre < 5000 (q09)
        ("V023", "C011", "F009", "", d(50), L, "Débito", "Completada", [("PRD014", 1)]),        # libre < 5000 (q09)
        ("V024", "C010", "F009", "RC014", hoy_iso, R, "Débito", "Pendiente", [("PRD015", 2)]),   # pendiente (q02)
        ("V025", "C017", "F012", "", d(1), L, "Transferencia", "Pendiente", [("PRD020", 2)]),    # pendiente (q02)
        ("V026", "C014", "F014", "", d(10), L, "Efectivo", "Anulada", [("PRD022", 3)]),          # anulada: excluir en q05, q07, q09, q11
        ("V027", "C009", "F008", "", d(12), L, "Débito", "Anulada", [("PRD018", 1)]),            # anulada < 5000: excluir en q09
        ("V028", "C017", "F014", "RC012", d(20), R, "Obra social", "Completada", [("PRD017", 1)]),
        ("V029", "C010", "F010", "", d(200), L, "Crédito", "Completada", [("PRD014", 2), ("PRD018", 1)]),  # último año, fuera de 60 días
        ("V030", "C018", "F014", "", d(400), L, "Efectivo", "Completada", [("PRD022", 1)]),      # más de un año (q12)
        ("V031", "C011", "F011", "", d(60), L, "Débito", "Completada", [("PRD014", 1)]),         # borde: hace exactamente 60 días
        ("V032", "C011", "F011", "", d(61), L, "Débito", "Completada", [("PRD018", 1)]),         # borde: hace 61 días
    ]
    ventas: list[dict[str, Any]] = []
    detalle: list[dict[str, Any]] = []
    n_det = 22  # el último detalle original es D022
    for vid, cli, farm, rec, fecha, tipo, medio, estado, items in ventas_def:
        total = 0
        for prod, cant in items:
            n_det += 1
            total += cant * precio[prod]
            detalle.append(dict(zip(FILES["detalle_ventas"], (f"D{n_det:03d}", vid, prod, cant, precio[prod]))))
        ventas.append(dict(zip(FILES["ventas"], (vid, cli, farm, rec, fecha, tipo, medio, total, estado))))

    return {
        "clientes": clientes, "sucursales": sucursales, "farmaceuticos": farmaceuticos,
        "proveedores": proveedores, "productos": productos, "stock_lotes": stock_lotes,
        "recetas": recetas, "ventas": ventas, "detalle_ventas": detalle,
    }


def escribir_csv(directorio: Path, base: date) -> dict[str, int]:
    """Escribe los nueve CSV adicionales en ``directorio`` (sobrescribe) y devuelve sus conteos."""
    directorio.mkdir(parents=True, exist_ok=True)
    conteos: dict[str, int] = {}
    for nombre, filas in generar(base).items():
        with (directorio / f"{nombre}.csv").open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=FILES[nombre], lineterminator="\n")
            writer.writeheader()
            writer.writerows(filas)
        conteos[nombre] = len(filas)
    return conteos
