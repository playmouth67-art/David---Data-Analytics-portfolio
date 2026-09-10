# 6 — Agente de operación del ETL (servidor MCP)

**Stack:** Python · MCP (FastMCP) · MySQL · Pydantic

Servidor MCP que convierte el proceso ETL del [caso 5](../5_ETL_Visitas_Web) en algo
que un agente puede operar, auditar y extender. Son 14 herramientas sobre la base del
ETL, en cuatro familias: operación, interpretación de casos ambiguos, ingesta de
archivos nuevos y práctica sobre datos reales.

> **Aviso:** los datos son **sintéticos**, los mismos que genera
> `python/generar_datos.py` del caso 5. Ningún correo, IP ni registro de actividad
> de este repositorio corresponde a una persona real.

---

## La decisión que ordena todo lo demás

> **Lo que se puede verificar con aritmética se calcula en SQL.
> Lo que exige interpretar el negocio se le deja al agente, con la evidencia enfrente
> y el dictamen registrado para que un humano pueda revisarlo.**

Ninguna herramienta le pide al modelo que cuente, que cuadre o que decida un estatus.
Esos números salen de la base, siempre. Un agente que estime «creo que se cargaron unos
dos mil registros» es peor que inútil en un proceso de datos: es una fuente de error con
voz de autoridad.

| Territorio | Quién decide | Por qué |
|---|---|---|
| Conteos, cuadres, estatus, semáforo | SQL determinista | Son verificables. El agente los lee, no los produce. |
| Qué hacer ante un código de error | El catálogo `cat_validacion` | Lo escribieron personas. El agente lo cita, no lo inventa. |
| Clasificar casos ambiguos | El agente | La regla de negocio no existe; hay que interpretar evidencia. |
| Proponer esquema para un archivo nuevo | El agente, sobre un perfil determinista | El perfilado cuenta y mide; el criterio de qué rechazar es juicio. |

La tabla `dictamen_agente` es la contraparte de esa libertad. Cada clasificación del
modelo queda con su justificación, su nivel de confianza y un campo `revisado_por` que
sigue en NULL hasta que una persona la valida. Un agente que clasifica sin dejar rastro
no es usable en producción: nadie puede revisar sus decisiones ni medir si acierta.

---

## Lo que el agente encontró al correr contra el ETL

El servidor no se probó contra un ambiente de juguete. Se levantó la base, se corrió el
ETL del caso 5 de punta a punta, y se generaron cuatro corridas con estados distintos.
De ahí salieron **cuatro defectos del proceso original** que no eran visibles con los
archivos de ejemplo. Cada uno es reproducible.

### 1. La regla V-04 no puede ejecutarse: revienta la transformación

El orquestador fija `sql_mode = 'STRICT_ALL_TABLES'` antes del `LOAD DATA`, y ese modo
persiste en la conexión. Cuando la transformación hace
`CREATE TABLE wrk_visitas AS SELECT ... STR_TO_DATE(...)`, una fecha fuera de formato
escala de advertencia a error 1411 y **aborta toda la transformación**.

```
[FATAL ERROR] (1411, "Incorrect datetime value: '2013-02-08 18:30'
                      for function str_to_date")
```

Consecuencia: V-04 —«Fecha envío inválida → RECHAZO auditado»— nunca puede auditar nada.
Un solo registro con fecha mal formada tumba la corrida completa en vez de quedar
registrado. Nunca se detectó porque los archivos de ejemplo no traen fechas inválidas;
lo confirma el propio script de análisis previo `07_validate_dates.py`.

*Verificado en MariaDB 10.11. Falta confirmarlo en MySQL 8.0 antes de afirmarlo ahí.*

### 2. La ventana entre purga y transformación deja datos irrecuperables

Un archivo que llega a `PURGADO_ORIGEN` en una corrida que después falla queda atrapado:
ya no está en el origen, su huella está registrada en `etl_archivo`, y volver a colocarlo
**no lo reprocesa** porque la idempotencia lo salta.

Probado de punta a punta. `report_10.txt` cargó 300 registros a staging, se respaldó, se
purgó del origen, y entonces la transformación falló. Al restaurar el archivo desde el
zip y volver a correr:

```
[*] Ejecución ID: 3 registrada.
  [SKIP] report_10.txt: Hash 535b702e... ya procesado.
[...] Orquestación finalizada con estatus: OK
```

