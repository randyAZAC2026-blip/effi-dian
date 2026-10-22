"""Lectura del .env (nunca del código): tolera lo que hace el Bloc de notas de Windows (UTF-16, BOM, .env.txt)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


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
