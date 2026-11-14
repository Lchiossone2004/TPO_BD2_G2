"""Excepciones tipadas y códigos de error estables del dominio FarmaRed."""

from __future__ import annotations

from typing import Any

CLIENTE_INACTIVO = "CLIENTE_INACTIVO"
RECETA_VENCIDA = "RECETA_VENCIDA"
RECETA_INVALIDA = "RECETA_INVALIDA"
STOCK_INSUFICIENTE = "STOCK_INSUFICIENTE"
DNI_DUPLICADO = "DNI_DUPLICADO"
FARMACEUTICO_INVALIDO = "FARMACEUTICO_INVALIDO"
SUCURSAL_INVALIDA = "SUCURSAL_INVALIDA"
PRODUCTO_INACTIVO = "PRODUCTO_INACTIVO"
OPERACION_CONFLICTO = "OPERACION_CONFLICTO"
NO_ENCONTRADO = "NO_ENCONTRADO"
VALIDACION_ERROR = "VALIDACION_ERROR"
NO_IMPLEMENTADO = "NO_IMPLEMENTADO"

ERROR_CODES: tuple[str, ...] = (
    CLIENTE_INACTIVO,
    RECETA_VENCIDA,
    RECETA_INVALIDA,
    STOCK_INSUFICIENTE,
    DNI_DUPLICADO,
    FARMACEUTICO_INVALIDO,
    SUCURSAL_INVALIDA,
    PRODUCTO_INACTIVO,
    OPERACION_CONFLICTO,
    NO_ENCONTRADO,
    VALIDACION_ERROR,
    NO_IMPLEMENTADO,
)


class DomainError(Exception):
    """Error de negocio o validación con código estable y código HTTP asociado."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        """Serializa el error a un diccionario apto para respuestas JSON y CLI."""
        return {
            "code": self.code,
            "message": self.message,
            "status_code": self.status_code,
            "details": self.details,
        }

    def __repr__(self) -> str:
        return (
            f"DomainError(code={self.code!r}, message={self.message!r}, "
            f"status_code={self.status_code!r})"
        )


__all__ = [
    "CLIENTE_INACTIVO",
    "DNI_DUPLICADO",
    "DomainError",
    "ERROR_CODES",
    "FARMACEUTICO_INVALIDO",
    "NO_ENCONTRADO",
    "NO_IMPLEMENTADO",
    "OPERACION_CONFLICTO",
    "PRODUCTO_INACTIVO",
    "RECETA_INVALIDA",
    "RECETA_VENCIDA",
    "STOCK_INSUFICIENTE",
    "SUCURSAL_INVALIDA",
    "VALIDACION_ERROR",
]
