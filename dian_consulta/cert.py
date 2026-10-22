"""El certificado digital de la empresa (.p12 / .pfx): se carga en memoria y nada sale del equipo."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, pkcs12


class CertificadoError(Exception):
    pass


def _utc(fecha: datetime) -> datetime:
    return fecha if fecha.tzinfo else fecha.replace(tzinfo=timezone.utc)


def vigencia(cert: x509.Certificate) -> tuple[datetime, datetime]:
    desde = getattr(cert, "not_valid_before_utc", None) or _utc(cert.not_valid_before)
    hasta = getattr(cert, "not_valid_after_utc", None) or _utc(cert.not_valid_after)
    return desde, hasta


@dataclass(frozen=True)
class Certificado:
    clave: rsa.RSAPrivateKey
    cert: x509.Certificate

    @property
    def der(self) -> bytes:
        return self.cert.public_bytes(Encoding.DER)

    def resumen(self) -> dict:
        desde, hasta = vigencia(self.cert)
        return {"titular": self.cert.subject.rfc4514_string(), "emisor": self.cert.issuer.rfc4514_string(),
                "desde": desde.isoformat(), "hasta": hasta.isoformat(), "bits": self.clave.key_size}


def cargar_certificado(ruta: str | Path, contrasena: str, ahora: datetime | None = None) -> Certificado:
    """Carga el .p12. Exige clave RSA de 2048 bits o más y que esté vigente."""
    archivo = Path(ruta)
    if not archivo.is_file():
        raise CertificadoError(f"No se encuentra el certificado en {archivo}.")
    try:
        clave, cert, _ = pkcs12.load_key_and_certificates(archivo.read_bytes(), contrasena.encode() if contrasena else None)
    except ValueError as e:
        raise CertificadoError("No se pudo abrir el certificado: revisa la contraseña (DIAN_CERT_PASSWORD).") from e
    if cert is None or clave is None:
        raise CertificadoError("El archivo no trae la clave privada: pide al emisor un .p12/.pfx exportable.")
    if not isinstance(clave, rsa.RSAPrivateKey) or clave.key_size < 2048:
        raise CertificadoError("La DIAN exige una clave RSA de 2048 bits o más.")
    desde, hasta = vigencia(cert)
    ahora = ahora or datetime.now(timezone.utc)
    if not desde <= ahora <= hasta:
        raise CertificadoError(f"El certificado no está vigente (válido del {desde:%Y-%m-%d} al {hasta:%Y-%m-%d}).")
    return Certificado(clave=clave, cert=cert)
