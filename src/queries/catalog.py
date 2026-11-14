"""Catálogo declarativo de las 15 consultas y servicios (Q1–Q15) de FarmaRed S.A."""

from __future__ import annotations

from typing import Any

QUERIES_CATALOG: list[dict[str, Any]] = [
    {
        "id": "q01",
        "number": 1,
        "title": "Productos activos con proveedor",
        "type": "Lectura",
        "method": "GET",
        "endpoint": "/api/queries/q01",
        "engines": ["MongoDB", "Redis"],
        "description": "Productos activos con todos los datos de su proveedor.",
        "relations_strategy": (
            "Consulta IDs de productos activos en MongoDB y resuelve cada producto y su "
            "proveedor mediante caché cache-aside en Redis (farmared:producto:<id>, "
            "farmared:proveedor:<id>) con fallback a MongoDB sin filtrar la actividad del proveedor."
        ),
        "parameters": [],
        "implemented": False,
    },
    {
        "id": "q02",
        "number": 2,
        "title": "Ventas pendientes con farmacéutico y sucursal",
        "type": "Lectura",
        "method": "GET",
        "endpoint": "/api/queries/q02",
        "engines": ["MongoDB"],
        "description": (
            "Ventas en estado 'Pendiente' con el farmacéutico asignado "
            "(nombre, matrícula y sucursal) y el total."
        ),
        "relations_strategy": (
            "Agregación en MongoDB filtrando estado = 'Pendiente' y resolviendo el cruce "
            "con farmaceuticos y sucursales mediante $lookup."
        ),
        "parameters": [],
        "implemented": False,
    },
    {
        "id": "q03",
        "number": 3,
        "title": "Historial cronológico de cliente",
        "type": "Lectura",
        "method": "GET",
        "endpoint": "/api/queries/q03",
        "engines": ["MongoDB"],
        "description": (
            "Historial completo de un cliente (dado su id): ventas y recetas ordenadas "
            "cronológicamente por fecha."
        ),
        "relations_strategy": (
            "Consulta ventas (con ítems embebidos) y recetas por id_cliente en MongoDB, "
            "unificadas en orden cronológico usando fecha y fecha_emision con tipo e ID como desempate."
        ),
        "parameters": ["id_cliente"],
        "implemented": False,
    },
    {
        "id": "q04",
        "number": 4,
        "title": "Clientes con más de una receta",
        "type": "Agregación",
        "method": "GET",
        "endpoint": "/api/queries/q04",
        "engines": ["MongoDB"],
        "description": "Clientes con más de una receta registrada, indicando la cantidad.",
        "relations_strategy": (
            "Agregación en MongoDB sobre recetas ($group por id_cliente, $match cantidad > 1) "
            "y enriquecimiento de datos del cliente con $lookup hacia clientes."
        ),
        "parameters": [],
        "implemented": False,
    },
    {
        "id": "q05",
        "number": 5,
        "title": "Ventas por farmacéutico activo (últimos 60 días)",
        "type": "Agregación",
        "method": "GET",
        "endpoint": "/api/queries/q05",
        "engines": ["MongoDB"],
        "description": (
            "Farmacéuticos activos y cantidad de ventas registradas en los últimos 60 días "
            "(excluyendo anuladas). Deben aparecer también los que tienen cero."
        ),
        "relations_strategy": (
            "Agregación partiendo de farmaceuticos (activo = true) con $lookup hacia ventas "
            "en [hoy - 60 días, hoy] excluyendo estado = 'Anulada', preservando los ceros."
        ),
        "parameters": [],
        "implemented": False,
    },
    {
        "id": "q06",
        "number": 6,
        "title": "Recetas prolongadas con próxima dispensa vencida",
        "type": "Lectura",
        "method": "GET",
        "endpoint": "/api/queries/q06",
        "engines": ["MongoDB"],
        "description": (
            "Recetas de tratamiento prolongado en estado 'Vigente' cuya próxima dispensa "
            "es anterior a hoy, con los datos del cliente."
        ),
        "relations_strategy": (
            "Consulta en MongoDB sobre recetas (tipo = 'Tratamiento prolongado', estado = 'Vigente', "
            "proxima_dispensa != null y < hoy) con $lookup hacia clientes."
        ),
        "parameters": [],
        "implemented": False,
    },
    {
        "id": "q07",
        "number": 7,
        "title": "Top 5 productos más vendidos",
        "type": "Agregación",
        "method": "GET",
        "endpoint": "/api/queries/q07",
        "engines": ["MongoDB"],
        "description": (
            "Top 5 productos más vendidos (unidades), considerando solo ventas 'Completada'."
        ),
        "relations_strategy": (
            "Agregación en MongoDB sobre ventas (estado = 'Completada') con $unwind sobre "
            "items embebidos, $group sumando cantidades, desempate por id_producto y $lookup a productos."
        ),
        "parameters": [],
        "implemented": False,
    },
    {
        "id": "q08",
        "number": 8,
        "title": "Lotes con menos de 50 unidades",
        "type": "Lectura",
        "method": "GET",
        "endpoint": "/api/queries/q08",
        "engines": ["MongoDB", "Redis"],
        "description": "Lotes con menos de 50 unidades, indicando producto, sucursal y proveedor.",
        "relations_strategy": (
            "Consulta en MongoDB sobre stock_lotes (unidades < 50, incluyendo cero y vencidos); "
            "enriquecimiento de producto y proveedor mediante caché cache-aside en Redis "
            "(con fallback a MongoDB) y sucursal desde MongoDB."
        ),
        "parameters": [],
        "implemented": False,
    },
    {
        "id": "q09",
        "number": 9,
        "title": "Ventas libres menores a $5.000",
        "type": "Lectura",
        "method": "GET",
        "endpoint": "/api/queries/q09",
        "engines": ["MongoDB"],
        "description": (
            "Ventas de tipo 'Venta libre' con total menor a $5.000 (excluyendo anuladas)."
        ),
        "relations_strategy": (
            "Consulta directa en MongoDB sobre ventas filtrando tipo = 'Venta libre', "
            "total < 5000 y estado != 'Anulada', aprovechando los ítems embebidos en el documento."
        ),
        "parameters": [],
        "implemented": False,
    },
    {
        "id": "q10",
        "number": 10,
        "title": "Clientes atendidos en una sucursal",
        "type": "Lectura",
        "method": "GET",
        "endpoint": "/api/queries/q10",
        "engines": ["MongoDB"],
        "description": (
            "Todos los clientes atendidos en una sucursal determinada (a través del farmacéutico "
            "que registró la venta, esté activo o no)."
        ),
        "relations_strategy": (
            "Agregación en MongoDB partiendo de farmaceuticos filtrados por id_sucursal "
            "(sin filtrar activo) con $lookup hacia ventas y clientes, agrupando clientes distintos."
        ),
        "parameters": ["id_sucursal"],
        "implemented": False,
    },
    {
        "id": "q11",
        "number": 11,
        "title": "Ingresos por farmacéutico en el mes actual",
        "type": "Agregación",
        "method": "GET",
        "endpoint": "/api/queries/q11",
        "engines": ["MongoDB"],
        "description": (
            "Vista agregada: ingresos totales por farmacéutico en el mes actual "
            "(solo ventas 'Completada')."
        ),
        "relations_strategy": (
            "Agregación en MongoDB sobre ventas (estado = 'Completada' y fecha dentro del mes "
            "actual), agrupando por id_farmaceutico y resolviendo datos del profesional con $lookup "
            "(incluyendo inactivos)."
        ),
        "parameters": [],
        "implemented": False,
    },
    {
        "id": "q12",
        "number": 12,
        "title": "Clientes sin ventas en el último año",
        "type": "Lectura",
        "method": "GET",
        "endpoint": "/api/queries/q12",
        "engines": ["MongoDB"],
        "description": "Clientes sin ventas registradas en el último año.",
        "relations_strategy": (
            "Consulta en MongoDB identificando clientes sin ventas registradas en la ventana "
            "[hoy - 1 año, hoy] (considerando también Pendientes y Anuladas como ventas registradas)."
        ),
        "parameters": [],
        "implemented": False,
    },
    {
        "id": "q13",
        "number": 13,
        "title": "ABM completo de clientes",
        "type": "Servicio",
        "method": "POST",
        "endpoint": "/api/services/clientes",
        "engines": ["MongoDB"],
        "description": (
            "ABM completo de clientes: alta (validando DNI único), modificación de datos de "
            "contacto y cobertura, y baja lógica."
        ),
        "relations_strategy": (
            "Escritura transaccional en MongoDB con índice único en dni, generación de ID por "
            "contadores, modificación restringida a email/telefono/obra_social/nro_afiliado "
            "y baja lógica (activo = false) preservando el DNI."
        ),
        "parameters": [
            "accion",
            "id_cliente",
            "nombre",
            "apellido",
            "dni",
            "email",
            "telefono",
            "ciudad",
            "provincia",
            "obra_social",
            "nro_afiliado",
        ],
        "implemented": False,
    },
    {
        "id": "q14",
        "number": 14,
        "title": "Registro de nueva venta integrada",
        "type": "Servicio",
        "method": "POST",
        "endpoint": "/api/services/ventas",
        "engines": ["MongoDB"],
        "description": (
            "Registro de una nueva venta 'Completada' (cabecera e ítems) con validación de: "
            "cliente existente y activo; farmacéutico existente, activo y de una sucursal tipo "
            "'Farmacia'; productos existentes y activos; y, para productos bajo receta, receta "
            "existente, vigente y del mismo cliente. El total se calcula a partir de los ítems "
            "y se actualiza la receta según las reglas de negocio."
        ),
        "relations_strategy": (
            "Transacción ACID multi-documento en MongoDB (Replica Set rs0) que integra "
            "contadores de IDs, validación autoritativa, descuento FEFO de stock_lotes, "
            "actualización de receta, inserción de venta con ítems embebidos e idempotencia "
            "por id_operacion."
        ),
        "parameters": [
            "id_cliente",
            "id_farmaceutico",
            "id_receta",
            "medio_pago",
            "items",
            "id_operacion",
        ],
        "implemented": False,
    },
    {
        "id": "q15",
        "number": 15,
        "title": "Descuento masivo de stock FEFO",
        "type": "Servicio",
        "method": "POST",
        "endpoint": "/api/services/stock/descontar",
        "engines": ["MongoDB"],
        "description": (
            "Actualización masiva del stock: dada una venta registrada, decrementar las unidades "
            "de cada producto del detalle en los lotes de la sucursal del farmacéutico, aplicando "
            "FEFO y omitiendo lotes vencidos. Si el stock vigente no alcanza para algún ítem, la "
            "operación completa se rechaza sin modificar ningún lote."
        ),
        "relations_strategy": (
            "Transacción ACID multi-documento en MongoDB sobre ventas y stock_lotes ordenados "
            "por vencimiento y _id (FEFO), con actualizaciones condicionales y marca idempotente "
            "stock_aplicado."
        ),
        "parameters": ["id_venta"],
        "implemented": False,
    },
]

_CATALOG_BY_ID: dict[str, dict[str, Any]] = {entry["id"]: entry for entry in QUERIES_CATALOG}


def _normalize_query_id(query_id: str) -> str:
    raw = str(query_id).strip().lower()
    if raw.startswith("q") and raw[1:].isdigit():
        return f"q{int(raw[1:]):02d}"
    if raw.isdigit():
        return f"q{int(raw):02d}"
    return raw


def get_query_metadata(query_id: str) -> dict[str, Any] | None:
    """Devuelve los metadatos de una consulta por su ID (ej. 'q01'), o `None` si no existe."""
    normalized = _normalize_query_id(query_id)
    entry = _CATALOG_BY_ID.get(normalized)
    return dict(entry) if entry is not None else None


__all__ = ["QUERIES_CATALOG", "get_query_metadata"]