**La corrida reportó OK con 300 registros permanentemente fuera del destino.** Es
exactamente la clase de fallo silencioso que los puntos de control del caso 5 existen
para evitar. `visitas_diagnosticar` lo detecta cruzando `etl_archivo` contra
`estadistica`, y devuelve la remediación concreta: recuperar el zip, borrar la fila de
`etl_archivo` para liberar la huella, y volver a colocar el archivo.

### 3. El renglón auditado no permite reconstruir el registro

La transformación arma `registro_completo` con `CONCAT_WS`, que **omite los valores
nulos**. Un campo vacío desaparece del renglón y las posiciones se recorren:

```
Original (15 campos):  correo@ejemplo.com,,HARD,,08/02/2013 18:30,-,0,0,-,0,0,-,-,-,-
Guardado (13 campos):  correo@ejemplo.com,HARD,08/02/2013 18:30,-,0,0,-,0,0,-,-,-,-
```

**64 de 66 renglones auditados están incompletos.** Toda la seguridad de «borrar del
origen no es riesgoso porque guardamos el renglón» descansa en un campo que no cumple esa
promesa. Se arregla usando `CONCAT` con separadores explícitos, o guardando la línea cruda
antes de tipificar.

### 4. El ranking de duplicados puede borrar el estatus de entrega

El ranking ordena por `opens DESC, clicks DESC`. Cuando dos filas del mismo envío difieren
en el estatus de entrega, gana la de más interacción y **con ella se descarta la marca de
rebote**. La contradicción deja de ser visible en `estadistica`: solo sobrevive en el
renglón descartado que queda en `errores`.

Es una decisión de negocio implícita que nadie tomó de forma explícita. La herramienta
`visitas_casos_ambiguos` con `tipo="badmail_perdido_en_dedupe"` cruza las dos tablas para
exponerla.

---

## Las 14 herramientas

### Operación

| Herramienta | Qué contesta |
|---|---|
| `visitas_estado_actual` | ¿Cómo va el proceso? Semáforo, métricas y alerta de vigencia |
| `visitas_listar_ejecuciones` | Historial de corridas, con filtro por estatus |
| `visitas_detalle_ejecucion` | Todo de una corrida: métricas, archivos e incidencias |
| `visitas_listar_archivos` | Estado de cada archivo en su máquina de estados |
| `visitas_consultar_errores` | Qué se rechazó, dónde estaba y qué hacer al respecto |
| `visitas_explicar_codigo` | El catálogo de validaciones y la acción del operador |
| `visitas_diagnosticar` | **Herramienta de flujo.** Qué falló, en qué fase, qué hacer |
| `visitas_reconciliar` | Los puntos de control bajo demanda, con el cuadre por capa |

`visitas_diagnosticar` es la que carga el peso. En vez de que el agente arme el
diagnóstico con cinco consultas, aplica los controles que importan y devuelve hallazgos
priorizados con su remediación, incluidos los que solo se ven al cruzar tablas.

### Interpretación

| Herramienta | Qué hace |
|---|---|
| `visitas_casos_ambiguos` | Devuelve los registros que el ETL marcó a propósito, con la regla aplicable y la pregunta de negocio abierta |
| `visitas_registrar_dictamen` | Guarda la clasificación del agente con justificación y confianza |
| `visitas_listar_dictamenes` | Los dictámenes registrados, para revisión humana |

Seis tipos de ambigüedad, todos derivados de los supuestos que el proceso dejó sin cerrar:
badmail con actividad, badmail perdido al deduplicar, fecha anterior al envío, viral mayor
que el total, baja con actividad y clic sin apertura.

### Ingesta

| Herramienta | Qué hace |
|---|---|
| `visitas_perfilar_archivo` | Perfila un archivo plano: estructura, tipos, ausencias, llaves candidatas y anomalías |
| `visitas_proponer_validaciones` | Genera DDL de staging y catálogo de validaciones candidatas |

El perfilado es determinista y detecta el patrón CRLF-con-comillas que provocó la pérdida
silenciosa de 73 registros en el caso 5. Sobre las llaves candidatas devuelve el
porcentaje de unicidad y **no un veredicto**: que una combinación sea única en la muestra
no prueba que sea la llave de negocio, y confundir las dos cosas es lo que lleva a
deduplicar borrando información real.

### Práctica

| Herramienta | Qué hace |
|---|---|
| `visitas_caso_practica` | Saca un caso real de la base y lo plantea como situación, con respuesta modelo opcional |

No usa preguntas enlatadas: toma una corrida, una incidencia o una anomalía que de verdad
está en la base. Si el estado cambia, el caso cambia.

---

## Cómo correrlo

