# effi-dian

Herramientas en Python para bajar de la DIAN los XML de la facturación electrónica de una empresa, firmando las
consultas con su certificado digital (`.p12` o `.pfx`). Todo corre en el computador: el certificado y su contraseña
nunca salen de él.

1. **`dian_consulta`**: consulta del web service de la DIAN (GetStatus, GetXmlByDocumentKey…).
2. **`archivador`**: baja en lote los XML del token de la DIAN o de una lista de CUFE y los ordena por carpetas.

Solo consulta: no firma facturas ni cambia nada en la DIAN.

## Instalación

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                                   # y llena DIAN_CERT_PATH y DIAN_CERT_PASSWORD
python -m pytest                                       # 26 pruebas, sin red
```

## Uso

```bash
python -m dian_consulta verificar-cert                 # revisa el .p12 del .env; no envía nada
python -m dian_consulta estado <CUFE>                  # GetStatus
python -m dian_consulta estado --lista cufes.txt       # GetStatus de una lista → estado_dian.xlsx (retoma si se corta)
python -m dian_consulta xml <CUFE> -o factura.xml      # GetXmlByDocumentKey
python -m archivador --desde-excel token.xlsx [--solo faltantes.csv] --destino "G:/Mi unidad/Facturacion" [--zip lote.zip]
python -m archivador --desde-excel cufes.txt --destino "G:/Mi unidad/Facturacion"   # una lista de CUFE sin token
```

- La firma es WS-Security, RSA-SHA256 con c14n exclusiva sobre `wsa:To`, Timestamp de 60 s y BinarySecurityToken.
  Se hace sin `xmlsec`, con `lxml` + `cryptography`.
- Se firma el sobre tal como lo leerá la DIAN: serializado y vuelto a leer, porque la c14n de lxml sobre árboles en
  memoria no resuelve siempre igual los InclusiveNamespaces.
- El archivador guarda `<destino>/<año>/<mes>/{ventas,compras,nomina,documento_soporte}/<número>_<NIT>.xml`. Valida
  que cada XML traiga su CUFE, no vuelve a pedir lo que ya está y escribe `indice.xlsx` con «No descargados».
- Con una **lista de CUFE** (uno por línea en un `.txt`, o una columna en `.csv`/`.xlsx`), el número, la fecha, los
  NIT y el total se leen del XML descargado. El NIT de la empresa sale del certificado (o `--nit`). Lo que ya está en
  el `indice.xlsx` del destino no se vuelve a pedir.
- `faltantes.csv` sale de la plataforma: Conciliación DIAN → «Descargar faltantes (CSV)».
- El paso a paso de la prueba real con el certificado está en `GUIA_PRUEBA.md`.
- `dian_consulta/entorno.py` lee el `.env` como lo deja el Bloc de notas de Windows: en UTF-16, con BOM o guardado
  como `.env.txt`. `python -m dian_consulta diagnostico` dice qué leyó sin mostrar valores.
