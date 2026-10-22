"""Verificación opcional en la DIAN (--verificar-dian): cada CUFE/CUDE/CUNE propio debe ser válido en GetStatus.

Usa el paquete dian_consulta (con el certificado .p12 de la empresa). Si no está instalado o no hay certificado,
la conciliación sigue sin este control.
"""
from __future__ import annotations

from typing import Any, Protocol

from effi_api.modelos import campo

from .controles import _hallazgo
from .modelos import ALTA, Datos, Hallazgo

CONTROL = "Código no válido en la DIAN"


class ConsultaDian(Protocol):
    def get_status(self, track_id: str) -> Any: ...


def cliente_dian() -> ConsultaDian:
    try:
        from dian_consulta.client import DianClient  # type: ignore[import-not-found]
    except ImportError as e:
        raise RuntimeError("Para --verificar-dian instala dian_consulta junto a este proyecto y configura el .p12 en el .env.") from e
    fabrica = getattr(DianClient, "desde_entorno", None) or getattr(DianClient, "from_env", None)
    return fabrica() if fabrica else DianClient()


def _valido(respuesta: Any) -> tuple[bool, str]:
    def leer(*nombres: str) -> Any:
        for n in nombres:
            if isinstance(respuesta, dict) and n in respuesta:
                return respuesta[n]
            if hasattr(respuesta, n):
                return getattr(respuesta, n)
        return None
    valido = leer("is_valid", "IsValid", "valido")
    descripcion = leer("status_description", "StatusDescription", "descripcion") or ""
    return str(valido).lower() in {"true", "1"}, str(descripcion)


def verificar_en_dian(datos: Datos, dian: ConsultaDian) -> list[Hallazgo]:
    propios = [("Ventas", d) for d in datos.facturas_v + datos.notas_credito_v + datos.notas_debito_v if not d.get("_anulada")]
    propios += [("Nómina", d) for d in datos.nominas if not d.get("_anulada")]
    propios += [("Compras", d) for d in datos.documentos_soporte if not d.get("_anulada")]
    out = []
    for modulo, d in propios:
        codigo = str(campo(d, "cufe", defecto="")).strip()
        if not codigo:
            continue
        try:
            ok, descripcion = _valido(dian.get_status(codigo))
        except Exception as e:  # un SOAP Fault de un documento no detiene el resto
            ok, descripcion = False, f"Error al consultar: {e}"
        if not ok:
            out.append(_hallazgo(modulo, CONTROL, ALTA, d, f"GetStatus: {descripcion or 'no válido'} · {codigo[:16]}…"))
    return out
