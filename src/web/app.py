"""Aplicación FastAPI principal para el backoffice políglota de FarmaRed S.A."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.clock import AR_TZ, format_iso_date, hoy
from src.infrastructure.config import get_settings
from src.infrastructure.mongo import check_mongo_health
from src.infrastructure.redis_client import check_redis_health
from src.queries import EJECUTORES
from src.queries.catalog import QUERIES_CATALOG, get_query_metadata
from src.services.exceptions import NO_ENCONTRADO, VALIDACION_ERROR, DomainError
from src.services.serialization import a_json

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(
    title="FarmaRed S.A. — Sistema Backoffice Políglota",
    version="0.1.0",
    description="API HTTP y Consola Web de FarmaRed S.A. con MongoDB (Replica Set rs0) y Redis.",
)


@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    """Serializa errores de dominio con código, mensaje y detalles estructurados."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            }
        },
    )


def _to_plain_dict(value: Any) -> dict[str, Any]:
    """Convierte metadatos de consulta (dict, Pydantic o dataclass) a dict JSON-serializable."""
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if is_dataclass(value):
        return asdict(value)
    return dict(vars(value))


def _resolve_query_metadata(query_id: str) -> dict[str, Any] | None:
    """Resuelve una consulta en el catálogo tolerando variantes de mayúsculas y ceros a la izquierda."""
    raw = query_id.strip()
    lowered = raw.lower()
    candidates = [raw, lowered, raw.upper()]
    if lowered.startswith("q") and lowered[1:].isdigit():
        num = int(lowered[1:])
        candidates.extend([f"q{num:02d}", f"Q{num:02d}", f"q{num}", f"Q{num}"])

    seen: set[str] = set()
    last_domain_error: DomainError | None = None
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            meta = get_query_metadata(candidate)
        except (KeyError, LookupError):
            meta = None
        except DomainError as exc:
            last_domain_error = exc
            meta = None
        if meta is not None:
            return _to_plain_dict(meta)

    if last_domain_error is not None:
        raise last_domain_error
    return None


@app.get(
    "/api/health",
    tags=["Sistema"],
    summary="Estado de salud de los motores y fecha de negocio",
)
def get_health() -> dict[str, Any]:
    """Verifica el estado de MongoDB (rs0) y Redis junto a la fecha de negocio local."""
    mongo = check_mongo_health()
    redis = check_redis_health()
    return {
        "status": "ok" if mongo["status"] == "ok" else "degraded",
        "business_date": format_iso_date(hoy()),
        "timezone": str(AR_TZ),
        "mongodb": mongo,
        "redis": redis,
    }


