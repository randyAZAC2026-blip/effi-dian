"""Sesión HTTP falsa: devuelve respuestas en cola y guarda lo que se pidió (sin red)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RespuestaFalsa:
    status_code: int = 200
    cuerpo: Any = None
    headers: dict = field(default_factory=dict)

    def json(self) -> Any:
        if self.cuerpo is None:
            raise ValueError("sin JSON")
        return self.cuerpo

    @property
    def text(self) -> str:
        return json.dumps(self.cuerpo) if self.cuerpo is not None else ""


class SesionFalsa:
    def __init__(self, *respuestas: RespuestaFalsa):
        self.respuestas = list(respuestas)
        self.pedidos: list[dict] = []

    def request(self, metodo: str, url: str, **kwargs: Any) -> RespuestaFalsa:
        self.pedidos.append({"metodo": metodo, "url": url, **kwargs})
        if not self.respuestas:
            raise AssertionError(f"Pedido inesperado: {metodo} {url} {kwargs.get('params')}")
        return self.respuestas.pop(0)


def ok(data: list | dict, pagina: int = 1, total_paginas: int = 1) -> RespuestaFalsa:
    return RespuestaFalsa(200, {"ok": True, "data": data, "paginacion": {"pagina": pagina, "por_pagina": 100, "total": 0, "total_paginas": total_paginas}})
