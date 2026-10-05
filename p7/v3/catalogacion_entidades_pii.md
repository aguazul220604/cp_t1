# Catalogación de entidades PII — dataset_validated_prepared

## 1. Contexto

- Origen: filtro `pii == true` sobre `dataset_validated_prepared` (21k, validado por Data Security).
- Resultado del filtro: **943 registros**.
- Objetivo: etiquetar manualmente la columna `entity` de cada fila PII, para entrenar el modelo de entidades (modelo B) del MVP v3.
- Regla del MVP: entidades con menos de ~15 ejemplos distintos pasan a `otro_pii`.

## 2. Decisiones tomadas

| # | Decisión |
|---|---|
| 1 | Se mantienen las 17 entidades originales. |
| 2 | Se crea la entidad nueva **`tarjeta`** (total: **18 entidades**, más `otro_pii`). |
| 3 | `edad` → `fecha_nacimiento`. |
| 4 | `num seg cli` → `nss` (se asume número de seguro; pendiente de confirmar). |
| 5 | `numempdep` → `nomina` (se asume número de empleado). |
| 6 | `ingresos` → `saldo`. |
| 7 | Todo registro sin encaje claro → `otro_pii`. |

## 3. Entidades y registros

Entre paréntesis, el número de veces que aparece el registro (cuando es mayor a 1).

### cliente
folio cliente, num cliente (61), numero cliente, numcliente (33), numerocliente, numclientep (2), no clnt, num clientenv, b01 ctenum, v cf cust num (5), customer id

### nomina
nomina (2), nominamaker, nominachecker, cve nomina, numempdep (2)

### correo
email1, email2, correoelectronico, correo elec

### telefono
telefono empleo (x2 registros), telefonos celular, tel casa1..5 (2 c/u), tel oficina1..5 (2 c/u), numtel, numtel2, numtelext, numtelex2, cel personal1..5 (2 c/u), cel trabajo1..5 (2 c/u), v cel acc no, v id cobrand ph no, tel bus, no extn bus

### sexo
sexo (4), cv sexo

### cuenta
cuentabasica (5), acct nbr (18), loan orig acct nbr (6), loan prev acct nbr (4), reln acct nbr (2), fms acct nbr (6), epp acct nbr (3), new rwrt crd acct nbr (2), crd acct nbr (22), loan auto dr acct nbr (5), legacy acct nbr, im checking plus acct nbr, rewrite linkage acct nbr (2), trnsfr acct nbr (2), ctamda subc, v af acct num, cta ordenante, loan acct cntry cde (3), dda acnt nbr (2), num cuentaeje (4), num cuenta risk

### credito
banx numero credito (2), numero credito, num credito, linea credito (2), lineacredito (10), limitecredito (10), folio credito, num cred (8), imp limitecredito (2), line id (2), linnum (2)

### saldo
saldo, n saldo capital, saldo actual (2), saldo neto (2), sdo capital (20), sdo capitalvig (4), sdo actual (6), sdo actual mn (3), aper sdobase, sdo capactual (7), b11 sdodisp, n rt tot prin, n ba curr bal, ingresos (2)

### nombre
v partner name, clnt nbr (23), borrower 1..5 clnt nbr (2 c/u), nom ordenante, src sys clnt nbr (2), nombre (9), nombrecorto, v borr 1..5 cust nbr (2 c/u), cust nmbr, aper nomcte, dda acnt nm txt, razonsocial

### apellido
apellidopaterno (2), apellidomaterno (2), apellido materno, apellido paterno

### contrato
num lineacredorig (2), cte gfcid, v contract user id, v contract no, num contrato (44), numcontrato (2), contrato (9), numcontratolocal, idcontrato, num contrato1, num contrato2, num contrato3, contrato subc, aper cto, contract id (3), banx ident contrato

### fecha_nacimiento
fechanacimiento, fec nacimiento, fnacim (5), fnacim1..4 (2 c/u), edad

### rfc
rfc (8), codrfc, cve rfc, aper rfc, rf 4 dígitos, rf 6 dígitos, rf 3 dígitos, num identificación fiscal oeq, idfiscalextranjero

### curp
curp, cve curp (3)

### fecha_vencimiento
crd expry dt (3), exp dt (3), crd exp dt, acct expry dt (2)

### direccion
v at addr 1 1, v at addr 2 1, addr line 1 (2), addr line 2 (2), poblacion (3), nomcol, colonia (3), calle (3), callenum, nacion (4), nacionlar, estate cde (3), cntry cde (5), ind city bus, ind city, ind ste bus, txn cntry cde (2), iso cntry cde

### nss
nss, num seg cli (2)

### tarjeta (nueva)
post card nbr (2), v card number, v debit card nbr, num plastico

### otro_pii
num dependientes economicos, indicadorextranjero, actacons (2), v car dlr num, creactecto (2), crd org cde

## 4. Reubicaciones sugeridas (pendientes de decisión)

Surgieron en la revisión de la primera categorización. Aún no están aplicadas en las listas de arriba.

| Registro | Hoy en | Sugerido | Motivo |
|---|---|---|---|
| clnt nbr (23), borrower 1..5 clnt nbr, src sys clnt nbr, v borr 1..5 cust nbr, cust nmbr | nombre | **cliente** | Son identificadores de cliente, no nombres. Es el cambio de mayor volumen (~45 registros). |
| cte gfcid | contrato | **cliente** | GFCID es un ID de cliente. |
| num lineacredorig (2) | contrato | **credito** | Es una línea de crédito. |
| loan acct cntry cde (3) | cuenta | **direccion** | Es un código de país. |
| nacion (4), nacionlar | direccion | nueva entidad o `otro_pii` | Parecen nacionalidad, no dirección. |
| crd acct nbr (22) | cuenta | **tarjeta** (si aplica) | Confirmar si es cuenta de tarjeta o número de tarjeta. Si lo es, `tarjeta` pasa de 4 a 26 ejemplos. |
| limitecredito (10), lineacredito (10), linea credito (2) | credito | **saldo** (opcional) | Son montos, no identificadores. Definir si `credito` es identificador o también monto. |
| v partner name | nombre | revisar | Puede ser nombre de socio o empresa. |
| ctamda subc / contrato subc | cuenta / contrato | unificar | Parecen el mismo concepto en dos entidades. |

## 5. Pendientes de confirmación

- `num seg cli`: ¿número de seguro (nss) o segmento de cliente? Si es segmento, no es PII.
- `numempdep`: ¿número de empleado o de dependientes?
- `creactecto`: si es fecha de creación de cuenta/contrato, evaluar si merece entidad propia.
- `crd acct nbr`: ¿cuenta de tarjeta o número de tarjeta?
- `line id` / `linnum`: ¿línea de crédito u otra cosa?

## 6. Notas para el entrenamiento

- Limpiar sufijos numéricos (`tel casa1..5`, `cel personal1..5`, `fnacim1..4`) con regex antes de normalizar.
- En la CV agrupada por `name_norm`, los nombres con sufijo numérico deben quedar en el mismo grupo para evitar fuga de información entre train y validación.
- Entidades con pocos ejemplos (`nss`, `curp`, `fecha_vencimiento`, `tarjeta`): revisar la regla de ~15 ejemplos distintos antes de dejarlas como entidad propia.
