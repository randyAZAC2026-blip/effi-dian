# effi-dian

Herramientas en Python para controlar la facturación electrónica de una empresa que factura con **Effi ERP**
(transmisión a la DIAN vía SOENAC), según el spec «Integración Effi ERP ↔ DIAN»:

1. **`effi_api`**: cliente de la API REST de Effi, de **solo lectura** por defecto.
2. **`conciliacion`**: un CLI que lee un periodo de Effi y entrega un Excel de hallazgos fiscales.
3. **`dian_consulta`**: consulta del web service de la DIAN (GetStatus, GetXmlByDocumentKey…), firmada con el
   certificado `.p12` de la empresa.
4. **`archivador`**: baja en lote los XML de los documentos del token de la DIAN. El certificado nunca sale del
   computador.

Todo lo de estas fases solo consulta: no crea, no modifica y no anula nada en Effi ni en la DIAN.

## Instalación

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                                   # y llena EFFI_API_KEY
python -m pytest                                       # 55 pruebas, sin red
```

## Uso

```bash
# Probar la key y ver la forma de un recurso
python -m effi_api listar proveedor
python -m effi_api listar factura_v --desde 2026-09-01 --hasta 2026-09-30 --todo

# Conciliación
python -m conciliacion --desde 2026-01-01 --hasta 2026-09-30 --modulos ventas,compras,nomina -o conciliacion.xlsx
python -m conciliacion --desde 2026-09-01 --hasta 2026-09-30 --verificar-dian      # opcional, con certificado
```

Parámetros: `--gracia-cufe` (2 días), `--gracia-radian` (10 días), `--tolerancia` ($1).

## XML de la DIAN con certificado

```bash
python -m dian_consulta verificar-cert                 # revisa el .p12 del .env; no envía nada
python -m dian_consulta estado <CUFE>                  # GetStatus
python -m dian_consulta xml <CUFE> -o factura.xml      # GetXmlByDocumentKey
python -m archivador --desde-excel token.xlsx [--solo faltantes.csv] --destino "G:/Mi unidad/Facturacion" [--zip lote.zip]
```

- La firma es WS-Security, RSA-SHA256 con c14n exclusiva sobre `wsa:To`, Timestamp de 60 s y BinarySecurityToken.
  Se hace sin `xmlsec`, con `lxml` + `cryptography`.
- Se firma el sobre tal como lo leerá la DIAN: serializado y vuelto a leer, porque la c14n de lxml sobre árboles en
  memoria no resuelve siempre igual los InclusiveNamespaces.
- El archivador guarda `<destino>/<año>/<mes>/{ventas,compras,nomina,documento_soporte}/<número>_<NIT>.xml`. Valida
  que cada XML traiga su CUFE, no vuelve a pedir lo que ya está y escribe `indice.xlsx` con «No descargados».
- `faltantes.csv` sale de la plataforma: Conciliación DIAN → «Descargar faltantes (CSV)».
- El paso a paso de la prueba real con el certificado está en `GUIA_PRUEBA.md`.

## Controles

| Módulo | Control (hoja del Excel) | Severidad |
| --- | --- | --- |
| Ventas | Factura electrónica sin CUFE (más de 2 días) | Alta |
| Ventas | Prefijo electrónico sin ebill | Alta |
| Ventas | Hueco en el consecutivo (las anuladas cuentan como usadas) | Media |
| Ventas | Nota de venta sin CUDE | Alta |
| Compras | Recibida y no registrada (buzón vs `factura_c` por CUFE; las rechazadas en RADIAN no se exigen) | Alta |
| Compras | Compra sin CUFE del buzón (sin `cufe_proveedor`, o con un CUFE que no está en el buzón del periodo) | Media |
| Compras | Diferencia XML vs registrado (más de $1) | Media |
| Compras | Evento RADIAN pendiente (estado 1 o 2, más de 10 días) | Media |
| Compras | Rechazada RADIAN y registrada (estado 6) | Alta |
| Compras | CUFE de proveedor repetido | Alta |
| Compras | Documento soporte sin CUDS | Alta |
| Nómina | Nómina electrónica sin CUNE | Alta |
| Nómina | Nómina anulada sin ajuste (con CUNE y sin `cufe_ajuste`) | Alta |
| DIAN (opcional) | Código no válido en la DIAN (`GetStatus`) | Alta |

El Excel trae una hoja **Resumen** (conteo y valor por control, las altas primero) y una hoja por control, con
filtros y el enlace al PDF cuando Effi lo da.

## Cómo está hecho

- `effi_api/client.py`: `EffiClient.listar`, `listar_todo` (páginas de 100), `resumen` (`agrupar_por`), y `crear` /
  `modificar` / `anular`, que solo funcionan con `EFFI_PERMITIR_ESCRITURA=1`.
- Las trampas de la API que maneja el cliente:
  - no envía filtros vacíos;
  - agrega `vigente=1` en las transacciones;
  - exige `desde` y `hasta` en `factura_v`;
  - en el buzón, exige `desde` y como máximo 31 días;
  - ante un 429, espera `Retry-After` y reintenta hasta 3 veces, pero solo los GET o las escrituras con `idempotency_key`;
  - traduce el 401 a un mensaje en español.
- `effi_api/fechas.py`: tramos de 31 días y paso de UTC a Colombia. Los días de gracia se cuentan en la fecha de Colombia.
- `conciliacion/controles.py`: cada control es una función pura `(datos, parámetros) -> [Hallazgo]`.
- `conciliacion/datos.py`:
  - lee facturas de venta y nóminas vigentes y anuladas (marcadas `_anulada`);
  - lee el buzón por tramos de 31 días.
- `conciliacion/dian.py`: la verificación opcional usa el paquete **`dian_consulta`**, que no está en este repositorio.
  Si no está instalado, la conciliación avisa y sigue sin ese control.

## Por confirmar en la prueba real (con la API key)

- **Nombres de campo no documentados**, que se leen con varios alias en `conciliacion/controles.py`:
  - total, NIT, nombre y número del documento en `documento_ebill_proveedor`;
  - número de las notas, del documento soporte y de la nómina.

  Si alguno sale vacío en el Excel, se agrega el nombre real en esas tuplas.
- **Filtros de fecha de `nomina`:** Effi los aplica sobre `fecha_trans`, no sobre el periodo liquidado.
- **Códigos RADIAN 1, 2 y 6:** se toman del spec.
- **El buzón en la frontera del periodo:** una compra registrada este mes pudo llegar el mes anterior y sale en
  «Compra sin CUFE del buzón». Conviene correr la conciliación con un mes extra hacia atrás.
