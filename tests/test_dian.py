import base64
import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from lxml import etree

from dian_consulta.cert import CertificadoError, cargar_certificado
from dian_consulta.client import DianClient, DianError, leer_estado, leer_rangos, leer_xml
from dian_consulta.config import DianConfig
from dian_consulta.soap import DS, PREFIJOS_REFERENCIA, PREFIJOS_SIGNEDINFO, WSA, WSSE, WSU, c14n, content_type, sobre

from .falsos import RespuestaFalsa, SesionFalsa

AHORA = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)
EP = "https://vpfe.dian.gov.co/WcfDianCustomerServices.svc"


def _p12(tmp_path, bits=2048, dias=365, clave=b"secreta", serial="901682408"):
    k = rsa.generate_private_key(public_exponent=65537, key_size=bits)
    nombre = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "EMPRESA SAS"), x509.NameAttribute(NameOID.SERIAL_NUMBER, serial)])
    cert = (x509.CertificateBuilder().subject_name(nombre).issuer_name(nombre).public_key(k.public_key()).serial_number(1)
            .not_valid_before(AHORA - timedelta(days=1)).not_valid_after(AHORA + timedelta(days=dias)).sign(k, hashes.SHA256()))
    ruta = tmp_path / f"empresa_{bits}_{dias}_{serial}.p12"
    ruta.write_bytes(pkcs12.serialize_key_and_certificates(b"empresa", k, cert, None, serialization.BestAvailableEncryption(clave)))
    return ruta


@pytest.fixture
def cert(tmp_path):
    return cargar_certificado(_p12(tmp_path), "secreta", ahora=AHORA)


# ---------------- Certificado ----------------
def test_carga_el_certificado_y_muestra_titular_y_vigencia(cert):
    r = cert.resumen()
    assert "EMPRESA SAS" in r["titular"] and "901682408" in r["titular"] and r["bits"] == 2048


def test_nit_del_certificado_con_o_sin_digito_de_verificacion(tmp_path):
    nit = lambda serial: cargar_certificado(_p12(tmp_path, serial=serial), "secreta", ahora=AHORA).nit  # noqa: E731
    assert nit("9016409885") == "901640988"      # Camerfirma pega el DV al final
    assert nit("901640988-5") == "901640988"
    assert nit("901682408") == "901682408"       # sin DV: el último dígito no cuadra como DV


def test_contrasena_mala_clave_corta_y_vencido(tmp_path):
    with pytest.raises(CertificadoError, match="contraseña"):
        cargar_certificado(_p12(tmp_path), "otra", ahora=AHORA)
    with pytest.raises(CertificadoError, match="2048"):
        cargar_certificado(_p12(tmp_path, bits=1024), "secreta", ahora=AHORA)
    with pytest.raises(CertificadoError, match="no está vigente"):
        cargar_certificado(_p12(tmp_path, dias=10), "secreta", ahora=AHORA + timedelta(days=30))
    with pytest.raises(CertificadoError, match="No se encuentra"):
        cargar_certificado(tmp_path / "no.p12", "x")


# ---------------- Sobre firmado ----------------
def _sobre(cert, op="GetStatus", params=None):
    return etree.fromstring(sobre(op, params or {"trackId": "abc123"}, EP, cert, ahora=AHORA))


def test_estructura_del_sobre(cert):
    env = _sobre(cert)
    ns = {"wsa": WSA, "wsse": WSSE, "wsu": WSU, "ds": DS}
    assert env.find(".//wsa:Action", ns).text == "http://wcf.dian.colombia/IWcfDianCustomerServices/GetStatus"
    to = env.find(".//wsa:To", ns)
    assert to.text == EP and to.get(f"{{{WSU}}}Id").startswith("ID-")
    assert env.find(".//wsu:Created", ns).text == "2026-10-22T12:00:00.000Z"
    assert env.find(".//wsu:Expires", ns).text == "2026-10-22T12:01:00.000Z"
    token = env.find(".//wsse:BinarySecurityToken", ns)
    assert base64.b64decode(token.text) == cert.der
    assert env.find(".//ds:Reference", ns).get("URI") == f"#{to.get(f'{{{WSU}}}Id')}"
    assert env.find(".//ds:KeyInfo//wsse:Reference", ns).get("URI") == f"#{token.get(f'{{{WSU}}}Id')}"
    assert [e.get("PrefixList") for e in env.iter("{http://www.w3.org/2001/10/xml-exc-c14n#}InclusiveNamespaces")] == ["wsa soap wcf", "soap wcf"]
    assert etree.QName(env.find("{http://www.w3.org/2003/05/soap-envelope}Body")[0]).localname == "GetStatus"
    assert content_type("GetXmlByDocumentKey") == 'application/soap+xml;charset=UTF-8;action="http://wcf.dian.colombia/IWcfDianCustomerServices/GetXmlByDocumentKey"'


