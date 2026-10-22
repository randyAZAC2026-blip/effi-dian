"""Conversión opcional de los valores de Effi, que llegan como texto ("357000.0000", "22")."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def a_decimal(valor: Any) -> Decimal:
    if valor is None or valor == "":
        return Decimal(0)
    try:
        return Decimal(str(valor))
    except InvalidOperation:
        return Decimal(0)


def a_int(valor: Any) -> int | None:
    if valor is None or valor == "":
        return None
    try:
        return int(Decimal(str(valor)))
    except (InvalidOperation, ValueError):
        return None


def es_si(valor: Any) -> bool:
    """Banderas de Effi ("1", 1, "true")."""
    return str(valor).strip().lower() in {"1", "true", "si", "sí"}


def campo(registro: dict, *nombres: str, defecto: Any = None) -> Any:
    """El primer campo presente y no vacío (los nombres pueden variar entre recursos)."""
    for nombre in nombres:
        valor = registro.get(nombre)
        if valor not in (None, ""):
            return valor
    return defecto
