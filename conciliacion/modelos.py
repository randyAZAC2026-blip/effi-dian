"""Tipos de la conciliación: el hallazgo, los parámetros y los datos del periodo."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

ALTA, MEDIA, BAJA = "Alta", "Media", "Baja"
ORDEN_SEVERIDAD = {ALTA: 0, MEDIA: 1, BAJA: 2}


@dataclass(frozen=True)
class Hallazgo:
    modulo: str
    control: str
    severidad: str
    documento: str
    tercero: str = ""
    nit: str = ""
    valor: Decimal = Decimal(0)
    fecha: date | None = None
    detalle: str = ""
    enlace: str = ""


@dataclass(frozen=True)
class Parametros:
    hoy: date = field(default_factory=date.today)
    dias_gracia_cufe: int = 2       # un CUFE/CUDE/CUNE puede tardar en llegar de SOENAC
    dias_gracia_radian: int = 10    # acuse/recibo pendiente
    tolerancia_valor: Decimal = Decimal(1)
    # Prefijos de numeración electrónica conocidos; además, todo prefijo que tenga alguna factura con ebill=1.
    prefijos_electronicos: frozenset[str] = frozenset({"FE"})


@dataclass
class Datos:
    """Lo leído de Effi para el periodo. Los registros anulados llevan `_anulada=True`."""
    desde: date
    hasta: date
    facturas_v: list[dict] = field(default_factory=list)
    notas_credito_v: list[dict] = field(default_factory=list)
    notas_debito_v: list[dict] = field(default_factory=list)
    buzon: list[dict] = field(default_factory=list)            # documento_ebill_proveedor
    facturas_c: list[dict] = field(default_factory=list)
    documentos_soporte: list[dict] = field(default_factory=list)
    nominas: list[dict] = field(default_factory=list)
