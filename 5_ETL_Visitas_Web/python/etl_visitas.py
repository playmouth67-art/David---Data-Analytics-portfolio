import os
import hashlib
import pymysql
import zipfile
import csv
from datetime import datetime, timedelta
from pymysql.constants import CLIENT

from origen import crear_origen

# ==========================================
# RUTAS AUTORITATIVAS DEL PROYECTO
# ==========================================
BASE_DIR = os.environ.get(
    'ETL_BASE_DIR',
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LANDING_DIR = os.path.join(BASE_DIR, 'data/landing')
BACKUP_DIR = os.environ.get('ETL_BACKUP_DIR', os.path.join(BASE_DIR, 'data/backup'))
SQL_FILE = os.path.join(BASE_DIR, 'sql/02_transformacion.sql')

os.makedirs(LANDING_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)

# ==========================================
# CONFIGURACIÓN
# ==========================================
# Las credenciales se leen del entorno. Los valores por omisión son los
# del contenedor de desarrollo; en productivo se inyectan por variables
# de entorno o gestor de secretos, nunca desde el repositorio.
DB_CONFIG = {
    'host': os.environ.get('ETL_DB_HOST', '127.0.0.1'),
    'port': int(os.environ.get('ETL_DB_PORT', '3306')),
    'user': os.environ.get('ETL_DB_USER', 'etl'),
    'password': os.environ.get('ETL_DB_PASSWORD', 'etl'),
    'database': os.environ.get('ETL_DB_NAME', 'etl_visitas'),
    'charset': 'utf8mb4',
    'local_infile': True,
    'client_flag': CLIENT.MULTI_STATEMENTS,
    'cursorclass': pymysql.cursors.DictCursor
}

QUIET_PERIOD_MINUTES = 10
EXPECTED_COLUMNS = 15

# Horas tras las cuales una ejecución en curso se considera colgada y deja de
# bloquear. Sin esto, un proceso muerto sin cerrar bloquearía el ETL para
# siempre y haría falta intervención manual todos los días.
HORAS_EJECUCION_COLGADA = 6

# Layout esperado. La posición 2 va como None a propósito: su encabezado
# cambia entre archivos (jk, jyv, fgh) y el campo llega vacío siempre. Se
# conserva por posición, no por nombre. Es el supuesto S-6 del documento.
ENCABEZADO_ESPERADO = [
    'email', None, 'badmail', 'baja', 'fecha envio', 'fecha open', 'opens',
    'opens virales', 'fecha click', 'clicks', 'clicks virales', 'links',
    'ips', 'navegadores', 'plataformas',
]


def get_db_connection():
    return pymysql.connect(**DB_CONFIG)

def calculate_sha256(filepath):
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b""):
            h.update(chunk)
    return h.hexdigest()

def normalizar_a_lf(origen, destino):
    """Reescribe el archivo con saltos de linea LF y devuelve cuantos convirtio.

    Por que existe esta funcion: los archivos de origen vienen con CRLF. Si se
    cargan asi con LINES TERMINATED BY '\\n', el \\r queda pegado despues de la
    comilla de cierre del ultimo campo. MySQL pierde el control del
    OPTIONALLY ENCLOSED BY y absorbe los renglones siguientes hasta encontrar
    otra comilla, perdiendo registros en silencio.

    La normalizacion se hace en la zona de aterrizaje, nunca sobre el archivo
    original: este se conserva intacto para el respaldo y para la huella
    SHA-256 que da la identidad de contenido usada en la idempotencia.
    """
    with open(origen, 'rb') as f:
        raw = f.read()
    convertidos = raw.count(b'\r\n')
    normalizado = raw.replace(b'\r\n', b'\n').replace(b'\r', b'\n')
    with open(destino, 'wb') as f:
        f.write(normalizado)
    return convertidos


