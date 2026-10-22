"""Configuración del cliente de Effi: se lee del entorno o de un archivo .env (nunca del código)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

URL_POR_DEFECTO = "https://effi.com.co/api"


@dataclass
class LecturaEnv:
    """Qué .env se leyó (para diagnosticar sin mostrar valores)."""
    archivo: Path | None = None
    codificacion: str = ""
    claves: list[str] = field(default_factory=list)


def _texto_env(archivo: Path) -> tuple[str, str]:
    """El texto del .env con su codificación: el Bloc de notas de Windows puede guardar en UTF-16 o con BOM."""
    datos = archivo.read_bytes()
    if datos.startswith(b"\xff\xfe") or datos.startswith(b"\xfe\xff"):
        return datos.decode("utf-16"), "UTF-16"
    if datos.startswith(b"\xef\xbb\xbf"):
        return datos.decode("utf-8-sig"), "UTF-8 con BOM"
    try:
        return datos.decode("utf-8"), "UTF-8"
    except UnicodeDecodeError:
        return datos.decode("cp1252"), "Windows-1252"


def cargar_env(ruta: str | os.PathLike = ".env") -> LecturaEnv:
    """Carga CLAVE=valor de un .env sin pisar lo que ya está en el entorno. Ignora comentarios y líneas vacías.
    Si no existe el .env, prueba .env.txt (Windows oculta las extensiones). Devuelve qué leyó, sin los valores."""
    archivo = Path(ruta)
    if not archivo.is_file() and Path(f"{archivo}.txt").is_file():
        archivo = Path(f"{archivo}.txt")
    if not archivo.is_file():
        return LecturaEnv()
    texto, codificacion = _texto_env(archivo)
    claves = []
    for linea in texto.splitlines():
        linea = linea.strip().lstrip("\ufeff")
        if linea.lower().startswith("export "):
            linea = linea[7:].strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        clave = clave.strip()
        valor = valor.strip().strip('"').strip("'").strip()
        claves.append(clave)
        # Una variable vacía en el entorno no tapa la del .env.
        if not os.environ.get(clave):
            os.environ[clave] = valor
    return LecturaEnv(archivo=archivo, codificacion=codificacion, claves=claves)


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
