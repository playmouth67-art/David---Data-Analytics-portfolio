-- =====================================================================
-- 05_reconciliacion.sql  --  Puntos de control post-ejecución
-- =====================================================================
-- Suite de verificación que se ejecuta después del ETL. Cada bloque es
-- un punto de control con un resultado esperado explícito.
--
-- Uso:
--   docker exec -i etl_visitas_mysql mysql -uetl -petl etl_visitas -t < sql/05_reconciliacion.sql
-- =====================================================================

USE etl_visitas;

-- ---------------------------------------------------------------------
-- PC-1  Control de ejecución: la corrida terminó y con qué estatus
-- ---------------------------------------------------------------------
SELECT 'PC-1 EJECUCION' AS punto_control;
SELECT id_ejecucion, estatus, fecha_inicio, fecha_fin,
       archivos_detectados, archivos_cargados,
       TIMESTAMPDIFF(SECOND, fecha_inicio, fecha_fin) AS segundos
FROM etl_ejecucion ORDER BY id_ejecucion;

-- ---------------------------------------------------------------------
-- PC-2  Control de archivos: cada archivo llegó a PURGADO_ORIGEN
-- ---------------------------------------------------------------------
SELECT 'PC-2 ARCHIVOS' AS punto_control;
SELECT id_archivo, nombre_archivo, LEFT(hash_archivo,12) AS hash, bytes,
       estatus, registros_leidos, archivo_zip
FROM etl_archivo ORDER BY id_archivo;

-- ---------------------------------------------------------------------
-- PC-3  Conteo por capa.
--       staging y trabajo llevan todo lo que traian los archivos.
--       estadistica lleva el detalle de cada envio seleccionado.
--       visita y visitante solo los clics: son las visitas reales al sitio.
-- ---------------------------------------------------------------------
SELECT 'PC-3 CONTEO POR CAPA' AS punto_control;
SELECT 'stg_visitas'  AS capa, COUNT(*) AS registros FROM stg_visitas
UNION ALL SELECT 'wrk_visitas', COUNT(*) FROM wrk_visitas
UNION ALL SELECT 'estadistica', COUNT(*) FROM estadistica
UNION ALL SELECT 'visita  (solo clics)',   COUNT(*) FROM visita
UNION ALL SELECT 'visitante',              COUNT(*) FROM visitante
UNION ALL SELECT 'suma de clics',          IFNULL(SUM(clicks),0) FROM visita;

-- ---------------------------------------------------------------------
-- PC-4  Cuadre origen -> destino por archivo. Esperado 503/501,
--       503/501, 995/995. La diferencia debe ser exactamente 4.
-- ---------------------------------------------------------------------
SELECT 'PC-4 CUADRE POR ARCHIVO' AS punto_control;
SELECT a.nombre_archivo,
       a.registros_leidos                        AS leidos,
       COUNT(w.id_stg)                           AS en_trabajo,
       SUM(w.rn = 1)                             AS seleccionados,
       SUM(w.rn > 1)                             AS descartados_dup,
       SUM(w.rn IS NULL)                         AS rechazados
FROM etl_archivo a
LEFT JOIN wrk_visitas w ON w.id_archivo = a.id_archivo
GROUP BY a.id_archivo, a.nombre_archivo, a.registros_leidos
ORDER BY a.nombre_archivo;

-- ---------------------------------------------------------------------
-- PC-5  Auditoría. Esperado: V-07 = 4, V-08 = 234, V-09 = 3, V-10 = 1.
--       Ningún registro se pierde en silencio.
-- ---------------------------------------------------------------------
SELECT 'PC-5 AUDITORIA' AS punto_control;
SELECT e.codigo_error, c.nombre, e.severidad, COUNT(*) AS total
FROM errores e LEFT JOIN cat_validacion c ON c.codigo_error = e.codigo_error
GROUP BY e.codigo_error, c.nombre, e.severidad
ORDER BY e.codigo_error;

-- ---------------------------------------------------------------------
-- PC-6  Trazabilidad del id_ejecucion en la auditoría.
--       Esperado: 0 filas con id_ejecucion distinto al de la corrida.
-- ---------------------------------------------------------------------
SELECT 'PC-6 TRAZABILIDAD EJECUCION' AS punto_control;
SELECT id_ejecucion, COUNT(*) AS errores_registrados
FROM errores GROUP BY id_ejecucion;

-- ---------------------------------------------------------------------
-- PC-7  Los 4 descartados por duplicado, con nombre y línea de origen.
-- ---------------------------------------------------------------------
SELECT 'PC-7 DESCARTADOS POR DUPLICADO' AS punto_control;
SELECT nombre_archivo, num_linea, valor_original, descripcion
FROM errores WHERE codigo_error = 'V-07'
ORDER BY nombre_archivo, num_linea;

-- ---------------------------------------------------------------------
-- PC-8  Higiene CRLF. Esperado: 0 en ambas columnas.
--       Valida el fix del retorno de carro en la última columna.
-- ---------------------------------------------------------------------
SELECT 'PC-8 HIGIENE CRLF' AS punto_control;
SELECT SUM(plataformas LIKE '%\r') AS stg_con_cr,
       (SELECT COUNT(*) FROM wrk_visitas WHERE plataformas LIKE '%\r') AS wrk_con_cr
FROM stg_visitas;

SELECT 'PC-8b VALORES DE PLATAFORMAS' AS punto_control;
SELECT IFNULL(plataformas,'(NULL)') AS plataformas, COUNT(*) AS total
FROM wrk_visitas GROUP BY plataformas ORDER BY total DESC LIMIT 10;

-- ---------------------------------------------------------------------
-- PC-9  Integridad de destino: sin nulos en llaves, sin fechas absurdas.
-- ---------------------------------------------------------------------
SELECT 'PC-9 INTEGRIDAD DESTINO' AS punto_control;
SELECT
    (SELECT COUNT(*) FROM estadistica WHERE email IS NULL OR fecha_envio IS NULL) AS est_llave_nula,
    (SELECT COUNT(*) FROM visitante WHERE visitasTotales <= 0)                    AS vte_sin_visitas,
    (SELECT COUNT(*) FROM visitante WHERE fechaPrimeraVisita > fechaUltimaVisita)  AS vte_fechas_invertidas,
    (SELECT COUNT(DISTINCT email) FROM visita)                                    AS emails_unicos_visita,
    (SELECT COUNT(*) FROM visitante)                                              AS filas_visitante;
