"""Fechas de Effi: los campos de fecha vienen en UTC y los filtros desde/hasta van en la hora de la empresa (Colombia)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Iterator
from zoneinfo import ZoneInfo

BOGOTA = ZoneInfo("America/Bogota")
MAX_DIAS_TRAMO = 31


def a_fecha(valor: str | date) -> date:
    return valor if isinstance(valor, date) and not isinstance(valor, datetime) else date.fromisoformat(str(valor)[:10])


def rango_mensual(desde: str | date, hasta: str | date, dias: int = MAX_DIAS_TRAMO) -> Iterator[tuple[date, date]]:
    """Parte [desde, hasta] (inclusive) en tramos de `dias` días o menos, para recursos con rango máximo."""
    inicio, fin = a_fecha(desde), a_fecha(hasta)
    if inicio > fin:
        raise ValueError(f"El periodo empieza ({inicio}) después de terminar ({fin}).")
    while inicio <= fin:
        tramo_fin = min(inicio + timedelta(days=dias - 1), fin)
        yield inicio, tramo_fin
        inicio = tramo_fin + timedelta(days=1)


def utc_a_bogota(valor: str | None) -> datetime | None:
    """'2026-09-30 23:10:00' en UTC → datetime con zona de Bogotá (ese ejemplo es el 30 a las 18:10). None si no hay fecha."""
    if not valor:
        return None
    texto = str(valor).strip().replace("T", " ").replace("Z", "")
    try:
        dt = datetime.fromisoformat(texto)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(BOGOTA)


def fecha_local(valor: str | None) -> date | None:
    """La fecha (día en Colombia) de un campo UTC de Effi."""
    dt = utc_a_bogota(valor)
    return dt.date() if dt else None