```bash
# 1. Levantar el ETL del caso 5 y dejar la base con datos
cd ../5_ETL_Visitas_Web
python3 python/generar_datos.py
docker compose up -d
docker exec -i etl_visitas_mysql mysql -uetl -petl --default-character-set=utf8mb4 \
  etl_visitas < sql/01_ddl.sql
./restaurar.sh && python3 python/etl_visitas.py

# 2. Tabla de dictámenes (aditiva: no toca el esquema del ETL)
cd ../6_Agente_MCP_ETL
docker exec -i etl_visitas_mysql mysql -uetl -petl --default-character-set=utf8mb4 \
  etl_visitas < sql/06_agente_dictamenes.sql

# 3. Dependencias y verificación de las 14 herramientas
pip install -r requirements.txt
python3 prueba_herramientas.py
```

> La bandera `--default-character-set=utf8mb4` no es opcional. Sin ella el catálogo de
> validaciones queda con doble codificación (`número` → `nÃºmero`) y el texto que ve el
> operador sale ilegible.

### Conectarlo a un cliente MCP

```json
{
  "mcpServers": {
    "etl-visitas": {
      "command": "python3",
      "args": ["/ruta/absoluta/a/6_Agente_MCP_ETL/server.py"],
      "env": {
        "ETL_DB_HOST": "127.0.0.1",
        "ETL_DB_PORT": "3306",
        "ETL_DB_USER": "etl",
        "ETL_DB_PASSWORD": "etl",
        "ETL_DB_NAME": "etl_visitas"
      }
    }
  }
}
```

Son las mismas variables que usa `etl_visitas.py`, así que el servidor se conecta al mismo
entorno sin configuración adicional. Ninguna credencial vive en el código.

---

## Decisiones de implementación

**pymysql envuelto en `asyncio.to_thread`.** El driver es síncrono. Cambiar a `aiomysql`
habría alineado el stack, pero también habría metido una segunda forma de hablar con la
base en un proyecto que ya usa pymysql en el ETL. Envolver las llamadas mantiene un solo
driver y no bloquea el bucle de eventos.

**Conexión por llamada, sin pool.** Un servidor MCP local atiende una conversación a la
vez. Un pool agrega estado que hay que invalidar cuando la base se reinicia, a cambio de
un ahorro que aquí no se nota.

**Solo lectura sobre las tablas del ETL.** La única escritura es `dictamen_agente`. El
agente opina sobre los datos del proceso; no los modifica.

**Markdown por omisión, JSON a petición.** El markdown es para quien opera; el JSON para
encadenar herramientas. La lógica de formato vive en un módulo compartido.

**Errores accionables.** Cada fallo de conexión dice qué revisar: base caída, credenciales,
esquema faltante. Un agente que recibe «Error 2003» no sabe qué hacer; uno que recibe
«verifica que la base esté levantada o ajusta ETL_DB_HOST» sí.

---

## Estructura

```
6_Agente_MCP_ETL/
├── server.py                      14 herramientas, modelos y formato de salida
├── db.py                          conexión, errores accionables, helpers async
├── formato.py                     markdown/JSON compartido, tablas, paginación
├── perfilado.py                   perfilado determinista de archivos planos
├── prueba_herramientas.py         ejercita las 14 contra la base
├── ver.py                         inspección manual de una herramienta
├── evaluacion.xml                 10 preguntas con respuesta verificable
├── sql/06_agente_dictamenes.sql   tabla de dictámenes (aditiva)
├── requirements.txt
└── README.md
```

---

## Límites conocidos

- **`wrk_visitas` es efímera.** Se reconstruye en cada corrida, así que PC-5 a PC-8 solo
  se pueden evaluar después de una transformación exitosa. `visitas_reconciliar` lo
  detecta y lo dice en vez de fallar.
- **Los dictámenes no se propagan.** Registrar un dictamen no modifica `estadistica` ni
  cambia el comportamiento del ETL. Es deliberado: primero se acumula evidencia y se mide
  el acierto del agente contra la revisión humana; automatizar la acción viene después, si
  los números lo justifican.
- **`visitas_proponer_validaciones` no ejecuta nada.** Genera DDL como texto. Crear tablas
  desde un agente es una operación destructiva que merece revisión humana explícita.
- **Faltan pruebas de fallo del propio servidor.** Se ejercitan las 14 herramientas con 30
  casos, incluidos los caminos de error de entrada (código inexistente, archivo
  inexistente, llave ausente). Falta cubrir base caída a media consulta.