def _verificar(env):
    ns = {"wsa": WSA, "ds": DS, "wsse": WSSE}
    to = env.find(".//wsa:To", ns)
    assert env.find(".//ds:DigestValue", ns).text == base64.b64encode(hashlib.sha256(c14n(to, PREFIJOS_REFERENCIA)).digest()).decode()
    publica = x509.load_der_x509_certificate(base64.b64decode(env.find(".//wsse:BinarySecurityToken", ns).text)).public_key()
    publica.verify(base64.b64decode(env.find(".//ds:SignatureValue", ns).text), c14n(env.find(".//ds:SignedInfo", ns), PREFIJOS_SIGNEDINFO), padding.PKCS1v15(), hashes.SHA256())


def test_la_firma_cuadra_siempre_tal_como_la_lee_la_dian(cert):
    # La c14n de lxml sobre árboles en memoria era intermitente: se firma y verifica muchas veces, con varios destinos.
    for i in range(20):
        url = EP if i % 2 else f"http://127.0.0.1:{8000 + i}/WcfDianCustomerServices.svc"
        _verificar(etree.fromstring(sobre("GetXmlByDocumentKey" if i % 3 else "GetStatus", {"trackId": f"cufe{i}"}, url, cert)))


def test_la_firma_se_verifica_con_el_certificado(cert):
    env = _sobre(cert, "GetXmlByDocumentKey")
    ns = {"wsa": WSA, "ds": DS, "wsse": WSSE}
    to = env.find(".//wsa:To", ns)
    signed = env.find(".//ds:SignedInfo", ns)
    digest = base64.b64encode(hashlib.sha256(c14n(to, PREFIJOS_REFERENCIA)).digest()).decode()
    assert env.find(".//ds:DigestValue", ns).text == digest
    firma = base64.b64decode(env.find(".//ds:SignatureValue", ns).text)
    publica = x509.load_der_x509_certificate(base64.b64decode(env.find(".//wsse:BinarySecurityToken", ns).text)).public_key()
    publica.verify(firma, c14n(signed, PREFIJOS_SIGNEDINFO), padding.PKCS1v15(), hashes.SHA256())   # lanza si no cuadra
    # Si alguien cambia el destino, la firma ya no vale.
    to.text = "https://otro.example/WcfDianCustomerServices.svc"
    assert base64.b64encode(hashlib.sha256(c14n(to, PREFIJOS_REFERENCIA)).digest()).decode() != digest


# ---------------- Respuestas ----------------
def _resp(cuerpo: str) -> bytes:
    return (f'<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:b="http://schemas.datacontract.org/2004/07/DianResponse" '
            f'xmlns:c="http://schemas.microsoft.com/2003/10/Serialization/Arrays"><s:Body>{cuerpo}</s:Body></s:Envelope>').encode()


ESTADO_OK = _resp('<GetStatusResponse xmlns="http://wcf.dian.colombia"><GetStatusResult><b:ErrorMessage/><b:IsValid>true</b:IsValid>'
                  '<b:StatusCode>00</b:StatusCode><b:StatusDescription>Procesado Correctamente.</b:StatusDescription>'
                  f'<b:XmlBase64Bytes>{base64.b64encode(b"<Invoice/>").decode()}</b:XmlBase64Bytes></GetStatusResult></GetStatusResponse>')
ESTADO_MAL = _resp('<GetStatusResponse xmlns="http://wcf.dian.colombia"><GetStatusResult><b:ErrorMessage><c:string>Regla: FAD06, Rechazo</c:string>'
                   '</b:ErrorMessage><b:IsValid>false</b:IsValid><b:StatusCode>99</b:StatusCode><b:StatusDescription>Validación contiene errores</b:StatusDescription>'
                   '</GetStatusResult></GetStatusResponse>')
XML_OK = _resp('<GetXmlByDocumentKeyResponse xmlns="http://wcf.dian.colombia"><GetXmlByDocumentKeyResult><b:Code>100</b:Code><b:Message>Accion completada OK</b:Message>'
               f'<b:XmlBytesBase64>{base64.b64encode(b"<Invoice><UUID>abc</UUID></Invoice>").decode()}</b:XmlBytesBase64></GetXmlByDocumentKeyResult></GetXmlByDocumentKeyResponse>')
