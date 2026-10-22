"""python -m dian_consulta [--cert RUTA] verificar-cert | diagnostico | estado <CUFE> | xml <CUFE> -o archivo.xml"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from effi_api.config import cargar_env

from .cert import CertificadoError, cargar_certificado
from .client import DianClient, DianError
from .config import DianConfig, explicar_env, limpiar_ruta


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dian_consulta", description="Consulta de la DIAN firmada con el certificado de la empresa.")
    ap.add_argument("--cert", help="Ruta del .p12/.pfx (si no, la del .env); la contraseña se pregunta sin mostrarla")
    sub = ap.add_subparsers(dest="comando", required=True)
    sub.add_parser("verificar-cert", help="Revisa el .p12 del .env (titular, emisor, vigencia); no envía nada")
    sub.add_parser("diagnostico", help="Muestra qué .env lee el programa y qué claves DIAN_ trae (sin valores)")
    es = sub.add_parser("estado", help="GetStatus de un CUFE, CUDE o CUNE")
    es.add_argument("codigo")
    xm = sub.add_parser("xml", help="GetXmlByDocumentKey: guarda el XML del documento")
    xm.add_argument("codigo")
    xm.add_argument("-o", "--salida")
    args = ap.parse_args(argv)
    try:
        if args.comando == "diagnostico":
            lectura = cargar_env(".env")
            print(f"Carpeta: {Path.cwd()}\n{explicar_env(lectura)}")
            print(f"Ruta del certificado: {'definida' if os.environ.get('DIAN_CERT_PATH') else 'FALTA'} · "
                  f"contraseña: {'definida' if os.environ.get('DIAN_CERT_PASSWORD') else 'falta (se preguntará)'}")
            ruta = os.environ.get("DIAN_CERT_PATH", "")
            if ruta:
                print(f"¿Existe el archivo del certificado? {'sí' if Path(limpiar_ruta(ruta)).is_file() else 'NO: revisa la ruta y el nombre (.p12 o .pfx)'}")
            return 0
        cfg = DianConfig.desde_entorno(cert=args.cert)
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