def validar_estructura_csv(filepath):
    """Valida el layout del archivo. Devuelve (filas_de_datos, discrepancias).

    Lo estructural (V-01) es motivo de rechazo: sin 15 columnas no hay forma
    segura de mapear los campos. Los nombres de encabezado (V-02) son solo
    advertencia: si la estructura está bien, el archivo se puede cargar y lo
    que corresponde es avisar al proveedor del origen.
    """
    if os.path.getsize(filepath) == 0:
        raise ValueError("El archivo está vacío.")

    filas = 0
    discrepancias = []
    with open(filepath, 'r', encoding='utf-8-sig', newline='') as f:
        reader = csv.reader(f, delimiter=',', quotechar='"')
        headers = next(reader, None)

        # --- V-01: estructura (RECHAZO) ---
        if not headers or len(headers) != EXPECTED_COLUMNS:
            raise ValueError(f"Layout inválido en cabecera. Esperadas: {EXPECTED_COLUMNS}.")

        if headers[0].strip().lower() != 'email' or headers[4].strip().lower() != 'fecha envio':
            raise ValueError("Layout inválido: 'email' o 'Fecha envio' no están en la posición esperada.")

        # --- V-02: nombres de encabezado (ADVERTENCIA) ---
        for i, esperado in enumerate(ENCABEZADO_ESPERADO):
            if esperado is None:
                continue
            recibido = headers[i].strip().lower()
            if recibido != esperado:
                discrepancias.append((i + 1, esperado, headers[i].strip()))

        for i, row in enumerate(reader, start=2):
            if not any(field.strip() for field in row):
                continue
            if len(row) != EXPECTED_COLUMNS:
                raise ValueError(f"Error estructural en línea {i}: {len(row)} columnas.")
            filas += 1
    return filas, discrepancias


def verificar_reconciliacion(cursor, exec_id):
    """Ejecuta los puntos de control de cierre PC-5 a PC-9.

    Devuelve la lista de puntos que fallaron. Que esta función exista dentro
    del orquestador y no solo como script SQL es lo que permite que un
    descuadre marque la ejecución como FALLIDA en lugar de depender de que
    alguien lea la salida de una consulta.
    """
    fallos = []

    def check(pc, descripcion, sql, params=None):
        # Sin parámetros se ejecuta la consulta tal cual: si se pasa una tupla
        # vacía, pymysql intenta interpolar y revienta con cualquier '%'
        # literal, como el del LIKE de PC-8.
        if params:
            cursor.execute(sql, params)
        else:
            cursor.execute(sql)
        r = cursor.fetchone()
        valores = list(r.values())
        ok = all(v == 0 for v in valores)
        estado = 'OK  ' if ok else 'FALLA'
        print(f"    [{estado}] {pc}  {descripcion}")
        if not ok:
            fallos.append(f"{pc}: {descripcion} -> {r}")

    # PC-5: nada se pierde entre staging y la capa de trabajo
    check('PC-5', 'staging = trabajo',
          "SELECT (SELECT COUNT(*) FROM stg_visitas) - (SELECT COUNT(*) FROM wrk_visitas) AS d")

    # PC-6: por archivo, lo leído es lo que llegó a la capa de trabajo
    check('PC-6', 'cuadre por archivo',
          """SELECT COUNT(*) AS d FROM (
                SELECT a.id_archivo
                FROM etl_archivo a JOIN wrk_visitas w ON w.id_archivo = a.id_archivo
                WHERE a.id_ejecucion = %s
                GROUP BY a.id_archivo, a.registros_leidos
                HAVING COUNT(w.id_stg) <> a.registros_leidos) x""", (exec_id,))

    # PC-7: todo descarte por duplicado tiene su registro en errores
    check('PC-7', 'descartes auditados',
          """SELECT (SELECT COUNT(*) FROM wrk_visitas WHERE rn > 1)
                  - (SELECT COUNT(*) FROM errores
                     WHERE id_ejecucion = %s AND codigo_error = 'V-07') AS d""", (exec_id,))

    # PC-8: higiene de codificación; ningún retorno de carro residual
    check('PC-8', 'higiene de saltos de línea',
          r"""SELECT (SELECT COUNT(*) FROM wrk_visitas WHERE plataformas LIKE '%\r')
                   + (SELECT COUNT(*) FROM wrk_visitas WHERE navegadores LIKE '%\r') AS d""")

    # PC-9: integridad del destino y coherencia del agregado
    check('PC-9', 'integridad del destino',
          """SELECT
               (SELECT COUNT(*) FROM estadistica WHERE email IS NULL OR fecha_envio IS NULL) AS llave_nula,
               (SELECT COUNT(*) FROM visitante WHERE visitasTotales <= 0)                    AS sin_visitas,
               (SELECT COUNT(*) FROM visitante WHERE fechaPrimeraVisita > fechaUltimaVisita)  AS fechas_invertidas,
               (SELECT COUNT(DISTINCT email) FROM visita)
                 - (SELECT COUNT(*) FROM visitante)                                          AS agregado_descuadrado""")

    return fallos