XML_66 = _resp('<GetXmlByDocumentKeyResponse xmlns="http://wcf.dian.colombia"><GetXmlByDocumentKeyResult><b:Code>66</b:Code>'
               '<b:Message>TrackId no existe en los registros de la DIAN.</b:Message><b:XmlBytesBase64/></GetXmlByDocumentKeyResult></GetXmlByDocumentKeyResponse>')
FAULT = _resp('<s:Fault><s:Code><s:Value>s:Sender</s:Value></s:Code><s:Reason><s:Text xml:lang="es-CO">An error occurred when verifying security for the message.</s:Text></s:Reason></s:Fault>')
RANGOS = _resp('<GetNumberingRangeResponse xmlns="http://wcf.dian.colombia"><GetNumberingRangeResult><b:OperationCode>100</b:OperationCode><b:ResponseList>'
               '<c:NumberRangeResponse><c:ResolutionNumber>18764000001</c:ResolutionNumber><c:Prefix>FE</c:Prefix><c:FromNumber>1</c:FromNumber>'
               '<c:ToNumber>5000</c:ToNumber><c:TechnicalKey>fc8eac422eba</c:TechnicalKey></c:NumberRangeResponse></b:ResponseList></GetNumberingRangeResult></GetNumberingRangeResponse>')


def test_lee_estado_valido_y_rechazado():
    ok = leer_estado(ESTADO_OK)
    assert ok.is_valid and ok.status_code == "00" and ok.xml == b"<Invoice/>"
    mal = leer_estado(ESTADO_MAL)
    assert not mal.is_valid and mal.errores == ["Regla: FAD06, Rechazo"]


def test_lee_xml_rangos_y_fault():
    assert leer_xml(XML_OK).xml.startswith(b"<Invoice>")
    assert leer_rangos(RANGOS) == [{"ResolutionNumber": "18764000001", "Prefix": "FE", "FromNumber": "1", "ToNumber": "5000", "TechnicalKey": "fc8eac422eba"}]
    with pytest.raises(DianError, match="hora del equipo"):
        leer_estado(FAULT)


def test_cliente_firma_cada_llamada_y_traduce_el_66(cert):
    sesion = SesionFalsa(RespuestaFalsa(200, None), RespuestaFalsa(200, None))
    sesion.respuestas[0].content = XML_OK
    sesion.respuestas[1].content = XML_66
    sesion.post = lambda url, data, headers, timeout: (sesion.pedidos.append({"url": url, "data": data, "headers": headers}), sesion.respuestas.pop(0))[1]
    cli = DianClient(DianConfig(cert_path="x", cert_password=""), cert=cert, session=sesion)
    assert cli.get_xml("abc").startswith(b"<Invoice>")
    assert "GetXmlByDocumentKey" in sesion.pedidos[0]["headers"]["Content-Type"]
    assert b"<wcf:trackId>abc</wcf:trackId>" in sesion.pedidos[0]["data"]
    with pytest.raises(DianError, match="código 66"):
        cli.get_xml("noexiste")


def test_config_no_imprime_la_contrasena(monkeypatch):
    monkeypatch.setenv("DIAN_CERT_PATH", "/x.p12"); monkeypatch.setenv("DIAN_CERT_PASSWORD", "supersecreta"); monkeypatch.setenv("DIAN_AMBIENTE", "habilitacion")
    cfg = DianConfig.desde_entorno(None)
    assert "supersecreta" not in repr(cfg) and cfg.endpoint.startswith("https://vpfe-hab")
    monkeypatch.setenv("DIAN_AMBIENTE", "pruebas")
    with pytest.raises(ValueError, match="produccion o habilitacion"):
        DianConfig.desde_entorno(None)


# ---------------- .env de Windows ----------------
import os  # noqa: E402

from dian_consulta.__main__ import main as cli_dian  # noqa: E402
from effi_api.config import cargar_env  # noqa: E402


@pytest.fixture
def limpio(monkeypatch, tmp_path):
    for k in [k for k in os.environ if k.startswith("DIAN_")]:
        monkeypatch.delenv(k)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_env_del_bloc_de_notas_utf16_bom_y_txt(limpio):
    (limpio / ".env.txt").write_bytes("DIAN_CERT_PATH=C:/Certificados/empresa.p12\r\nDIAN_CERT_PASSWORD=clave\r\n".encode("utf-16"))
    lectura = cargar_env(".env")
    assert lectura.archivo.name == ".env.txt" and lectura.codificacion == "UTF-16"
    assert os.environ["DIAN_CERT_PATH"] == "C:/Certificados/empresa.p12"
    (limpio / ".env.txt").unlink()
    os.environ.pop("DIAN_CERT_PATH")
    (limpio / ".env").write_bytes("\ufeffDIAN_CERT_PATH = \"C:\\Certificados\\empresa.pfx\"\n".encode("utf-8"))
    assert cargar_env(".env").codificacion == "UTF-8 con BOM"
    assert os.environ["DIAN_CERT_PATH"] == "C:\\Certificados\\empresa.pfx"


