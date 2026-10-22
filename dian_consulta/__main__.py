"""python -m dian_consulta verificar-cert | estado <CUFE> | xml <CUFE> -o archivo.xml"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .cert import CertificadoError, cargar_certificado
from .client import DianClient, DianError
from .config import DianConfig


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dian_consulta", description="Consulta de la DIAN firmada con el certificado de la empresa.")
    sub = ap.add_subparsers(dest="comando", required=True)
    sub.add_parser("verificar-cert", help="Revisa el .p12 del .env (titular, emisor, vigencia); no envía nada")
    es = sub.add_parser("estado", help="GetStatus de un CUFE, CUDE o CUNE")
    es.add_argument("codigo")
    xm = sub.add_parser("xml", help="GetXmlByDocumentKey: guarda el XML del documento")
    xm.add_argument("codigo")
    xm.add_argument("-o", "--salida")
    args = ap.parse_args(argv)
    try:
        cfg = DianConfig.desde_entorno()
        if args.comando == "verificar-cert":
            r = cargar_certificado(cfg.cert_path, cfg.cert_password).resumen()
            print(f"Titular: {r['titular']}\nEmisor:  {r['emisor']}\nVigente: {r['desde'][:10]} a {r['hasta'][:10]} · RSA {r['bits']} bits\nAmbiente: {cfg.ambiente}")
            return 0
        cliente = DianClient(cfg)
        if args.comando == "estado":
            e = cliente.get_status(args.codigo)
            print(f"{'VÁLIDO' if e.is_valid else 'NO VÁLIDO'} · {e.status_code} · {e.status_description}")
            for m in e.errores:
                print(f"  - {m}")
            return 0 if e.is_valid else 2
        xml = cliente.get_xml(args.codigo)
        destino = Path(args.salida or f"{args.codigo[:16]}.xml")
        destino.write_bytes(xml)
        print(f"XML guardado en {destino} ({len(xml):,} bytes)")
        return 0
    except (CertificadoError, DianError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
