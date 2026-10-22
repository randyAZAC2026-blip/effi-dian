"""python -m conciliacion --desde 2026-01-01 --hasta 2026-09-30 --modulos ventas,compras,nomina [--verificar-dian] -o conciliacion.xlsx"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import date
from decimal import Decimal

from effi_api.client import EffiClient, EffiError
from effi_api.config import EffiConfig

from .controles import conciliar
from .datos import leer_periodo
from .excel import escribir_excel
from .modelos import Parametros

MODULOS = {"ventas", "compras", "nomina"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="conciliacion", description="Conciliación Effi ↔ DIAN (solo lectura) a un Excel de hallazgos.")
    ap.add_argument("--desde", required=True, type=date.fromisoformat)
    ap.add_argument("--hasta", required=True, type=date.fromisoformat)
    ap.add_argument("--modulos", default="ventas,compras,nomina", help="Separados por coma: ventas, compras, nomina")
    ap.add_argument("--verificar-dian", action="store_true", help="Consulta GetStatus de cada código propio (necesita dian_consulta y el .p12)")
    ap.add_argument("--gracia-cufe", type=int, default=2, help="Días antes de reportar un documento sin CUFE/CUDE/CUNE/CUDS")
    ap.add_argument("--gracia-radian", type=int, default=10, help="Días antes de reportar un evento RADIAN pendiente")
    ap.add_argument("--tolerancia", type=Decimal, default=Decimal(1), help="Diferencia de valor tolerada (pesos)")
    ap.add_argument("-o", "--salida", default="conciliacion.xlsx")
    args = ap.parse_args(argv)

    modulos = {m.strip().lower() for m in args.modulos.split(",") if m.strip()}
    if not modulos <= MODULOS:
        ap.error(f"Módulos desconocidos: {', '.join(sorted(modulos - MODULOS))}")
    if args.desde > args.hasta:
        ap.error("--desde es posterior a --hasta")
    p = Parametros(dias_gracia_cufe=args.gracia_cufe, dias_gracia_radian=args.gracia_radian, tolerancia_valor=args.tolerancia)

    try:
        datos = leer_periodo(EffiClient(EffiConfig.desde_entorno()), args.desde, args.hasta, modulos)
    except (EffiError, ValueError) as e:
        print(f"Error leyendo Effi: {e}", file=sys.stderr)
        return 1
    hallazgos = conciliar(datos, p, modulos)
    if args.verificar_dian:
        from .dian import cliente_dian, verificar_en_dian
        try:
            hallazgos += verificar_en_dian(datos, cliente_dian())
        except RuntimeError as e:
            print(f"Aviso: sin verificación en la DIAN. {e}", file=sys.stderr)

    ruta = escribir_excel(hallazgos, args.salida, f"Conciliación Effi ↔ DIAN · {args.desde} a {args.hasta}")
    conteo = Counter(h.severidad for h in hallazgos)
    print(f"{len(hallazgos)} hallazgos (Alta {conteo['Alta']}, Media {conteo['Media']}) → {ruta}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
