-- =====================================================================
-- 00_reset.sql  --  Reinicio controlado del entorno ETL
-- =====================================================================
-- Deja la base en estado inicial (estructura intacta, sin datos) para
-- poder ejecutar el ETL de forma reproducible desde cero.
--
-- NO borra la estructura: 01_ddl.sql no necesita volver a correrse.
-- Las tablas wrk_* sí se eliminan porque 02_transformacion.sql las
-- reconstruye con CREATE TABLE AS SELECT en cada ejecución.
--
-- Uso:
--   docker exec -i etl_visitas_mysql mysql -uetl -petl etl_visitas < sql/00_reset.sql
-- =====================================================================

USE etl_visitas;

SET FOREIGN_KEY_CHECKS = 0;

-- Capa de destino / consumo
TRUNCATE TABLE visitante;
TRUNCATE TABLE visita;
TRUNCATE TABLE estadistica;

-- Capa de auditoría
TRUNCATE TABLE errores;

-- Capa de staging
TRUNCATE TABLE stg_visitas;

-- Capa de control (el orden importa: etl_archivo referencia etl_ejecucion)
TRUNCATE TABLE etl_archivo;
TRUNCATE TABLE etl_ejecucion;

SET FOREIGN_KEY_CHECKS = 1;

-- Capa de trabajo (se regenera en cada transformación)
DROP TABLE IF EXISTS wrk_dedupe;
DROP TABLE IF EXISTS wrk_visitas;

-- cat_validacion NO se toca: es catálogo de referencia, no dato transaccional.
