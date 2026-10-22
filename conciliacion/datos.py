"""Lectura de Effi para un periodo, solo con GET. Marca los anulados con `_anulada=True`."""
from __future__ import annotations

from datetime import date
from typing import Iterable

from effi_api.client import EffiClient
from effi_api.fechas import rango_mensual

from .modelos import Datos


def _anulados(registros: Iterable[dict]) -> list[dict]:
    return [{**r, "_anulada": True} for r in registros]


def leer_periodo(cliente: EffiClient, desde: date, hasta: date, modulos: set[str]) -> Datos:
    d = Datos(desde=desde, hasta=hasta)
    rango = {"desde": desde, "hasta": hasta}
    if "ventas" in modulos:
        # Las anuladas también: cuentan para el consecutivo.
        d.facturas_v = list(cliente.listar_todo("factura_v", **rango, vigente=1)) + _anulados(cliente.listar_todo("factura_v", **rango, vigente=0))
        d.notas_credito_v = list(cliente.listar_todo("nota_credito_v", **rango))
        d.notas_debito_v = list(cliente.listar_todo("nota_debito_v", **rango))
    if "compras" in modulos:
        # El buzón admite 31 días por consulta.
        d.buzon = [b for ini, fin in rango_mensual(desde, hasta) for b in cliente.listar_todo("documento_ebill_proveedor", desde=ini, hasta=fin)]
        d.facturas_c = list(cliente.listar_todo("factura_c", **rango))
        d.documentos_soporte = list(cliente.listar_todo("documento_soporte", **rango))
    if "nomina" in modulos:
        # Las anuladas también: deben tener nota de ajuste. Ojo: Effi filtra la nómina por fecha_trans.
        d.nominas = list(cliente.listar_todo("nomina", **rango, vigente=1)) + _anulados(cliente.listar_todo("nomina", **rango, vigente=0))
    return d
