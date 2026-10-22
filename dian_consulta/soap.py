"""Sobre SOAP 1.2 firmado con WS-Security para WcfDianCustomerServices (spec, sección 4).

- Cabecera wsse:Security con wsu:Timestamp (60 s), BinarySecurityToken (X509v3 en base64) y ds:Signature.
- Firma RSA-SHA256 con canonicalización exclusiva sobre el elemento wsa:To (que lleva wsu:Id).
- InclusiveNamespaces: «wsa soap wcf» en SignedInfo y «soap wcf» en la referencia.
Sin xmlsec: solo lxml y cryptography.
"""
from __future__ import annotations

import base64
import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from lxml import etree

from .cert import Certificado

SOAP = "http://www.w3.org/2003/05/soap-envelope"
WCF = "http://wcf.dian.colombia"
WSA = "http://www.w3.org/2005/08/addressing"
WSSE = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
WSU = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"
DS = "http://www.w3.org/2000/09/xmldsig#"
EC = "http://www.w3.org/2001/10/xml-exc-c14n#"
X509V3 = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-x509-token-profile-1.0#X509v3"
BASE64 = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary"
RSA_SHA256 = "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
SHA256 = "http://www.w3.org/2001/04/xmlenc#sha256"

PREFIJOS_SIGNEDINFO = ["wsa", "soap", "wcf"]
PREFIJOS_REFERENCIA = ["soap", "wcf"]
VIGENCIA_SEGUNDOS = 60


def accion(operacion: str) -> str:
    return f"http://wcf.dian.colombia/IWcfDianCustomerServices/{operacion}"


def content_type(operacion: str) -> str:
    return f'application/soap+xml;charset=UTF-8;action="{accion(operacion)}"'


def _q(ns: str, nombre: str) -> str:
    return f"{{{ns}}}{nombre}"


def c14n(elemento: etree._Element, prefijos: list[str]) -> bytes:
    return etree.tostring(elemento, method="c14n", exclusive=True, inclusive_ns_prefixes=prefijos)


def _fecha(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def sobre(operacion: str, parametros: dict[str, str], endpoint: str, cert: Certificado, ahora: datetime | None = None) -> bytes:
    """El sobre SOAP firmado, listo para enviar por POST al endpoint."""
    ahora = ahora or datetime.now(timezone.utc)
    sufijo = uuid.uuid4().hex.upper()
    id_to, id_token, id_ts = f"ID-{sufijo}", f"X509-{sufijo}", f"TS-{sufijo}"

    env = etree.Element(_q(SOAP, "Envelope"), nsmap={"soap": SOAP, "wcf": WCF})
    header = etree.SubElement(env, _q(SOAP, "Header"), nsmap={"wsa": WSA})
    seguridad = etree.SubElement(header, _q(WSSE, "Security"), nsmap={"wsse": WSSE, "wsu": WSU})
    seguridad.set(_q(SOAP, "mustUnderstand"), "true")
    ts = etree.SubElement(seguridad, _q(WSU, "Timestamp"))
    ts.set(_q(WSU, "Id"), id_ts)
    etree.SubElement(ts, _q(WSU, "Created")).text = _fecha(ahora)
    etree.SubElement(ts, _q(WSU, "Expires")).text = _fecha(ahora + timedelta(seconds=VIGENCIA_SEGUNDOS))
    token = etree.SubElement(seguridad, _q(WSSE, "BinarySecurityToken"), EncodingType=BASE64, ValueType=X509V3)
    token.set(_q(WSU, "Id"), id_token)
    token.text = base64.b64encode(cert.der).decode()

    firma = etree.SubElement(seguridad, _q(DS, "Signature"), nsmap={"ds": DS}, Id=f"SIG-{sufijo}")
    etree.SubElement(header, _q(WSA, "Action")).text = accion(operacion)
    to = etree.SubElement(header, _q(WSA, "To"), nsmap={"wsu": WSU})
    to.set(_q(WSU, "Id"), id_to)
    to.text = endpoint

    cuerpo = etree.SubElement(env, _q(SOAP, "Body"))
    op = etree.SubElement(cuerpo, _q(WCF, operacion))
    for nombre, valor in parametros.items():
        etree.SubElement(op, _q(WCF, nombre)).text = str(valor)

    # SignedInfo: referencia a wsa:To con su digest.
    signed = etree.SubElement(firma, _q(DS, "SignedInfo"))
    canon = etree.SubElement(signed, _q(DS, "CanonicalizationMethod"), Algorithm=EC)
    etree.SubElement(canon, _q(EC, "InclusiveNamespaces"), nsmap={"ec": EC}, PrefixList=" ".join(PREFIJOS_SIGNEDINFO))
    etree.SubElement(signed, _q(DS, "SignatureMethod"), Algorithm=RSA_SHA256)
    ref = etree.SubElement(signed, _q(DS, "Reference"), URI=f"#{id_to}")
    transforms = etree.SubElement(ref, _q(DS, "Transforms"))
    tr = etree.SubElement(transforms, _q(DS, "Transform"), Algorithm=EC)
    etree.SubElement(tr, _q(EC, "InclusiveNamespaces"), nsmap={"ec": EC}, PrefixList=" ".join(PREFIJOS_REFERENCIA))
    etree.SubElement(ref, _q(DS, "DigestMethod"), Algorithm=SHA256)
    etree.SubElement(ref, _q(DS, "DigestValue"))
    etree.SubElement(firma, _q(DS, "SignatureValue"))
    info = etree.SubElement(firma, _q(DS, "KeyInfo"), Id=f"KI-{sufijo}")
    str_ = etree.SubElement(info, _q(WSSE, "SecurityTokenReference"))
    str_.set(_q(WSU, "Id"), f"STR-{sufijo}")
    etree.SubElement(str_, _q(WSSE, "Reference"), URI=f"#{id_token}", ValueType=X509V3)

    # Se firma el documento tal como lo leerá la DIAN: serializado y vuelto a leer. La c14n de lxml sobre un árbol
    # armado en memoria no siempre resuelve igual los InclusiveNamespaces.
    env = etree.fromstring(etree.tostring(env, encoding="utf-8"))
    ns = {"wsa": WSA, "ds": DS}
    to = env.find(".//wsa:To", ns)
    signed = env.find(".//ds:SignedInfo", ns)
    env.find(".//ds:DigestValue", ns).text = base64.b64encode(hashlib.sha256(c14n(to, PREFIJOS_REFERENCIA)).digest()).decode()
    valor = cert.clave.sign(c14n(signed, PREFIJOS_SIGNEDINFO), padding.PKCS1v15(), hashes.SHA256())
    env.find(".//ds:SignatureValue", ns).text = base64.b64encode(valor).decode()
    return etree.tostring(env, xml_declaration=False, encoding="utf-8")
