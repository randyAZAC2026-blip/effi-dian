"""CLI de prueba: python -m effi_api listar factura_v --desde 2026-09-01 --hasta 2026-09-30 [--todo] [-f clave=valor]"""
from __future__ import annotations

import argparse
import json
import sys

from .client import EffiClient, EffiError
from .config import EffiConfig


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="effi_api", description="Consulta de solo lectura a la API de Effi.")
    sub = ap.add_subparsers(dest="comando", required=True)
    ls = sub.add_parser("listar", help="Lista un recurso (una página, o todas con --todo)")
    ls.add_argument("recurso")
    ls.add_argument("--desde")
    ls.add_argument("--hasta")
    ls.add_argument("--todo", action="store_true", help="Recorre todas las páginas")
    ls.add_argument("-f", "--filtro", action="append", default=[], help="Filtro extra clave=valor (repetible)")
    args = ap.parse_args(argv)

    filtros = dict(f.split("=", 1) for f in args.filtro)
    filtros.update({k: v for k, v in (("desde", args.desde), ("hasta", args.hasta)) if v})
    try:
        cliente = EffiClient(EffiConfig.desde_entorno())
        if args.todo:
            datos = list(cliente.listar_todo(args.recurso, **filtros))
            print(json.dumps({"total": len(datos), "data": datos}, ensure_ascii=False, indent=2))
        else:
            p = cliente.listar(args.recurso, **filtros)
            print(json.dumps({"paginacion": p.paginacion, "data": p.data}, ensure_ascii=False, indent=2))
    except (EffiError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
