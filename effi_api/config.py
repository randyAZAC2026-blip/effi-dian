"""Configuración del cliente de Effi: se lee del entorno o de un archivo .env (nunca del código)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

URL_POR_DEFECTO = "https://effi.com.co/api"


def cargar_env(ruta: str | os.PathLike = ".env") -> None:
    """Carga KEY=valor de un .env sin pisar lo que ya está en el entorno. Ignora comentarios y líneas vacías."""
    archivo = Path(ruta)
    if not archivo.is_file():
        return
    for linea in archivo.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        os.environ.setdefault(clave.strip(), valor.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class EffiConfig:
    api_key: str
    base_url: str = URL_POR_DEFECTO
    timeout: float = 30.0
    permitir_escritura: bool = False

    def __repr__(self) -> str:  # la key nunca se imprime
        return f"EffiConfig(base_url={self.base_url!r}, timeout={self.timeout}, permitir_escritura={self.permitir_escritura})"

    @classmethod
    def desde_entorno(cls, env: str | os.PathLike | None = ".env") -> "EffiConfig":
        if env:
            cargar_env(env)
        key = os.environ.get("EFFI_API_KEY", "").strip()
        if not key:
            raise ValueError("Falta EFFI_API_KEY en el .env (Administración → Usuarios → Ver más detalles en Effi).")
        return cls(
            api_key=key,
            base_url=os.environ.get("EFFI_BASE_URL", URL_POR_DEFECTO).rstrip("/"),
            timeout=float(os.environ.get("EFFI_TIMEOUT", "30")),
            permitir_escritura=os.environ.get("EFFI_PERMITIR_ESCRITURA", "0").strip() == "1",
        )