def test_una_linea_vacia_no_tapa_la_que_tiene_la_ruta(limpio):
    # El .env.example trae «DIAN_CERT_PATH=» vacío: si además se agrega la línea con la ruta, debe valer la ruta.
    (limpio / ".env").write_text("DIAN_CERT_PATH=\nDIAN_CERT_PATH=C:/Certificados/empresa.p12\n", encoding="utf-8")
    cargar_env(".env")
    assert os.environ["DIAN_CERT_PATH"] == "C:/Certificados/empresa.p12"


def test_sin_ruta_explica_que_vio_sin_mostrar_valores(limpio):
    (limpio / ".env").write_text("DIAN_AMBIENTE=produccion\nDIAN_CERT_PASSWORD=supersecreta\nDIAN_CERT_PATH=\n", encoding="utf-8")
    with pytest.raises(ValueError) as e:
        DianConfig.desde_entorno(preguntar=False)
    msj = str(e.value)
    assert "DIAN_AMBIENTE, DIAN_CERT_PASSWORD, DIAN_CERT_PATH" in msj and "supersecreta" not in msj and "vacía" in msj
    (limpio / ".env").unlink()
    with pytest.raises(ValueError, match="No se encontró el archivo .env"):
        DianConfig.desde_entorno(preguntar=False)


def test_pregunta_ruta_y_contrasena_si_hay_consola(limpio, monkeypatch, tmp_path):
    p12 = _p12(tmp_path)
    monkeypatch.setattr("builtins.input", lambda _: f'"{p12}"')
    monkeypatch.setattr("getpass.getpass", lambda _: "secreta")
    cfg = DianConfig.desde_entorno(preguntar=True)
    assert cfg.cert_path == str(p12) and cfg.cert_password == "secreta"


def test_cli_diagnostico_y_cert_por_opcion(limpio, monkeypatch, capsys, tmp_path):
    (limpio / ".env").write_text("DIAN_CERT_PATH=C:/no/existe.p12\nDIAN_CERT_PASSWORD=x\n", encoding="utf-8")
    assert cli_dian(["diagnostico"]) == 0
    salida = capsys.readouterr().out
    assert "DIAN_CERT_PATH" in salida and "NO: revisa la ruta" in salida and "C:/no/existe.p12" not in salida.split("\n")[1]
    monkeypatch.setattr("getpass.getpass", lambda _: "secreta")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    p12 = _p12(tmp_path, dias=4000)
    assert cli_dian(["--cert", str(p12), "verificar-cert"]) == 0
    assert "EMPRESA SAS" in capsys.readouterr().out


def test_cli_estado_de_una_lista_de_cufe(limpio, monkeypatch, capsys):
    from dian_consulta import __main__ as modulo
    from dian_consulta.client import Estado

    validos = {"a" * 96, "c" * 96}
    class ClienteFalso:
        def __init__(self, cfg):
            self.pedidos = []
        def get_status(self, codigo):
            if codigo == "b" * 96:
                raise DianError("código 66")
            ok = codigo in validos
            return Estado(is_valid=ok, status_code="00" if ok else "99", status_description="Procesado Correctamente." if ok else "Rechazado")
    monkeypatch.setattr(modulo, "DianClient", ClienteFalso)
    monkeypatch.setattr(modulo.DianConfig, "desde_entorno", classmethod(lambda cls, **_: DianConfig(cert_path="x", cert_password="")))
    (limpio / "cufes.txt").write_text(f"CUFE\n1. {'a' * 96}\n{'b' * 96}\n{'A' * 96}\n", encoding="utf-8")
    assert cli_dian(["estado", "--lista", "cufes.txt", "--pausa", "0", "c" * 96]) == 2
    salida = capsys.readouterr().out
    assert "[1/3]" in salida and "ERROR · código 66" in salida and "Válidos 2 de 3" in salida
    with pytest.raises(SystemExit):
        cli_dian(["estado", "--sin-esto"])
    assert cli_dian(["estado"]) == 1 and "Indica uno o varios CUFE" in capsys.readouterr().err