@app.get(
    "/api/architecture",
    tags=["Arquitectura"],
    summary="Modelo políglota, colecciones MongoDB, claves Redis y estrategia ACID",
)
def get_architecture() -> dict[str, Any]:
    """Devuelve la descripción técnica de motores, colecciones, claves Redis y consistencia."""
    settings = get_settings()
    database_name = settings.mongodb_db
    cache_ttl = settings.redis_ttl_seconds
    redis_prefix = settings.redis_prefix

    return {
        "project": "FarmaRed S.A.",
        "architecture": "Persistencia Políglota NoSQL (MongoDB + Redis)",
        "database": database_name,
        "motors": {
            "mongodb": {
                "name": "MongoDB",
                "paradigm": "Documental",
                "deployment": "Replica Set rs0",
                "role": "Fuente de verdad autoritativa",
                "acid_transactions": True,
                "collections_count": 9,
                "justification": (
                    "Almacena todas las entidades de negocio, incluyendo stock_lotes, "
                    "ventas con items embebidos y contadores. Permite agregaciones, "
                    "índices únicos y transacciones multi-documento ACID en rs0 para Q14–Q15."
                ),
                "why_stock_in_mongodb": (
                    "Mantener stock_lotes en MongoDB permite descontar lotes FEFO dentro "
                    "de la misma transacción ACID que inserta la venta y actualiza la receta, "
                    "evitando sagas distribuidas y compensaciones manuales."
                ),
            },
            "redis": {
                "name": "Redis",
                "paradigm": "Clave-Valor (en memoria)",
                "deployment": "Standalone (cache-aside)",
                "role": "Caché de referencia de catálogo y proveedores para Q1 y Q8",
                "ttl_seconds": cache_ttl,
                "fallback": (
                    "Si Redis no responde o excede el timeout, Q1 y Q8 continúan leyendo "
                    "directamente desde MongoDB sin comprometer disponibilidad ni integridad."
                ),
                "justification": (
                    "Segundo paradigma NoSQL optimizado para lecturas frecuentes de productos "
                    "y proveedores con expiración por TTL. Nunca almacena stock autoritativo "
                    "ni comprobantes de operaciones de venta."
                ),
            },
        },
        "collections": [
            {
                "name": "clientes",
                "role": "Maestro de clientes y cobertura médica con baja lógica (activo) y DNI único.",
                "id_strategy": "_id string de dominio (ej. C001)",
                "key_fields": [
                    "_id",
                    "nombre",
                    "apellido",
                    "dni",
                    "email?",
                    "telefono?",
                    "ciudad",
                    "provincia",
                    "obra_social",
                    "nro_afiliado?",
                    "activo",
                ],
                "relations": ["Referenciada por recetas.id_cliente y ventas.id_cliente (1:N)"],
                "indexes": ["{dni: 1} (unique)"],
            },
            {
                "name": "sucursales",
                "role": "Red de sucursales (Farmacia minorista y Droguería central de abastecimiento).",
                "id_strategy": "_id string de dominio (ej. S001)",
                "key_fields": [
                    "_id",
                    "nombre",
                    "tipo (Farmacia|Droguería)",
                    "direccion",
                    "ciudad",
                    "provincia",
                    "telefono",
                    "activo",
                ],
                "relations": ["Referenciada por farmaceuticos.id_sucursal y stock_lotes.id_sucursal (1:N)"],
                "indexes": ["_id único nativo"],
            },
            {
                "name": "farmaceuticos",
                "role": "Profesionales matriculados asignados a una única sucursal.",
                "id_strategy": "_id string de dominio (ej. F001)",
                "key_fields": [
                    "_id",
                    "nombre",
                    "apellido",
                    "matricula",
                    "cargo (Director Técnico|Farmacéutico)",
                    "id_sucursal",
                    "activo",
                ],
                "relations": [
                    "id_sucursal -> sucursales._id (N:1)",
                    "Referenciada por ventas.id_farmaceutico (1:N)",
                ],
                "indexes": ["{matricula: 1} (unique)", "{id_sucursal: 1}"],
            },
            {
                "name": "proveedores",
                "role": "Laboratorios y droguerías proveedoras del catálogo (cacheados en Redis para Q1/Q8).",
                "id_strategy": "_id string de dominio (ej. PRV001)",
                "key_fields": [
                    "_id",
                    "razon_social",
                    "cuit",
                    "tipo (Laboratorio|Droguería)",
                    "ciudad",
                    "provincia",
                    "telefono",
                    "activo",
                ],
                "relations": ["Referenciada por productos.id_proveedor (1:N)"],
                "indexes": ["_id único nativo"],
            },
            {
                "name": "productos",
                "role": "Catálogo de medicamentos y condición de venta (cacheados en Redis para Q1/Q8).",
                "id_strategy": "_id string de dominio (ej. PRD001)",
                "key_fields": [
                    "_id",
                    "nombre",
                    "principio_activo",
                    "categoria",
                    "presentacion",
                    "condicion_venta",
                    "precio_unit (int ARS)",
                    "id_proveedor",
                    "activo",
                ],
                "relations": [
                    "id_proveedor -> proveedores._id (N:1)",
                    "Referenciada por stock_lotes.id_producto y ventas.items[].id_producto",
                ],
                "indexes": ["{activo: 1}"],
            },
            {
                "name": "recetas",
                "role": "Recetas médicas (Simple, Archivada, Tratamiento prolongado) y control de dispensas.",
                "id_strategy": "_id string de dominio (ej. RC001)",
                "key_fields": [
                    "_id",
                    "id_cliente",
                    "medico",
                    "matricula_medico",
                    "fecha_emision",
                    "tipo",
                    "dispensas_autorizadas",
                    "dispensas_realizadas",
                    "proxima_dispensa?",
                    "estado (Vigente|Completada|Vencida)",
                ],
                "relations": [
                    "id_cliente -> clientes._id (N:1)",
                    "Referenciada opcionalmente por ventas.id_receta (1:N)",
                ],
                "indexes": [
                    "{id_cliente: 1, fecha_emision: 1}",
                    "{tipo: 1, estado: 1, proxima_dispensa: 1}",
                ],
            },
            {
                "name": "stock_lotes",
                "role": "Inventario por lote, producto y sucursal con vencimiento para FEFO determinista.",
                "id_strategy": "_id string de dominio (ej. L001)",
                "key_fields": [
                    "_id",
                    "id_producto",
                    "id_sucursal",
                    "nro_lote",
                    "unidades (>= 0)",
                    "vencimiento (date)",
                ],
                "relations": [
                    "id_producto -> productos._id (N:1)",
                    "id_sucursal -> sucursales._id (N:1)",
                ],
                "indexes": [
                    "{id_producto: 1, id_sucursal: 1, vencimiento: 1, _id: 1} (FEFO)",
                    "{unidades: 1}",
                ],
            },
            {
                "name": "ventas",
                "role": "Cabecera de ventas con detalle embebido (items[]), trazabilidad FEFO e idempotencia.",
                "id_strategy": "_id string de dominio (ej. V001)",
                "key_fields": [
                    "_id",
                    "id_cliente",
                    "id_farmaceutico",
                    "id_receta?",
                    "fecha",
                    "tipo",
                    "medio_pago",
                    "total",
                    "estado",
                    "origen",
                    "id_operacion?",
                    "huella_solicitud?",
                    "stock_aplicado",
                    "asignaciones_stock[]",
                    "items[] (id_detalle, id_producto, nombre_producto, cantidad, precio_unit)",
                ],
                "relations": [
                    "id_cliente -> clientes._id (N:1)",
                    "id_farmaceutico -> farmaceuticos._id (N:1)",
                    "id_receta -> recetas._id (N:1 opcional)",
                    "items embebidos (detalle_ventas fusionado sin colección duplicada)",
                ],
                "indexes": [
                    "{id_cliente: 1, fecha: 1}",
                    "{id_farmaceutico: 1, fecha: 1, estado: 1}",
                    "{estado: 1, fecha: 1}",
                    "{tipo: 1, total: 1}",
                    "{id_operacion: 1} (unique parcial para strings)",
                ],
            },
            {
                "name": "contadores",
                "role": "Secuencias atómicas transaccionales para generar IDs de venta, cliente y detalle.",
                "id_strategy": "_id fijo: 'venta' | 'cliente' | 'detalle'",
                "key_fields": ["_id", "valor (integer)"],
                "relations": ["Consumida dentro de transacciones en Q13 (cliente) y Q14 (venta y detalle)"],
                "indexes": ["_id único nativo"],
            },
        ],
        "redis_keys": [
            {
                "pattern": f"{redis_prefix}producto:<id_producto>",
                "type": "STRING JSON",
                "ttl_seconds": cache_ttl,
                "used_in": ["Q1", "Q8"],
                "authoritative_source": "MongoDB (productos)",
                "invalidation": "Invalidada por seed.py al recargar; expira por TTL.",
            },
            {
                "pattern": f"{redis_prefix}proveedor:<id_proveedor>",
                "type": "STRING JSON",
                "ttl_seconds": cache_ttl,
                "used_in": ["Q1", "Q8"],
                "authoritative_source": "MongoDB (proveedores)",
                "invalidation": "Invalidada por seed.py al recargar; expira por TTL.",
            },
        ],
        "consistency_strategy": {
            "summary": (
                "Q14 y Q15 ejecutan validación de negocio, actualización de receta, generación de IDs "
                "y descuento FEFO dentro de una única transacción multi-documento en MongoDB "
                "(session.with_transaction), sin saga distribuida ni compensaciones sobre Redis."
            ),
            "transaction_mechanism": "PyMongo ClientSession.with_transaction() en Replica Set rs0",
            "fefo_rule": (
                "Selecciona lotes de la sucursal del farmacéutico con unidades > 0 y vencimiento >= hoy "
                "(el vencimiento en el día corriente sigue vigente), ordenados determinísticamente por "
                "(vencimiento ASC, _id ASC). Descuenta con condición unidades >= cantidad; si falta stock "
                "para cualquier ítem, aborta la transacción completa sin dejar venta ni cambios de receta."
            ),
            "idempotency": (
                "Q14 recibe un id_operacion estable (UUID persistido en localStorage para reintentos web) "
                "y calcula huella_solicitud normalizada. El índice único parcial sobre ventas.id_operacion "
                "garantiza una única venta por operación; si coincide la huella devuelve la venta confirmada "
                "sin duplicar descuentos y si difiere rechaza el conflicto."
            ),
            "no_distributed_saga": (
                "Al residir stock_lotes, ventas, recetas y contadores dentro de MongoDB, no se requiere "
                "saga distribuida entre motores ni leases de inventario en Redis."
            ),
            "q15_standalone": (
                "Q15 independiente recibe id_venta y aplica FEFO en transacción sobre ventas Completadas "
                "de origen servicio con stock_aplicado = false (fixture técnico de prueba), sin volver "
                "a modificar la receta y devolviendo las asignaciones ya registradas si stock_aplicado = true."
            ),
        },
        "rejected_alternatives": [
            {
                "alternative": "Agregar Neo4j como 3er motor",
                "reason": (
                    "Duplicaría escrituras en cada alta de cliente y venta para consultas de alcance "
                    "acotado que MongoDB resuelve directamente con $lookup e índices."
                ),
            },
            {
                "alternative": "Mantener stock en Redis con Saga distribuida",
                "reason": (
                    "Introduciría compensaciones ante fallos parciales entre venta/receta y stock, "
                    "cuando una sola transacción ACID en MongoDB garantiza atomicidad nativa."
                ),
            },
        ],
    }


