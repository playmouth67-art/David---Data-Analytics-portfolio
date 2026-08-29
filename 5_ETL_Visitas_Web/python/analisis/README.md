# Scripts de análisis del origen

Estos scripts **no forman parte del proceso ETL**. Son las consultas que corrí
para entender los archivos antes de escribir una sola regla de negocio, y los
incluyo porque el requerimiento pide mostrar la lógica con la que llegué a la
solución.

Cada uno responde una pregunta concreta. Se ejecutan sobre `data/seed/` y no
tocan la base de datos. Los archivos de ese directorio son sintéticos: se
generan con `python3 python/generar_datos.py`.

| Script | Qué pregunta responde | Qué encontró |
|---|---|---|
| `profile_files.py` | ¿Qué hay en los archivos? Estructura, tamaño, número de columnas | 15 columnas, 3 archivos, 2,001 registros |
| `02_profile_values.py` | ¿Qué valores toma cada columna? | El catálogo de valores por campo |
| `03_check_duplicates.py` | ¿Se repite algún email? | Sí: direcciones que aparecen dos veces en el mismo archivo |
| `03_quality_and_business_rules.py` | ¿Qué combinaciones de campos son sospechosas? | Base de la matriz de reglas |
| `04_check_business_key.py` | ¿Sirve `email + fecha_envio` como llave? | **No.** Ver sección 9 de la propuesta |
| `05_check_exact_duplicates.py` | ¿Hay filas idénticas byte a byte? | Ninguna |
| `06_compare_files.py` | ¿Se cruzan los emails entre archivos? | 3 direcciones en report_7 y report_8 |
| `07_validate_dates.py` | ¿Alguna fecha viola el formato dd/mm/yyyy HH:mm? | Ninguna |
| `08_profile_missing_values.py` | ¿Cómo se representa la ausencia de dato? | Tres estados: valor, `-` y vacío |
| `11_check_all_scenarios.py` | Enumeración exhaustiva de escenarios de negocio | Alimentó el catálogo V-01 a V-10 |
| `12_verificar_cifras.py` | ¿Las cifras del documento salen de verdad de los archivos? | Reproduce las 8 cifras sin MySQL |

El hallazgo de `04_check_business_key.py` es el que más cambió el diseño: sin
él, habría deduplicado por `email + fecha_envio` y habría borrado registros con
información real de forma irreversible.

`12_verificar_cifras.py` es distinto de los demás: no es análisis previo, es
verificación posterior. Reimplementa la lógica de `sql/02_transformacion.sql`
en Python puro y comprueba que reproduce las cifras publicadas. Corre sin
Docker y sin base de datos, solo con Python 3, así que sirve para validar el
resultado en dos minutos antes de levantar nada.

## Producción

El proceso ETL vive en el directorio padre y son solo dos archivos:

- `../etl_visitas.py` — orquestador
- `../origen.py` — capa de acceso al origen (local o SFTP)