def main():
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Iniciando ETL de visitas...")
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # PC-0: nunca dos corridas a la vez. Ambas competirían por stg_visitas y
    # por las tablas de trabajo, que se reconstruyen en cada ejecución.
    cursor.execute("""
        SELECT id_ejecucion, fecha_inicio FROM etl_ejecucion
        WHERE estatus = 'EN_CURSO'
          AND fecha_inicio > NOW() - INTERVAL %s HOUR
        ORDER BY id_ejecucion DESC LIMIT 1
    """, (HORAS_EJECUCION_COLGADA,))
    viva = cursor.fetchone()
    if viva:
        print(f"[ABORTA] PC-0: la ejecución {viva['id_ejecucion']} sigue EN_CURSO "
              f"desde {viva['fecha_inicio']}. No se lanza una segunda corrida.")
        cursor.close()
        conn.close()
        return 3

    cursor.execute("INSERT INTO etl_ejecucion (fecha_negocio, fecha_inicio, estatus) VALUES (CURDATE(), NOW(), 'EN_CURSO')")
    exec_id = cursor.lastrowid
    conn.commit()
    print(f"[*] Ejecución ID: {exec_id} registrada.")
    
    archivos_procesados = 0
    archivos_error = 0
    staging_limpio = False

    # El origen se resuelve por configuración: directorio local en
    # desarrollo, SFTP en productivo. Ver python/origen.py.
    origen = crear_origen(BASE_DIR)
    print(f"[*] Origen: {origen}")
    archivos_encontrados = origen.listar()

    try:

        for arch in archivos_encontrados:
            filename = arch.nombre

            # Quiet period: un archivo modificado hace muy poco puede estar
            # escribiéndose todavía. Se deja para la corrida siguiente en
            # vez de arriesgar una carga parcial.
            if datetime.now() - arch.mtime < timedelta(minutes=QUIET_PERIOD_MINUTES):
                print(f"  [SKIP] {filename}: Ignorado por Quiet Period.")
                continue

            print(f"\n[*] Procesando: {filename}")

            # Descarga a .part y rename atómico: si el proceso muere a la
            # mitad, en landing nunca queda un archivo aparentemente completo.
            part_path = os.path.join(LANDING_DIR, filename + '.part')
            final_path = os.path.join(LANDING_DIR, filename)
            origen.descargar(filename, part_path)

            if os.path.getsize(part_path) != arch.bytes:
                print(f"  [ERROR] {filename}: Inconsistencia en tamaño de descarga.")
                os.remove(part_path)
                archivos_error += 1
                continue
            os.rename(part_path, final_path)

            file_hash = calculate_sha256(final_path)
            cursor.execute("SELECT estatus FROM etl_archivo WHERE hash_archivo = %s", (file_hash,))
            if cursor.fetchone():
                print(f"  [SKIP] {filename}: Hash {file_hash[:8]}... ya procesado.")
                os.remove(final_path)
                continue
                
            cursor.execute("""
                INSERT INTO etl_archivo (id_ejecucion, nombre_archivo, hash_archivo, bytes,
                                         fecha_modif_origen, fecha_deteccion, fecha_carga, estatus)
                VALUES (%s, %s, %s, %s, %s, NOW(), NOW(), 'DESCARGADO')
            """, (exec_id, filename, file_hash, arch.bytes, arch.mtime))
            archivo_id = cursor.lastrowid
            conn.commit()

            # Copia normalizada a LF, solo para la carga. El original no se toca.
            load_path = final_path + '.load'
            crlf_convertidos = normalizar_a_lf(final_path, load_path)
            if crlf_convertidos:
                print(f"  [*] Normalizados {crlf_convertidos} saltos de línea CRLF -> LF.")

            try:
                filas_esperadas, discrepancias = validar_estructura_csv(load_path)
            except Exception as e:
                print(f"  [ERROR] V-01 Validación estructural: {e}")
                cursor.execute("UPDATE etl_archivo SET estatus = 'RECHAZADO', motivo_rechazo = %s WHERE id_archivo = %s", (str(e), archivo_id))
                cursor.execute("""
                    INSERT INTO errores (id_ejecucion, id_archivo, nombre_archivo, codigo_error,
                                         severidad, campo, descripcion)
                    VALUES (%s, %s, %s, 'V-01', 'RECHAZO', 'layout', %s)
                """, (exec_id, archivo_id, filename, str(e)[:255]))
                conn.commit()
                archivos_error += 1
                os.remove(load_path)
                os.remove(final_path)
                continue

            # V-02: la estructura es válida pero algún encabezado no coincide.
            # Es advertencia: el archivo se carga y se reporta al origen.
            for pos, esperado, recibido in discrepancias:
                print(f"  [AVISO] V-02 columna {pos}: se esperaba '{esperado}', llegó '{recibido}'.")
                cursor.execute("""
                    INSERT INTO errores (id_ejecucion, id_archivo, nombre_archivo, num_linea,
                                         codigo_error, severidad, campo, valor_original, descripcion)
                    VALUES (%s, %s, %s, 1, 'V-02', 'ADVERTENCIA', %s, %s, %s)
                """, (exec_id, archivo_id, filename, esperado, recibido,
                      f"Encabezado en posición {pos} no coincide con el layout esperado"))

            cursor.execute("UPDATE etl_archivo SET estatus = 'VALIDADO' WHERE id_archivo = %s", (archivo_id,))
            conn.commit()

            print(f"  [*] Cargando {filas_esperadas} filas a staging...")
            # Staging se limpia de forma perezosa: solo si de verdad hay algo
            # que cargar. Asi una corrida sin archivos nuevos deja intacto el
            # estado de la corrida anterior y la reconciliacion sigue cuadrando.
            if not staging_limpio:
                cursor.execute("TRUNCATE TABLE stg_visitas")
                conn.commit()
                staging_limpio = True

            cursor.execute("SET sql_mode = 'STRICT_ALL_TABLES';")
            # Arranca en 1 para que num_linea sea la linea fisica del archivo
            # (la 1 es el encabezado). Asi el numero es abrible en un editor.
            cursor.execute("SET @row_num = 1;")
            load_query = """
                LOAD DATA LOCAL INFILE %s INTO TABLE stg_visitas
                CHARACTER SET utf8mb4 FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' LINES TERMINATED BY '\\n' IGNORE 1 LINES
                (@col1, @col2, @col3, @col4, @col5, @col6, @col7, @col8, @col9, @col10, @col11, @col12, @col13, @col14, @col15)
                SET id_archivo = %s, num_linea = @row_num := @row_num + 1,
                    email = NULLIF(TRIM(@col1), ''), jyv = NULLIF(TRIM(@col2), ''), badmail = NULLIF(TRIM(@col3), ''), baja = NULLIF(TRIM(@col4), ''),
                    fecha_envio = NULLIF(TRIM(@col5), ''), fecha_open = NULLIF(TRIM(@col6), ''), opens = NULLIF(TRIM(@col7), ''), opens_virales = NULLIF(TRIM(@col8), ''),
                    fecha_click = NULLIF(TRIM(@col9), ''), clicks = NULLIF(TRIM(@col10), ''), clicks_virales = NULLIF(TRIM(@col11), ''), links = NULLIF(TRIM(@col12), ''),
                    ips = NULLIF(TRIM(@col13), ''), navegadores = NULLIF(TRIM(@col14), ''),
                    plataformas = NULLIF(TRIM(TRIM(TRAILING '\\r' FROM @col15)), '');
            """
            cursor.execute(load_query, (load_path, archivo_id))

            # PC de carga: lo que MySQL insertó debe cuadrar con lo que
            # Python contó al validar. Si no cuadra, el archivo se rechaza
            # en vez de dejar pasar una pérdida silenciosa de registros.
            cursor.execute("SELECT COUNT(*) AS n FROM stg_visitas WHERE id_archivo = %s", (archivo_id,))
            filas_cargadas = cursor.fetchone()['n']
            if filas_cargadas != filas_esperadas:
                msg = f"Descuadre de carga: esperadas {filas_esperadas}, cargadas {filas_cargadas}."
                print(f"  [ERROR] {msg}")
                # Rechazar el archivo no basta: las filas que MySQL alcanzo a
                # insertar siguen en staging, y la transformacion lee toda la
                # tabla sin mirar el estatus del archivo. Sin este DELETE, un
                # archivo RECHAZADO igual llega a estadistica, visita y
                # visitante. Es el mismo fallo silencioso que este punto de
                # control existe para evitar.
                cursor.execute("DELETE FROM stg_visitas WHERE id_archivo = %s", (archivo_id,))
                cursor.execute("UPDATE etl_archivo SET estatus = 'RECHAZADO', motivo_rechazo = %s WHERE id_archivo = %s", (msg, archivo_id))
                cursor.execute("""
                    INSERT INTO errores (id_ejecucion, id_archivo, nombre_archivo, codigo_error,
                                         severidad, campo, descripcion)
                    VALUES (%s, %s, %s, 'V-01', 'RECHAZO', 'carga', %s)
                """, (exec_id, archivo_id, filename, msg[:255]))
                conn.commit()
                archivos_error += 1
                os.remove(load_path)
                os.remove(final_path)
                continue

            os.remove(load_path)
            cursor.execute("UPDATE etl_archivo SET estatus = 'CARGADO', registros_leidos = %s WHERE id_archivo = %s", (filas_esperadas, archivo_id))
            conn.commit()
            archivos_procesados += 1
            
            zip_filename = f"{filename.replace('.txt', '')}_{datetime.now().strftime('%Y%m%d%H%M%S')}.zip"
            zip_filepath = os.path.join(BACKUP_DIR, zip_filename)
            
            with zipfile.ZipFile(zip_filepath, 'w', zipfile.ZIP_DEFLATED) as zf:
                zf.write(final_path, arcname=filename)
                
            with zipfile.ZipFile(zip_filepath, 'r') as zf:
                if zf.testzip() is not None:
                    raise RuntimeError(f"ZIP corrupto para {filename}")
            
            cursor.execute("UPDATE etl_archivo SET estatus = 'RESPALDADO', archivo_zip = %s WHERE id_archivo = %s", (zip_filename, archivo_id))
            conn.commit()

            # El borrado en origen es lo último y solo ocurre después de que
            # el ZIP quedó escrito y verificado. Nunca al revés.
            origen.eliminar(filename)
            os.remove(final_path)
            cursor.execute("UPDATE etl_archivo SET estatus = 'PURGADO_ORIGEN' WHERE id_archivo = %s", (archivo_id,))
            conn.commit()
            print(f"  [SUCCESS] Archivo respaldado y purgado de origen.")

        if archivos_procesados > 0:
            print("\n[*] Ejecutando reglas de negocio y transformación SQL...")
            with open(SQL_FILE, 'r', encoding='utf-8') as f:
                sql_script = f.read()
            cursor.execute(f"SET @id_ejecucion = {exec_id};")
            cursor.execute(sql_script)
            # MULTI_STATEMENTS deja result sets pendientes: hay que drenarlos
            # o la siguiente consulta falla con "Commands out of sync".
            while cursor.nextset():
                pass
            conn.commit()
            print("  [SUCCESS] Transformación y consolidación finalizada.")

        estatus_final = 'OK' if archivos_error == 0 else 'OK_CON_ADVERTENCIAS'
        if archivos_procesados == 0 and archivos_error == 0:
            estatus_final = 'OK'

        # Reconciliación de cierre. Solo tiene sentido si esta corrida cargó
        # algo: sin archivos nuevos, las tablas de trabajo son de otra corrida.
        fallos_pc = []
        if archivos_procesados > 0:
            print("\n[*] Verificando puntos de control de cierre...")
            fallos_pc = verificar_reconciliacion(cursor, exec_id)
            if fallos_pc:
                estatus_final = 'FALLIDO'
                print(f"  [ERROR] {len(fallos_pc)} punto(s) de control fallaron.")
            else:
                print("  [SUCCESS] Los 5 puntos de control de cierre pasaron.")

        # Bitácora de control: alimenta el reporte mensual de archivos y
        # registros procesados que pide el requerimiento. Se calcula desde
        # las tablas, no desde contadores en memoria, para que el dato del
        # reporte sea el mismo que el de la base.
        # registros_cargados son los que efectivamente llegaron al destino:
        # los representantes seleccionados. No es "leídos menos rechazos",
        # porque los descartados por duplicado tampoco se cargan.
        cursor.execute("""
            SELECT
              (SELECT IFNULL(SUM(registros_leidos),0) FROM etl_archivo WHERE id_ejecucion = %s) AS leidos,
              (SELECT COUNT(*) FROM errores WHERE id_ejecucion = %s AND severidad = 'RECHAZO')     AS rechazos,
              (SELECT COUNT(*) FROM errores WHERE id_ejecucion = %s AND severidad = 'ADVERTENCIA') AS advertencias
        """, (exec_id, exec_id, exec_id))
        m = cursor.fetchone()

        if archivos_procesados > 0:
            cursor.execute("SELECT COUNT(*) AS n FROM wrk_visitas WHERE rn = 1")
            cargados = cursor.fetchone()['n']
        else:
            cargados = 0

        mensaje = ' | '.join(fallos_pc)[:500] if fallos_pc else None
        cursor.execute("""
            UPDATE etl_ejecucion
            SET estatus = %s, fecha_fin = NOW(), mensaje = %s,
                archivos_detectados = %s, archivos_cargados = %s, archivos_rechazados = %s,
                registros_leidos = %s, registros_cargados = %s,
                registros_error = %s, registros_advertencia = %s,
                duracion_segundos = TIMESTAMPDIFF(SECOND, fecha_inicio, NOW()),
                host_ejecucion = %s
            WHERE id_ejecucion = %s
        """, (estatus_final, mensaje, len(archivos_encontrados), archivos_procesados, archivos_error,
              m['leidos'], cargados,
              m['rechazos'], m['advertencias'],
              os.uname().nodename, exec_id))
        conn.commit()
        print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Orquestación finalizada con estatus: {estatus_final}")
        if estatus_final == 'FALLIDO':
            return 2
        return 0 if estatus_final == 'OK' else 1

    except Exception as e:
        conn.rollback()
        print(f"\n[FATAL ERROR] {e}")
        cursor.execute("UPDATE etl_ejecucion SET estatus = 'FALLIDO', fecha_fin = NOW(), mensaje = %s WHERE id_ejecucion = %s", (str(e)[:500], exec_id))
        conn.commit()
        # Código de salida distinto de cero: es la señal que el agendador
        # (cron/Airflow) necesita para disparar la alerta al equipo operativo.
        return 2
    finally:
        origen.cerrar()
        cursor.close()
        conn.close()


if __name__ == '__main__':
    raise SystemExit(main())