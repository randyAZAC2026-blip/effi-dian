"""Configuración de la consulta a la DIAN: se lee del entorno o del .env (el certificado nunca va en el código)."""
from __future__ import annotations

import os
from dataclasses import dataclass

from effi_api.config import cargar_env

ENDPOINTS = {
    "produccion": "https://vpfe.dian.gov.co/WcfDianCustomerServices.svc",
    "habilitacion": "https://vpfe-hab.dian.gov.co/WcfDianCustomerServices.svc",
}


@dataclass(frozen=True)
class DianConfig:
    cert_path: str
    cert_password: str
    ambiente: str = "produccion"
    timeout: float = 60.0
    nit_emisor: str = ""
    nit_proveedor: str = ""
    software_id: str = ""
    url: str = ""   # solo para pruebas (servidor local); vacío = el endpoint oficial del ambiente

    def __repr__(self) -> str:  # la contraseña nunca se imprime
        return f"DianConfig(ambiente={self.ambiente!r}, cert_path={self.cert_path!r}, timeout={self.timeout})"

    @property
    def endpoint(self) -> str:
        return self.url or ENDPOINTS[self.ambiente]

    @classmethod
    def desde_entorno(cls, env: str | os.PathLike | None = ".env") -> "DianConfig":
        if env:
            cargar_env(env)
        ambiente = os.environ.get("DIAN_AMBIENTE", "produccion").strip().lower()
        if ambiente not in ENDPOINTS:
            raise ValueError("DIAN_AMBIENTE debe ser produccion o habilitacion.")
        ruta = os.environ.get("DIAN_CERT_PATH", "").strip()
        if not ruta:
            raise ValueError("Falta DIAN_CERT_PATH en el .env: la ruta del certificado .p12 de la empresa.")
        return cls(
            cert_path=ruta, cert_password=os.environ.get("DIAN_CERT_PASSWORD", ""), ambiente=ambiente,
            timeout=float(os.environ.get("DIAN_TIMEOUT", "60")), nit_emisor=os.environ.get("DIAN_NIT_EMISOR", "").strip(),
            nit_proveedor=os.environ.get("DIAN_NIT_PROVEEDOR", "").strip(), software_id=os.environ.get("DIAN_SOFTWARE_ID", "").strip(),
            url=os.environ.get("DIAN_URL", "").strip(),
        )
