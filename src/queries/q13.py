"""q13 — ABM completo de clientes (servicio de escritura sobre MongoDB)."""

from __future__ import annotations

import re
from typing import Any

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from src.infrastructure.mongo import get_shared_db
from src.services.exceptions import (
    DNI_DUPLICADO,
    NO_ENCONTRADO,
    VALIDACION_ERROR,
    DomainError,
)
from src.services.transactions import ejecutar_en_transaccion

ACCIONES = ("alta", "modificacion", "baja")
OBLIGATORIOS_ALTA = ("nombre", "apellido", "dni", "ciudad", "provincia", "obra_social")
OPCIONALES = ("email", "telefono", "nro_afiliado")
MODIFICABLES = ("email", "telefono", "obra_social", "nro_afiliado")
NO_MODIFICABLES = ("nombre", "apellido", "dni", "ciudad", "provincia")


def _limpiar(valor: Any) -> str | None:
    """Recorta espacios; ``None`` si no se informó (``None``) y ``""`` si quedó vacío."""
    if valor is None:
        return None
    return str(valor).strip()


def _error(mensaje: str, **detalles: Any) -> DomainError:
    return DomainError(VALIDACION_ERROR, mensaje, 400, detalles or None)


def _validar_formatos(datos: dict[str, str | None]) -> None:
    dni = datos.get("dni")
    if dni and not re.fullmatch(r"\d{6,9}", dni):
        raise _error("El DNI debe tener entre 6 y 9 dígitos, sin puntos.", campo="dni")
    email = datos.get("email")
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise _error("El email no tiene un formato válido.", campo="email")
    telefono = datos.get("telefono")
    if telefono and not re.fullmatch(r"\d{6,15}", telefono):
        raise _error("El teléfono debe tener solo dígitos (6 a 15).", campo="telefono")


def _alta(db: Any, client: Any, datos: dict[str, str | None]) -> dict[str, Any]:
    faltan = [c for c in OBLIGATORIOS_ALTA if not datos.get(c)]
    if faltan:
        raise _error("Faltan datos obligatorios para el alta.", campos=faltan)
    _validar_formatos(datos)
    documento_base = {c: datos[c] for c in OBLIGATORIOS_ALTA}
    for campo in OPCIONALES:
        documento_base[campo] = datos.get(campo) or None

    def operacion(session: Any) -> dict[str, Any]:
        contador = db["contadores"].find_one_and_update(
            {"_id": "cliente"}, {"$inc": {"valor": 1}}, return_document=ReturnDocument.AFTER, session=session
        )
        id_cliente = f"C{contador['valor']:03d}"
        documento = {"_id": id_cliente, **documento_base, "activo": True}
        db["clientes"].insert_one(documento, session=session)
        return documento

    try:
        creado = ejecutar_en_transaccion(client, operacion)
    except DuplicateKeyError as exc:
        raise DomainError(
            DNI_DUPLICADO, f"Ya existe un cliente con DNI {datos['dni']}.", 409, {"dni": datos["dni"]}
        ) from exc
    return {"accion": "alta", "antes": None, "despues": creado, "cambio": True}


def _modificacion(db: Any, client: Any, id_cliente: str | None, datos: dict[str, str | None]) -> dict[str, Any]:
    if not id_cliente:
        raise _error("La modificación requiere id_cliente.", campo="id_cliente")
    prohibidos = [c for c in NO_MODIFICABLES if datos.get(c) is not None]
    if prohibidos:
        raise _error(
            "Solo se pueden modificar email, telefono, obra_social y nro_afiliado.",
            campos_no_modificables=prohibidos,
        )
    cambios: dict[str, str | None] = {}
    for campo in MODIFICABLES:
        valor = datos.get(campo)
        if valor is None:
            continue
        if campo == "obra_social" and not valor:
            raise _error("obra_social no puede quedar vacía.", campo=campo)
        cambios[campo] = valor or None  # cadena vacía en un opcional = limpiar (null)
    if cambios.get("obra_social") == "Sin cobertura":
        cambios["nro_afiliado"] = None  # sin cobertura no hay número de afiliado
    if not cambios:
        raise _error("No se informó ningún dato a modificar.", modificables=list(MODIFICABLES))
    _validar_formatos({c: v for c, v in cambios.items() if v})

    def operacion(session: Any) -> dict[str, Any]:
        antes = db["clientes"].find_one({"_id": id_cliente}, session=session)
        if antes is None:
            raise DomainError(NO_ENCONTRADO, f"No existe el cliente {id_cliente}.", 404, {"id_cliente": id_cliente})
        despues = db["clientes"].find_one_and_update(
            {"_id": id_cliente}, {"$set": cambios}, return_document=ReturnDocument.AFTER, session=session
        )
        return {"accion": "modificacion", "antes": antes, "despues": despues, "cambio": antes != despues}

    return ejecutar_en_transaccion(client, operacion)


def _baja(db: Any, client: Any, id_cliente: str | None) -> dict[str, Any]:
    if not id_cliente:
        raise _error("La baja requiere id_cliente.", campo="id_cliente")

    def operacion(session: Any) -> dict[str, Any]:
        antes = db["clientes"].find_one({"_id": id_cliente}, session=session)
        if antes is None:
            raise DomainError(NO_ENCONTRADO, f"No existe el cliente {id_cliente}.", 404, {"id_cliente": id_cliente})
        if not antes["activo"]:
            return {"accion": "baja", "antes": antes, "despues": antes, "cambio": False}  # ya estaba de baja
        despues = db["clientes"].find_one_and_update(
            {"_id": id_cliente}, {"$set": {"activo": False}}, return_document=ReturnDocument.AFTER, session=session
        )
        return {"accion": "baja", "antes": antes, "despues": despues, "cambio": True}

    return ejecutar_en_transaccion(client, operacion)


def ejecutar(
    accion: str,
    id_cliente: str | None = None,
    nombre: str | None = None,
    apellido: str | None = None,
    dni: str | None = None,
    email: str | None = None,
    telefono: str | None = None,
    ciudad: str | None = None,
    provincia: str | None = None,
    obra_social: str | None = None,
    nro_afiliado: str | None = None,
    *,
    db: Any = None,
) -> dict[str, Any]:
    """Punto de entrada compartido por la API, la CLI y los tests. ``db`` permite inyectar otra base."""
    accion = (accion or "").strip().lower()
    if accion not in ACCIONES:
        raise _error("accion debe ser alta, modificacion o baja.", accion=accion, validas=list(ACCIONES))
    base = db if db is not None else get_shared_db()
    client = base.client
    datos = {k: _limpiar(v) for k, v in dict(
        nombre=nombre, apellido=apellido, dni=dni, email=email, telefono=telefono, ciudad=ciudad,
        provincia=provincia, obra_social=obra_social, nro_afiliado=nro_afiliado).items()}
    id_cliente = _limpiar(id_cliente) or None
    if accion == "alta":
        return _alta(base, client, datos)
    if accion == "modificacion":
        return _modificacion(base, client, id_cliente, datos)
    return _baja(base, client, id_cliente)
