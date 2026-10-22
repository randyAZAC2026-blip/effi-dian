"""Controles de la conciliación Effi ↔ DIAN (spec, sección 10). Cada uno es una función pura (datos, parámetros) →
lista de hallazgos, así se prueban sin red.

Los nombres de campo de Effi que no están confirmados en la documentación se leen con varios alias (`campo(...)`).
Si la prueba real muestra otro nombre, se agrega en las tuplas de abajo.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Callable

from effi_api.fechas import fecha_local
from effi_api.modelos import a_decimal, campo, es_si

from .modelos import ALTA, MEDIA, Datos, Hallazgo, Parametros

# ---- Alias de campos ----
NUMERO = ("prefijo_id_facturacion", "prefijo_id_transaccion", "numero", "factura_proveedor", "id_transaccion", "id")
FECHA = ("fecha_trans", "fecha_emision", "fecha")
TERCERO = ("nombre_tercero", "razon_social", "cliente", "proveedor", "empleado", "nombre", "tercero")
NIT = ("nit", "numero_identificacion", "identificacion", "nit_emisor", "id_tercero")
TOTAL = ("total", "valor_total", "total_documento")
ENLACE = ("url_pdf", "url_xml")

RADIAN_PENDIENTE = {"1", "2"}
RADIAN_RECHAZADO = "6"


def _cufe(d: dict, *nombres: str) -> str:
    return str(campo(d, *(nombres or ("cufe",)), defecto="")).strip().lower()


def _fecha(d: dict) -> date | None:
    return fecha_local(campo(d, *FECHA))


def _dias(d: dict, p: Parametros) -> int | None:
    f = _fecha(d)
    return (p.hoy - f).days if f else None


def _hallazgo(modulo: str, control: str, severidad: str, d: dict, detalle: str) -> Hallazgo:
    return Hallazgo(
        modulo=modulo, control=control, severidad=severidad,
        documento=str(campo(d, *NUMERO, defecto="")),
        tercero=str(campo(d, *TERCERO, defecto="")), nit=str(campo(d, *NIT, defecto="")),
        valor=a_decimal(campo(d, *TOTAL)), fecha=_fecha(d), detalle=detalle, enlace=str(campo(d, *ENLACE, defecto="")),
    )


def _sin_codigo(docs: list[dict], p: Parametros, modulo: str, control: str, codigo: str, nombre: str) -> list[Hallazgo]:
    """Electrónico (ebill=1), vigente, sin su código y con más días que la gracia."""
    out = []
    for d in docs:
        if d.get("_anulada") or not es_si(d.get("ebill")) or _cufe(d, codigo):
            continue
        dias = _dias(d, p)
        if dias is None or dias > p.dias_gracia_cufe:
            out.append(_hallazgo(modulo, control, ALTA, d, f"Sin {nombre} hace {dias if dias is not None else '?'} días (gracia {p.dias_gracia_cufe})."))
    return out


def _prefijo_numero(texto: str) -> tuple[str, int] | None:
    m = re.match(r"^\s*([A-Za-z]+)\s*-?\s*(\d+)\s*$", str(texto or ""))
    return (m.group(1).upper(), int(m.group(2))) if m else None


# ---------------- Ventas ----------------
def ventas_sin_cufe(d: Datos, p: Parametros) -> list[Hallazgo]:
    return _sin_codigo(d.facturas_v, p, "Ventas", "Factura electrónica sin CUFE", "cufe", "CUFE")


def ventas_prefijo_sin_ebill(d: Datos, p: Parametros) -> list[Hallazgo]:
    electronicos = set(p.prefijos_electronicos)
    for f in d.facturas_v:
        pn = _prefijo_numero(campo(f, "prefijo_id_facturacion"))
        if pn and es_si(f.get("ebill")):
            electronicos.add(pn[0])
    out = []
    for f in d.facturas_v:
        pn = _prefijo_numero(campo(f, "prefijo_id_facturacion"))
        if pn and pn[0] in electronicos and not es_si(f.get("ebill")) and not f.get("_anulada"):
            out.append(_hallazgo("Ventas", "Prefijo electrónico sin ebill", ALTA, f, f"El prefijo {pn[0]} es de facturación electrónica, pero la factura tiene ebill=0."))
    return out


def ventas_huecos_consecutivo(d: Datos, p: Parametros) -> list[Hallazgo]:
    """Números que faltan entre el menor y el mayor de cada prefijo (las anuladas cuentan como usadas)."""
    por_prefijo: dict[str, set[int]] = defaultdict(set)
    for f in d.facturas_v:
        pn = _prefijo_numero(campo(f, "prefijo_id_facturacion"))
        if pn:
            por_prefijo[pn[0]].add(pn[1])
    out = []
    for prefijo, numeros in sorted(por_prefijo.items()):
        faltan = sorted(set(range(min(numeros), max(numeros) + 1)) - numeros)
        for n in faltan:
            out.append(Hallazgo("Ventas", "Hueco en el consecutivo", MEDIA, f"{prefijo}-{n}",
                                detalle=f"Falta {prefijo}-{n} entre {prefijo}-{min(numeros)} y {prefijo}-{max(numeros)} en el periodo."))
    return out


def notas_venta_sin_cude(d: Datos, p: Parametros) -> list[Hallazgo]:
    return (_sin_codigo(d.notas_credito_v, p, "Ventas", "Nota de venta sin CUDE", "cufe", "CUDE")
            + _sin_codigo(d.notas_debito_v, p, "Ventas", "Nota de venta sin CUDE", "cufe", "CUDE"))


# ---------------- Compras ----------------
def _cufes_registrados(d: Datos) -> dict[str, list[dict]]:
    reg: dict[str, list[dict]] = defaultdict(list)
    for f in d.facturas_c:
        if not f.get("_anulada") and _cufe(f, "cufe_proveedor"):
            reg[_cufe(f, "cufe_proveedor")].append(f)
    return reg


def compras_no_registradas(d: Datos, p: Parametros) -> list[Hallazgo]:
    registrados = _cufes_registrados(d)
    soporte = {_cufe(x) for x in d.documentos_soporte if _cufe(x)}
    out = []
    for b in d.buzon:
        c = _cufe(b)
        if not c or c in registrados or c in soporte or str(b.get("est_documento_ebill")) == RADIAN_RECHAZADO:
            continue
        out.append(_hallazgo("Compras", "Recibida y no registrada", ALTA, b, "El CUFE no está en ninguna factura de compra vigente."))
    return out


def compras_sin_cufe_o_fuera_del_buzon(d: Datos, p: Parametros) -> list[Hallazgo]:
    buzon = {_cufe(b) for b in d.buzon if _cufe(b)}
    out = []
    for f in d.facturas_c:
        if f.get("_anulada"):
            continue
        c = _cufe(f, "cufe_proveedor")
        if not c:
            out.append(_hallazgo("Compras", "Compra sin CUFE del buzón", MEDIA, f, "Sin cufe_proveedor: ¿es electrónica? Si no lo es, ¿tiene documento soporte?"))
        elif c not in buzon:
            out.append(_hallazgo("Compras", "Compra sin CUFE del buzón", MEDIA, f,
                                 "El CUFE no está en el buzón del periodo (pudo llegar en otro mes o por otro canal)."))
    return out


def compras_diferencia_valor(d: Datos, p: Parametros) -> list[Hallazgo]:
    registrados = _cufes_registrados(d)
    out = []
    for b in d.buzon:
        total_xml = campo(b, *TOTAL)
        if total_xml is None:
            continue
        for f in registrados.get(_cufe(b), []):
            dif = a_decimal(campo(f, *TOTAL)) - a_decimal(total_xml)
            if abs(dif) > p.tolerancia_valor:
                h = _hallazgo("Compras", "Diferencia XML vs registrado", MEDIA, f,
                              f"XML {a_decimal(total_xml):,.2f} · Effi {a_decimal(campo(f, *TOTAL)):,.2f} · diferencia {dif:,.2f}")
                out.append(h)
    return out


def compras_radian_pendiente(d: Datos, p: Parametros) -> list[Hallazgo]:
    out = []
    for b in d.buzon:
        dias = _dias(b, p)
        if str(b.get("est_documento_ebill")) in RADIAN_PENDIENTE and dias is not None and dias > p.dias_gracia_radian:
            out.append(_hallazgo("Compras", "Evento RADIAN pendiente", MEDIA, b,
                                 f"Estado RADIAN {b.get('est_documento_ebill')} hace {dias} días (gracia {p.dias_gracia_radian})."))
    return out


def compras_rechazada_registrada(d: Datos, p: Parametros) -> list[Hallazgo]:
    registrados = _cufes_registrados(d)
    return [_hallazgo("Compras", "Rechazada RADIAN y registrada", ALTA, b, "El documento se rechazó (estado 6) y aun así está en una factura de compra vigente.")
            for b in d.buzon if str(b.get("est_documento_ebill")) == RADIAN_RECHAZADO and _cufe(b) in registrados]


def compras_cufe_repetido(d: Datos, p: Parametros) -> list[Hallazgo]:
    out = []
    for c, facturas in _cufes_registrados(d).items():
        if len(facturas) > 1:
            numeros = ", ".join(str(campo(f, *NUMERO, defecto="?")) for f in facturas)
            out.extend(_hallazgo("Compras", "CUFE de proveedor repetido", ALTA, f, f"El mismo CUFE está en {len(facturas)} facturas: {numeros}.") for f in facturas)
    return out


def soporte_sin_cuds(d: Datos, p: Parametros) -> list[Hallazgo]:
    return _sin_codigo(d.documentos_soporte, p, "Compras", "Documento soporte sin CUDS", "cufe", "CUDS")


# ---------------- Nómina ----------------
def nomina_sin_cune(d: Datos, p: Parametros) -> list[Hallazgo]:
    return _sin_codigo(d.nominas, p, "Nómina", "Nómina electrónica sin CUNE", "cufe", "CUNE")


def nomina_anulada_sin_ajuste(d: Datos, p: Parametros) -> list[Hallazgo]:
    return [_hallazgo("Nómina", "Nómina anulada sin ajuste", ALTA, n, "Tenía CUNE y se anuló, pero no tiene cufe_ajuste: la DIAN la sigue viendo vigente.")
            for n in d.nominas if n.get("_anulada") and _cufe(n) and not _cufe(n, "cufe_ajuste")]


@dataclass(frozen=True)
class Control:
    modulo: str
    nombre: str
    funcion: Callable[[Datos, Parametros], list[Hallazgo]]


CONTROLES: tuple[Control, ...] = (
    Control("ventas", "Factura electrónica sin CUFE", ventas_sin_cufe),
    Control("ventas", "Prefijo electrónico sin ebill", ventas_prefijo_sin_ebill),
    Control("ventas", "Hueco en el consecutivo", ventas_huecos_consecutivo),
    Control("ventas", "Nota de venta sin CUDE", notas_venta_sin_cude),
    Control("compras", "Recibida y no registrada", compras_no_registradas),
    Control("compras", "Compra sin CUFE del buzón", compras_sin_cufe_o_fuera_del_buzon),
    Control("compras", "Diferencia XML vs registrado", compras_diferencia_valor),
    Control("compras", "Evento RADIAN pendiente", compras_radian_pendiente),
    Control("compras", "Rechazada RADIAN y registrada", compras_rechazada_registrada),
    Control("compras", "CUFE de proveedor repetido", compras_cufe_repetido),
    Control("compras", "Documento soporte sin CUDS", soporte_sin_cuds),
    Control("nomina", "Nómina electrónica sin CUNE", nomina_sin_cune),
    Control("nomina", "Nómina anulada sin ajuste", nomina_anulada_sin_ajuste),
)


def conciliar(datos: Datos, parametros: Parametros, modulos: set[str]) -> list[Hallazgo]:
    return [h for c in CONTROLES if c.modulo in modulos for h in c.funcion(datos, parametros)]
