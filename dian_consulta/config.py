"""Configuración de la consulta a la DIAN: se lee del entorno o del .env (el certificado nunca va en el código)."""
from __future__ import annotations

import getpass
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from effi_api.config import LecturaEnv, cargar_env

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
    def desde_entorno(cls, env: str | os.PathLike | None = ".env", cert: str | None = None, preguntar: bool | None = None) -> "DianConfig":
        """Lee el .env. Sin ruta del certificado: la pregunta (con la contraseña sin eco) si hay consola; si no, explica."""
        lectura = cargar_env(env) if env else LecturaEnv()
        ambiente = os.environ.get("DIAN_AMBIENTE", "produccion").strip().lower() or "produccion"
        if ambiente not in ENDPOINTS:
            raise ValueError("DIAN_AMBIENTE debe ser produccion o habilitacion.")
        ruta = limpiar_ruta(cert or os.environ.get("DIAN_CERT_PATH", ""))
        clave = os.environ.get("DIAN_CERT_PASSWORD", "")
        interactivo = sys.stdin.isatty() if preguntar is None else preguntar
        if not ruta and interactivo:
            print(explicar_env(lectura, env))
            ruta = limpiar_ruta(input("Ruta del certificado (.p12 o .pfx): "))
        if not ruta:
            raise ValueError(f"Falta la ruta del certificado (DIAN_CERT_PATH). {explicar_env(lectura, env)}")
        if (cert or not os.environ.get("DIAN_CERT_PASSWORD")) and interactivo:
            clave = getpass.getpass("Contraseña del certificado (no se ve al escribir): ")
        return cls(
            cert_path=ruta, cert_password=clave, ambiente=ambiente,
            timeout=float(os.environ.get("DIAN_TIMEOUT", "60")), nit_emisor=os.environ.get("DIAN_NIT_EMISOR", "").strip(),
            nit_proveedor=os.environ.get("DIAN_NIT_PROVEEDOR", "").strip(), software_id=os.environ.get("DIAN_SOFTWARE_ID", "").strip(),
            url=os.environ.get("DIAN_URL", "").strip(),
        )


def limpiar_ruta(ruta: str) -> str:
    """La ruta tal como la pega Windows: con comillas, con \\ o con /."""
    return str(ruta or "").strip().strip('"').strip("'").strip()


def explicar_env(lectura: LecturaEnv, env: str | os.PathLike | None = ".env") -> str:
    """Qué vio el programa, sin valores: qué archivo leyó y qué claves DIAN_ trae."""
    if not env:
        return "No se leyó ningún .env."
    if not lectura.archivo:
        return (f"No se encontró el archivo {env} en {Path.cwd()}. Créalo con «copy .env.example .env» en esta carpeta "
                "(no edites .env.example).")
    dian = [c for c in lectura.claves if c.startswith("DIAN_")]
    return (f"Se leyó {lectura.archivo.resolve()} ({lectura.codificacion}); trae {', '.join(dian) if dian else 'ninguna clave DIAN_'}. "
            "Si DIAN_CERT_PATH está pero vacía, escribe la ruta después del «=» y guarda.")