@app.get(
    "/api/queries",
    tags=["Consultas"],
    summary="Listado del catálogo Q1–Q15",
)
def list_queries() -> dict[str, Any]:
    """Devuelve todas las consultas y servicios registrados en el catálogo."""
    return {
        "queries": QUERIES_CATALOG,
        "total": len(QUERIES_CATALOG),
    }


@app.get(
    "/api/queries/{query_id}",
    tags=["Consultas"],
    summary="Ejecuta una consulta de lectura Q1–Q12 (o devuelve sus metadatos con ?meta=true)",
)
def get_query_detail(query_id: str, request: Request, meta: bool = False) -> Any:
    """Ejecuta la consulta con los parámetros de la URL; con ``meta=true`` solo devuelve el catálogo.

    Los servicios de escritura (Q13–Q15) no se ejecutan por GET: devuelven sus metadatos.
    HTTP 501 si la consulta todavía no está implementada.
    """
    entry = _resolve_query_metadata(query_id)
    if entry is None:
        raise DomainError(
            code="NO_ENCONTRADO",
            message=f"La consulta '{query_id}' no existe en el catálogo Q1–Q15.",
            status_code=404,
            details={"query_id": query_id},
        )

    if not entry.get("implemented", False):
        return JSONResponse(
            status_code=501,
            content={
                "status": "pending",
                "query": entry,
                "message": (
                    f"La consulta {query_id.upper()} forma parte de la Fase 3 "
                    "y aún no fue implementada en este hito inicial."
                ),
            },
        )

    ejecutor = EJECUTORES.get(entry["id"])
    if meta or entry.get("method") != "GET" or ejecutor is None:
        return {"status": "ready", "query": entry}

    # Solo se aceptan los parámetros declarados en el catálogo; cualquier otro es un error del cliente.
    recibidos = {k: v for k, v in request.query_params.items() if k != "meta"}
    desconocidos = sorted(set(recibidos) - set(entry["parameters"]))
    if desconocidos:
        raise DomainError(
            VALIDACION_ERROR,
            f"Parámetros no válidos: {', '.join(desconocidos)}.",
            400,
            {"validos": entry["parameters"]},
        )
    try:
        resultado = ejecutor(**recibidos)
    except TypeError as exc:  # p. ej. falta un parámetro obligatorio
        raise DomainError(
            VALIDACION_ERROR,
            f"Parámetros inválidos ({exc}).",
            400,
            {"validos": entry["parameters"]},
        ) from exc
    return {"status": "ok", "query": entry["id"], "result": a_json(resultado)}


