"""Cliente del web service de la DIAN: GetStatus, GetStatusZip, GetXmlByDocumentKey y GetNumberingRange."""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any

import requests
from lxml import etree

from .cert import Certificado, cargar_certificado
from .config import DianConfig
from .soap import content_type, sobre


class DianError(Exception):
    """Error de la DIAN (SOAP Fault, HTTP) con el mensaje en español."""


def _traducir(texto: str) -> str:
    t = texto.lower()
    if "verifying security" in t or "security token" in t or "seguridad" in t:
        return ("La DIAN no aceptó la firma: el certificado está vencido o no es reconocido, o la hora del equipo está "
                f"desfasada (sincronízala). Detalle: {texto}")
    return texto


def _local(el: etree._Element) -> str:
    return etree.QName(el).localname


def _hijo(el: etree._Element | None, nombre: str) -> etree._Element | None:
    if el is None:
        return None
    return next((x for x in el.iter() if isinstance(x.tag, str) and _local(x) == nombre), None)


def _texto(el: etree._Element | None, nombre: str) -> str:
    x = _hijo(el, nombre)
    return (x.text or "").strip() if x is not None else ""


@dataclass
class Estado:
    is_valid: bool
    status_code: str
    status_description: str
    errores: list[str] = field(default_factory=list)
    xml: bytes = b""


@dataclass
class XmlDocumento:
    code: str
    message: str
    xml: bytes


def _leer(respuesta: bytes, resultado: str) -> etree._Element:
    try:
        raiz = etree.fromstring(respuesta)
    except etree.XMLSyntaxError as e:
        raise DianError(f"La DIAN respondió algo que no es XML: {respuesta[:200]!r}") from e
    fault = _hijo(raiz, "Fault")
    if fault is not None:
        raise DianError(_traducir(_texto(fault, "Text") or _texto(fault, "Reason") or "SOAP Fault sin detalle"))
    res = _hijo(raiz, resultado)
    if res is None:
        raise DianError(f"La respuesta de la DIAN no trae {resultado}.")
    return res


def leer_estado(respuesta: bytes) -> Estado:
    r = _leer(respuesta, "GetStatusResult")
    lista = _hijo(r, "ErrorMessage")
    errores = [] if lista is None else [(x.text or "").strip() for x in lista if isinstance(x.tag, str) and (x.text or "").strip()]
    xml64 = _texto(r, "XmlBase64Bytes")
    return Estado(is_valid=_texto(r, "IsValid").lower() == "true", status_code=_texto(r, "StatusCode"),
                  status_description=_texto(r, "StatusDescription"), errores=errores, xml=base64.b64decode(xml64) if xml64 else b"")


def leer_xml(respuesta: bytes) -> XmlDocumento:
    r = _leer(respuesta, "GetXmlByDocumentKeyResult")
    xml64 = _texto(r, "XmlBytesBase64")
    return XmlDocumento(code=_texto(r, "Code"), message=_texto(r, "Message"), xml=base64.b64decode(xml64) if xml64 else b"")


def leer_rangos(respuesta: bytes) -> list[dict[str, str]]:
    r = _leer(respuesta, "GetNumberingRangeResult")
    rangos = [x for x in r.iter() if isinstance(x.tag, str) and _local(x) == "NumberRangeResponse"]
    return [{_local(c): (c.text or "").strip() for c in rango if isinstance(c.tag, str)} for rango in rangos]


class DianClient:
    def __init__(self, config: DianConfig, cert: Certificado | None = None, session: requests.Session | None = None):
        self.config = config
        self.cert = cert or cargar_certificado(config.cert_path, config.cert_password)
        self.session = session or requests.Session()

    @classmethod
    def desde_entorno(cls, env: str | None = ".env") -> "DianClient":
        return cls(DianConfig.desde_entorno(env))

    def _llamar(self, operacion: str, parametros: dict[str, Any]) -> bytes:
        datos = sobre(operacion, parametros, self.config.endpoint, self.cert)
        try:
            r = self.session.post(self.config.endpoint, data=datos, headers={"Content-Type": content_type(operacion)}, timeout=self.config.timeout)
        except requests.RequestException as e:
            raise DianError(f"No se pudo conectar con la DIAN: {e}") from e
        if r.status_code >= 500 and b"Fault" not in (r.content or b""):
            raise DianError(f"La DIAN respondió {r.status_code}. Intenta más tarde.")
        return r.content

    def get_status(self, track_id: str) -> Estado:
        return leer_estado(self._llamar("GetStatus", {"trackId": track_id}))

    def get_status_zip(self, track_id: str) -> bytes:
        return self._llamar("GetStatusZip", {"trackId": track_id})

    def get_xml(self, track_id: str) -> bytes:
        """El XML del documento. Lanza DianError si la DIAN no lo entrega (código 66: no existe en ese ambiente)."""
        doc = leer_xml(self._llamar("GetXmlByDocumentKey", {"trackId": track_id}))
        if not doc.xml:
            if doc.code == "66":
                raise DianError(f"El documento no existe en el ambiente {self.config.ambiente} de la DIAN (código 66).")
            raise DianError(f"La DIAN no entregó el XML (código {doc.code or '?'}): {doc.message or 'sin detalle'}")
        return doc.xml

    def get_numbering_range(self, account_code: str, account_code_t: str, software_code: str) -> list[dict[str, str]]:
        return leer_rangos(self._llamar("GetNumberingRange", {"accountCode": account_code, "accountCodeT": account_code_t, "softwareCode": software_code}))
