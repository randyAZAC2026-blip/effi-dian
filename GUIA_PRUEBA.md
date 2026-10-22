# Prueba real: XML de la DIAN con el certificado de la empresa

Se hace cuando llegue el certificado. Todo corre en tu computador: el `.p12` y su contraseña nunca salen de él ni se
suben a la plataforma.

## 0. Requisitos
- Python 3.11 o más reciente. En la carpeta del proyecto: `pip install -r requirements.txt`.
- El certificado **propio de la empresa**: `.p12` o `.pfx` exportable, con su contraseña, emitido por Certicámara,
  GSE o Andes SCD a nombre de la empresa (con su NIT). El de SOENAC no sirve.
- La hora del computador sincronizada (la firma vence a los 60 segundos).

## 1. Configurar (una sola vez)
1. Guarda el `.p12` en una carpeta segura, **fuera** de Google Drive y fuera del proyecto.
2. Copia `.env.example` como `.env` y llena:
   ```
   DIAN_AMBIENTE=produccion
   DIAN_CERT_PATH=C:/Seguro/empresa.p12
   DIAN_CERT_PASSWORD=la contraseña del certificado
   ```
3. Verifica el certificado (no envía nada a la DIAN):
   ```
   python -m dian_consulta verificar-cert
   ```
   Debe mostrar el titular con el NIT de la empresa, el emisor y la vigencia.

## 2. Probar un documento
1. Estado de una factura **emitida** por la empresa (su CUFE sale del token o de la factura):
   `python -m dian_consulta estado <CUFE>`
2. Su XML: `python -m dian_consulta xml <CUFE> -o prueba_emitida.xml`
3. El XML de una factura **recibida** de un proveedor: `python -m dian_consulta xml <CUFE> -o prueba_recibida.xml`

Anota qué responde cada paso. El spec deja abierto si la DIAN entrega los XML a una empresa que factura con un
proveedor tecnológico, y si entrega los de terceros.

| Mensaje | Qué significa |
|---|---|
| «La DIAN no aceptó la firma…» | Certificado vencido o no reconocido, o la hora del equipo está mal. |
| «…no existe en el ambiente produccion (código 66)» | Ese CUFE no está en producción, o la DIAN no se lo entrega a esta empresa. |

## 3. Descarga en lote desde el token
1. En el portal de la DIAN exporta el Excel de documentos del periodo (Recibidos y/o Enviados).
2. En la plataforma, súbelo en **Conciliación DIAN** y pulsa **«Descargar faltantes (CSV)»**.
3. Corre el archivador:
   ```
   python -m archivador --desde-excel token.xlsx --solo faltantes.csv --destino "G:/Mi unidad/Facturacion" --zip lote.zip
   ```
   - Sin `--solo` baja todos los del token. Los que ya están en la carpeta no se vuelven a pedir.
   - Queda `indice.xlsx` en el destino, con la hoja «No descargados» y el motivo de cada uno.
4. Suelta `lote.zip` en el **Tablero** de la plataforma. En Conciliación DIAN deben bajar los «Falta el XML».

## Si la DIAN no entrega los XML
La alternativa legal es la descarga manual del portal (catalogo-vpfe.dian.gov.co, con el token del correo). En la
plataforma está el botón **Administración → Descargar de la DIAN**, que lo automatiza desde tu navegador.
