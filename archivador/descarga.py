"""Descarga en lote de los XML con GetXmlByDocumentKey: idempotente, valida el CUFE de cada XML y organiza
<destino>/<año>/<mes>/<clase>/<número>_<NIT>.xml. Escribe indice.xlsx y, si se pide, un ZIP para el Tablero."""
from __future__ import annotations

import re
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Protocol

from lxml import etree
from openpyxl import Workbook
from openpyxl.styles import Font

from .token import Documento, clase


class FuenteXml(Protocol):
    def get_xml(self, track_id: str) -> bytes: ...


@dataclass
class Resultado:
    doc: Documento
    clase: str
    ruta: Path | None
    estado: str          # descargado · ya_estaba · error
    detalle: str = ""


def _seguro(t: str) -> str:
    return re.sub(r"[^\w.-]+", "_", t).strip("_") or "documento"


def ruta_de(destino: Path, d: Documento, cls: str) -> Path:
    anio, mes = (f"{d.fecha:%Y}", f"{d.fecha:%m}") if d.fecha else ("sin_fecha", "00")
    # El otro: en compras, el proveedor que emite; en ventas, nómina y documento soporte la empresa emite y el tercero recibe.
    tercero = d.nit_emisor if cls == "compras" else d.nit_receptor
    return destino / anio / mes / cls / f"{_seguro(d.numero or d.cufe[:16])}_{tercero or 'sin_nit'}.xml"


def trae_cufe(xml: bytes, cufe: str) -> bool:
    """¿El XML es de ese documento? Su cbc:UUID (o el de la factura dentro de un AttachedDocument) debe ser el CUFE."""
    c = cufe.strip().lower()
    try:
        raiz = etree.fromstring(xml)
    except etree.XMLSyntaxError:
        return False
    uuids = [(x.text or "").strip().lower() for x in raiz.iter() if isinstance(x.tag, str) and etree.QName(x).localname == "UUID"]
    if c in uuids:
        return True
    # AttachedDocument: la factura va como texto dentro de cbc:Description.
    return any(c in (x.text or "").lower() for x in raiz.iter() if isinstance(x.tag, str) and etree.QName(x).localname == "Description")


def descargar(docs: Iterable[Documento], fuente: FuenteXml, destino: str | Path, empresa: str, pausa: float = 1.0,
              dormir: Callable[[float], None] = time.sleep, avisar: Callable[[int, int, Resultado], None] | None = None) -> list[Resultado]:
    destino = Path(destino)
    docs = list(docs)
    out: list[Resultado] = []
    pedidos = 0
    for i, d in enumerate(docs, start=1):
        cls = clase(d, empresa)
        ruta = ruta_de(destino, d, cls)
        if ruta.exists():
            r = Resultado(d, cls, ruta, "ya_estaba")
        else:
            if pedidos and pausa:
                dormir(pausa)
            pedidos += 1
            try:
                xml = fuente.get_xml(d.cufe)
                if not trae_cufe(xml, d.cufe):
                    raise ValueError("el XML que entregó la DIAN no trae ese CUFE")
                ruta.parent.mkdir(parents=True, exist_ok=True)
                ruta.write_bytes(xml)
                r = Resultado(d, cls, ruta, "descargado")
            except Exception as e:  # un documento que falla no detiene el lote
                r = Resultado(d, cls, None, "error", str(e))
        out.append(r)
        if avisar:
            avisar(i, len(docs), r)
    return out


def escribir_indice(resultados: list[Resultado], ruta: str | Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Indice"
    ws.append(["Clase", "Tipo", "Número", "Fecha", "NIT emisor", "Emisor", "NIT receptor", "Receptor", "Total", "CUFE", "Archivo", "Estado"])
    for r in resultados:
        d = r.doc
        ws.append([r.clase, d.tipo, d.numero, d.fecha, d.nit_emisor, d.nombre_emisor, d.nit_receptor, d.nombre_receptor, float(d.total), d.cufe,
                   str(r.ruta or ""), {"descargado": "Descargado", "ya_estaba": "Ya estaba", "error": "Error"}[r.estado]])
    fallas = wb.create_sheet("No descargados")
    fallas.append(["Número", "Fecha", "Emisor", "Total", "CUFE", "Motivo"])
    for r in resultados:
        if r.estado == "error":
            fallas.append([r.doc.numero, r.doc.fecha, r.doc.nombre_emisor, float(r.doc.total), r.doc.cufe, r.detalle])
    for hoja in (ws, fallas):
        for c in hoja[1]:
            c.font = Font(bold=True)
        hoja.freeze_panes = "A2"
        hoja.auto_filter.ref = hoja.dimensions
    destino = Path(ruta)
    destino.parent.mkdir(parents=True, exist_ok=True)
    wb.save(destino)
    return destino


def escribir_zip(resultados: list[Resultado], ruta: str | Path, base: str | Path) -> Path:
    """ZIP con los XML del lote (descargados o que ya estaban), listo para soltar en el Tablero."""
    destino = Path(ruta)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
        for r in resultados:
            if r.ruta and r.ruta.exists():
                z.write(r.ruta, r.ruta.relative_to(base).as_posix())
    return destino
