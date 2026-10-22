"""Cliente de la API REST de Effi ERP (https://effi.com.co/api/<recurso>).

De solo lectura por defecto. Crear, modificar y anular solo funcionan con EFFI_PERMITIR_ESCRITURA=1 y, en las
transacciones, con una idempotency_key. Maneja las trampas conocidas de la API (spec, sección 7):
- no se envían filtros vacíos (un total_desde vacío vale 0);
- en las transacciones se añade vigente=1 si no se pide otra cosa (si se omite, mezcla vigentes y anuladas);
- factura_v exige desde y hasta (sin ellos solo trae desde ayer);
- documento_ebill_proveedor exige desde y un rango de 31 días o menos.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Iterator

import requests

from .config import EffiConfig
from .fechas import MAX_DIAS_TRAMO, a_fecha

TRANSACCIONES = frozenset({
    "factura_v", "factura_c", "nota_credito_v", "nota_debito_v", "nota_credito_c", "devolucion_c",
    "documento_soporte", "nomina", "anticipo_nomina", "ausencia_laboral", "orden_c",
})
CON_RESUMEN = frozenset({"factura_v", "factura_c"})
POR_PAGINA = 100
REINTENTOS_429 = 3


class EffiError(Exception):
    def __init__(self, status: int, mensaje: str):
        super().__init__(f"Effi {status}: {mensaje}")
        self.status = status
        self.mensaje = mensaje


class EscrituraBloqueada(EffiError):
    def __init__(self) -> None:
        super().__init__(0, "La escritura está desactivada. Actívala con EFFI_PERMITIR_ESCRITURA=1 solo después de la aprobación.")


@dataclass
class Pagina:
    data: list[dict]
    paginacion: dict = field(default_factory=dict)

    @property
    def total_paginas(self) -> int:
        try:
            return int(self.paginacion.get("total_paginas") or 1)
        except (TypeError, ValueError):
            return 1


def _limpiar(filtros: dict[str, Any]) -> dict[str, Any]:
    """Quita los filtros vacíos y pasa las fechas a texto."""
    out = {}
    for clave, valor in filtros.items():
        if valor is None or (isinstance(valor, str) and not valor.strip()):
            continue
        out[clave] = valor.isoformat() if isinstance(valor, date) else valor
    return out


class EffiClient:
    def __init__(self, config: EffiConfig, session: requests.Session | None = None, dormir: Callable[[float], None] = time.sleep):
        self.config = config
        self.session = session or requests.Session()
        self._dormir = dormir

    # ---------------- Lectura ----------------
    def listar(self, recurso: str, **filtros: Any) -> Pagina:
        params = self._filtros_lectura(recurso, filtros)
        cuerpo = self._pedir("GET", recurso, params=params)
        return Pagina(data=list(cuerpo.get("data") or []), paginacion=cuerpo.get("paginacion") or {})

    def listar_todo(self, recurso: str, **filtros: Any) -> Iterator[dict]:
        """Todas las páginas, de 100 en 100."""
        filtros = {**filtros, "por_pagina": POR_PAGINA}
        pagina = 1
        while True:
            p = self.listar(recurso, **{**filtros, "pagina": pagina})
            yield from p.data
            if pagina >= p.total_paginas or not p.data:
                return
            pagina += 1

    def resumen(self, recurso: str, agrupar_por: str, **filtros: Any) -> list[dict]:
        if recurso not in CON_RESUMEN:
            raise ValueError(f"{recurso} no tiene resumen (agrupar_por): solo {', '.join(sorted(CON_RESUMEN))}.")
        return self.listar(recurso, agrupar_por=agrupar_por, **filtros).data

    def _filtros_lectura(self, recurso: str, filtros: dict[str, Any]) -> dict[str, Any]:
        params = _limpiar(filtros)
        if recurso in TRANSACCIONES:
            params.setdefault("vigente", 1)
        if recurso == "factura_v" and not ("desde" in params and "hasta" in params):
            raise ValueError("factura_v exige desde y hasta (sin ellos Effi solo devuelve las facturas desde ayer).")
        if recurso == "documento_ebill_proveedor":
            if "desde" not in params:
                raise ValueError("documento_ebill_proveedor exige desde.")
            if "hasta" in params and (a_fecha(params["hasta"]) - a_fecha(params["desde"])).days + 1 > MAX_DIAS_TRAMO:
                raise ValueError("documento_ebill_proveedor admite 31 días como máximo: usa fechas.rango_mensual.")
        return params

    # ---------------- Escritura (bloqueada por defecto) ----------------
    def crear(self, recurso: str, datos: dict, idempotency_key: str | None = None) -> dict:
        return self._escribir("POST", recurso, datos, idempotency_key)

    def modificar(self, recurso: str, datos: dict) -> dict:
        """PUT parcial. Ojo: una clave vacía borra el campo, y direcciones/redes_sociales reemplazan todo el conjunto."""
        return self._escribir("PUT", recurso, datos, None, exigir_clave=False)

    def anular(self, recurso: str, datos: dict, idempotency_key: str | None = None) -> dict:
        if recurso in TRANSACCIONES and not datos.get("observacion_anular"):
            raise ValueError("Anular una transacción exige observacion_anular.")
        return self._escribir("DELETE", recurso, datos, idempotency_key)

    def _escribir(self, metodo: str, recurso: str, datos: dict, idempotency_key: str | None, exigir_clave: bool = True) -> dict:
        if not self.config.permitir_escritura:
            raise EscrituraBloqueada()
        cuerpo = dict(datos)
        if idempotency_key:
            cuerpo["idempotency_key"] = idempotency_key
        if exigir_clave and recurso in TRANSACCIONES:
            clave = cuerpo.get("idempotency_key") or ""
            if not 8 <= len(clave) <= 36:
                raise ValueError("Las transacciones exigen una idempotency_key de 8 a 36 caracteres.")
        return self._pedir(metodo, recurso, json=cuerpo).get("data") or {}

    # ---------------- HTTP ----------------
    def _pedir(self, metodo: str, recurso: str, **kwargs: Any) -> dict:
        url = f"{self.config.base_url}/{recurso.strip('/')}"
        headers = {"Authorization": f"Bearer {self.config.api_key}", "Accept": "application/json"}
        # Solo se reintenta lo que no duplica: los GET, o una escritura con idempotency_key (Effi responde 409 al repetir).
        reintentable = metodo == "GET" or bool((kwargs.get("json") or {}).get("idempotency_key"))
        for intento in range(REINTENTOS_429 + 1):
            r = self.session.request(metodo, url, headers=headers, timeout=self.config.timeout, **kwargs)
            if r.status_code == 429 and reintentable and intento < REINTENTOS_429:
                self._dormir(_retry_after(r))
                continue
            return _respuesta(r)
        raise EffiError(429, "Límite de 120 peticiones por minuto superado.")  # pragma: no cover


def _retry_after(r: requests.Response) -> float:
    try:
        return max(0.0, float(r.headers.get("Retry-After", "1")))
    except ValueError:
        return 1.0


def _respuesta(r: requests.Response) -> dict:
    try:
        cuerpo = r.json()
    except ValueError:
        cuerpo = {}
    if r.status_code == 401:
        raise EffiError(401, "API key inválida o vencida: renuévela en Administración → Usuarios.")
    if r.status_code == 403:
        raise EffiError(403, cuerpo.get("mensaje") or "El usuario de la API no tiene permiso sobre esta función.")
    if r.status_code >= 400 or cuerpo.get("ok") is False:
        raise EffiError(r.status_code, cuerpo.get("mensaje") or r.text[:300] or "Error sin mensaje")
    return cuerpo