class ClienteRequest(BaseModel):
    """Cuerpo de q13. Los campos no modificables se aceptan y el servicio los rechaza con un error de dominio."""

    accion: str
    id_cliente: str | None = None
    nombre: str | None = None
    apellido: str | None = None
    dni: str | None = None
    email: str | None = None
    telefono: str | None = None
    ciudad: str | None = None
    provincia: str | None = None
    obra_social: str | None = None
    nro_afiliado: str | None = None


@app.post(
    "/api/services/clientes",
    tags=["Servicios"],
    summary="q13 — ABM de clientes (alta, modificación y baja lógica)",
)
def post_clientes(body: ClienteRequest) -> JSONResponse:
    """Alta (201), modificación o baja lógica de un cliente; devuelve el estado antes y después."""
    resultado = EJECUTORES["q13"](**body.model_dump())
    codigo = 201 if resultado["accion"] == "alta" else 200
    return JSONResponse(status_code=codigo, content={"status": "ok", **a_json(resultado)})


@app.get(
    "/api/services/clientes/{id_cliente}",
    tags=["Servicios"],
    summary="Consulta un cliente por ID (para ver el estado antes/después de q13)",
)
def get_cliente(id_cliente: str) -> dict[str, Any]:
    """Devuelve el documento del cliente o 404."""
    from src.infrastructure.mongo import get_shared_db

    cliente = get_shared_db()["clientes"].find_one({"_id": id_cliente})
    if cliente is None:
        raise DomainError(NO_ENCONTRADO, f"No existe el cliente {id_cliente}.", 404, {"id_cliente": id_cliente})
    return a_json(cliente)


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def serve_console() -> FileResponse:
    """Sirve la consola web estática principal."""
    return FileResponse(STATIC_DIR / "index.html")
