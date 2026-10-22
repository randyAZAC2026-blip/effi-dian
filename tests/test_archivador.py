import zipfile
from datetime import date, datetime
from decimal import Decimal

from openpyxl import Workbook, load_workbook

from archivador.__main__ import main
from archivador.descarga import descargar, escribir_indice, escribir_zip, ruta_de, trae_cufe
from archivador.token import clase, leer_solo, leer_token, nit_empresa

EMPRESA = "901682408"


def _token(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append(["Reporte de documentos"])
    ws.append([])
    ws.append(["Tipo de documento", "CUFE/CUDE", "Folio", "Prefijo", "Fecha Emisión", "NIT Emisor", "Nombre Emisor", "NIT Receptor", "Nombre Receptor", "Total"])
    ws.append(["Factura electrónica", "CUFE-A", "10", "FV", "15-09-2026", "900111222", "FERRETERIA", EMPRESA, "MI EMPRESA", "1.190.000,00"])
    ws.append(["Factura electrónica", "CUFE-B", "164", "FE", datetime(2026, 9, 20), EMPRESA, "MI EMPRESA", "800100200", "CLIENTE", 357000])
    ws.append(["Application response", "EVENTO-1", "1", "", "16-09-2026", EMPRESA, "MI EMPRESA", "900111222", "FERRETERIA", 0])
    ws.append(["Nómina Individual", "CUNE-C", "70", "NI", "30/09/2026", EMPRESA, "MI EMPRESA", "1020304050", "ANA", 2500000])
    ws.append(["Documento soporte", "CUDS-D", "27", "DSE", "2026-09-16", EMPRESA, "MI EMPRESA", "71000000", "JARDINERO", 300000])
    ws.append(["Factura electrónica", "cufe-a", "10", "FV", "15-09-2026", "900111222", "FERRETERIA", EMPRESA, "MI EMPRESA", 1190000])   # repetido
    ruta = tmp_path / "token.xlsx"
    wb.save(ruta)
    return ruta


def _xml(uuid: str) -> bytes:
    return (f'<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">'
            f"<cbc:UUID>{uuid}</cbc:UUID></Invoice>").encode()


class DianFalsa:
    def __init__(self, respuestas):
        self.respuestas = respuestas
        self.pedidos = []

    def get_xml(self, cufe):
        self.pedidos.append(cufe)
        r = self.respuestas[cufe]
        if isinstance(r, Exception):
            raise r
        return r


def test_lee_el_token_sin_eventos_ni_repetidos(tmp_path):
    docs = leer_token(_token(tmp_path))
    assert [d.cufe for d in docs] == ["CUFE-A", "CUFE-B", "CUNE-C", "CUDS-D"]
    a = docs[0]
    assert (a.numero, a.fecha, a.total, a.nit_emisor) == ("FV10", date(2026, 9, 15), Decimal("1190000.00"), "900111222")
    assert docs[1].fecha == date(2026, 9, 20) and docs[2].fecha == date(2026, 9, 30)
    assert nit_empresa(docs) == EMPRESA
    assert [clase(d, EMPRESA) for d in docs] == ["compras", "ventas", "nomina", "documento_soporte"]


def test_valida_el_cufe_del_xml_incluido_attached_document():
    assert trae_cufe(_xml("CUFE-A"), "cufe-a")
    assert not trae_cufe(_xml("OTRO"), "CUFE-A")
    assert not trae_cufe(b"no es xml", "CUFE-A")
    adjunto = (b'<AttachedDocument xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"><cbc:Description>'
               b"&lt;Invoice&gt;&lt;cbc:UUID&gt;CUFE-A&lt;/cbc:UUID&gt;&lt;/Invoice&gt;</cbc:Description></AttachedDocument>")
    assert trae_cufe(adjunto, "CUFE-A")


def test_descarga_en_lote_organiza_salta_lo_que_existe_y_reporta_errores(tmp_path):
    docs = leer_token(_token(tmp_path))
    destino = tmp_path / "Facturacion"
    ya = ruta_de(destino, docs[3], "documento_soporte")
    ya.parent.mkdir(parents=True); ya.write_bytes(_xml("CUDS-D"))
    fuente = DianFalsa({"CUFE-A": _xml("CUFE-A"), "CUFE-B": _xml("OTRO"), "CUNE-C": RuntimeError("código 66")})
    esperas = []
    res = descargar(docs, fuente, destino, EMPRESA, pausa=0.5, dormir=esperas.append)
    assert [r.estado for r in res] == ["descargado", "error", "error", "ya_estaba"]
    assert fuente.pedidos == ["CUFE-A", "CUFE-B", "CUNE-C"]           # el que ya estaba no se pide
    assert esperas == [0.5, 0.5]                                         # pausa entre descargas
    assert res[0].ruta == destino / "2026" / "09" / "compras" / "FV10_900111222.xml"
    assert "no trae ese CUFE" in res[1].detalle and "66" in res[2].detalle

    indice = load_workbook(escribir_indice(res, destino / "indice.xlsx"))
    assert indice.sheetnames == ["Indice", "No descargados"]
    assert indice["Indice"].max_row == 5 and indice["No descargados"].max_row == 3
    with zipfile.ZipFile(escribir_zip(res, tmp_path / "lote.zip", destino)) as z:
        assert sorted(z.namelist()) == ["2026/09/compras/FV10_900111222.xml", "2026/09/documento_soporte/DSE27_71000000.xml"]

    # Segunda corrida: lo descargado ya no se vuelve a pedir.
    fuente2 = DianFalsa({"CUFE-B": _xml("CUFE-B"), "CUNE-C": _xml("CUNE-C")})
    res2 = descargar(docs, fuente2, destino, EMPRESA, pausa=0)
    assert fuente2.pedidos == ["CUFE-B", "CUNE-C"] and [r.estado for r in res2] == ["ya_estaba", "descargado", "descargado", "ya_estaba"]


def test_cli_con_la_lista_de_faltantes(tmp_path, capsys):
    token = _token(tmp_path)
    faltantes = tmp_path / "faltantes.csv"
    faltantes.write_text("cufe;clase;documento\ncufe-b;Venta;FE164\n", encoding="utf-8")
    assert leer_solo(faltantes) == {"cufe-b"}
    fuente = DianFalsa({"CUFE-B": _xml("CUFE-B")})
    codigo = main(["--desde-excel", str(token), "--solo", str(faltantes), "--destino", str(tmp_path / "out"), "--zip", str(tmp_path / "lote.zip"), "--pausa", "0"], cliente=fuente)
    salida = capsys.readouterr().out
    assert codigo == 0 and fuente.pedidos == ["CUFE-B"]
    assert "Descargados 1" in salida and (tmp_path / "out" / "indice.xlsx").exists() and (tmp_path / "lote.zip").exists()


def test_cli_sin_token_valido(tmp_path, capsys):
    malo = tmp_path / "malo.csv"
    malo.write_text("a,b\n1,2\n", encoding="utf-8")
    assert main(["--desde-excel", str(malo), "--destino", str(tmp_path)], cliente=DianFalsa({})) == 1
    assert "CUFE/CUDE" in capsys.readouterr().err
