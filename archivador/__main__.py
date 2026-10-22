"""python -m archivador --desde-excel token.xlsx [--solo faltantes.csv] --destino CARPETA [--zip lote.zip] [--nit NIT]"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from dian_consulta.cert import CertificadoError
from dian_consulta.client import DianClient, DianError

from .descarga import descargar, escribir_indice, escribir_zip
from .token import leer_solo, leer_token, nit_empresa


def main(argv: list[str] | None = None, cliente=None) -> int:
    ap = argparse.ArgumentParser(prog="archivador", description="Baja en lote los XML del token de la DIAN con el certificado de la empresa.")
    ap.add_argument("--desde-excel", required=True, help="Excel (o CSV) del token exportado del portal de la DIAN")
    ap.add_argument("--solo", help="CSV de faltantes de la plataforma (Conciliación DIAN → Descargar faltantes)")
    ap.add_argument("--destino", required=True, help="Carpeta donde se guardan los XML (puede ser de Google Drive)")
    ap.add_argument("--zip", help="Además, un ZIP con los XML del lote para el Tablero")
    ap.add_argument("--nit", help="NIT de la empresa (si no, se toma el que más aparece en el token)")
    ap.add_argument("--pausa", type=float, default=1.0, help="Segundos entre descargas (por defecto 1)")
    args = ap.parse_args(argv)
    try:
        docs = leer_token(args.desde_excel)
        empresa = (args.nit or "").split("-")[0].strip() or nit_empresa(docs)
        if args.solo:
            solo = leer_solo(args.solo)
            docs = [d for d in docs if d.cufe.lower() in solo]
        if not docs:
            print("No hay documentos para descargar.")
            return 0
        print(f"{len(docs)} documentos del token · empresa {empresa} · destino {args.destino}")
        fuente = cliente or DianClient.desde_entorno()
        def avisar(i: int, n: int, r) -> None:
            marca = {"descargado": "✓", "ya_estaba": "=", "error": "✗"}[r.estado]
            print(f"  [{i}/{n}] {marca} {r.doc.numero or r.doc.cufe[:16]}{' · ' + r.detalle if r.detalle else ''}")
        resultados = descargar(docs, fuente, args.destino, empresa, pausa=args.pausa, avisar=avisar)
        indice = escribir_indice(resultados, Path(args.destino) / "indice.xlsx")
        c = Counter(r.estado for r in resultados)
        print(f"Descargados {c['descargado']} · ya estaban {c['ya_estaba']} · con error {c['error']} → {indice}")
        if args.zip:
            print(f"ZIP para el Tablero: {escribir_zip(resultados, args.zip, args.destino)}")
        return 0 if not c["error"] else 2
    except (CertificadoError, DianError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
