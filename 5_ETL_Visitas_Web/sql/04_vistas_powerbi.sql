USE etl_visitas;

CREATE OR REPLACE VIEW vw_bi_ejecuciones AS
SELECT e.*,
    ROUND(100.0 * e.registros_error / NULLIF(e.registros_leidos,0), 2)       AS pct_error,
    ROUND(100.0 * e.registros_advertencia / NULLIF(e.registros_leidos,0), 2) AS pct_advertencia,
    CASE
        WHEN e.estatus = 'FALLIDO' THEN 'ROJO'
        WHEN e.registros_error > 0.05 * NULLIF(e.registros_leidos,0) THEN 'ROJO'
        WHEN e.archivos_rechazados > 0 THEN 'AMARILLO'
        WHEN e.registros_error > 0 THEN 'AMARILLO'
        ELSE 'VERDE'
    END AS semaforo
FROM etl_ejecucion e;

-- Capa de presentación de visitante. El requerimiento pide fechaUltimaVisita
-- en formato yyyymmdd; se almacena como DATE (comparable y ordenable) y el
-- formato se aplica aquí, no en la tabla. Así el dato sigue siendo una fecha
-- para cualquier cálculo y el consumidor recibe el formato pedido.
CREATE OR REPLACE VIEW vw_visitante AS
SELECT email,
       DATE_FORMAT(fechaPrimeraVisita, '%Y%m%d') AS fechaPrimeraVisita,
       DATE_FORMAT(fechaUltimaVisita,  '%Y%m%d') AS fechaUltimaVisita,
       visitasTotales, visitasAnioActual, visitasMesActual,
       fecha_actualizacion
FROM visitante;

CREATE OR REPLACE VIEW vw_bi_errores AS
SELECT er.id_error, e.fecha_negocio, er.nombre_archivo, er.num_linea,
       er.codigo_error, c.nombre AS nombre_validacion,
       c.descripcion AS que_significa, c.accion_operacion AS que_hacer,
       er.severidad, er.campo, er.valor_original, er.descripcion AS detalle
FROM errores er
JOIN etl_ejecucion e ON e.id_ejecucion = er.id_ejecucion
LEFT JOIN cat_validacion c ON c.codigo_error = er.codigo_error;

CREATE OR REPLACE VIEW vw_bi_reporte_mensual AS
SELECT DATE_FORMAT(fecha_negocio,'%Y-%m') AS periodo,
       COUNT(DISTINCT id_ejecucion)       AS corridas,
       SUM(estatus='FALLIDO')             AS corridas_fallidas,
       SUM(archivos_cargados)             AS archivos_procesados,
       SUM(archivos_rechazados)           AS archivos_rechazados,
       SUM(registros_leidos)              AS registros_leidos,
       SUM(registros_cargados)            AS registros_cargados,
       SUM(registros_error)               AS registros_rechazados,
       ROUND(100.0*SUM(registros_cargados)/NULLIF(SUM(registros_leidos),0),2) AS pct_exito,
       ROUND(AVG(duracion_segundos),1)    AS duracion_promedio_seg
FROM etl_ejecucion
GROUP BY DATE_FORMAT(fecha_negocio,'%Y-%m');

CREATE OR REPLACE VIEW vw_bi_calidad_diaria AS
SELECT e.fecha_negocio, er.codigo_error, c.nombre AS nombre_validacion,
       er.severidad, COUNT(*) AS incidencias,
       COUNT(DISTINCT er.nombre_archivo) AS archivos_afectados
FROM errores er
JOIN etl_ejecucion e ON e.id_ejecucion = er.id_ejecucion
LEFT JOIN cat_validacion c ON c.codigo_error = er.codigo_error
GROUP BY e.fecha_negocio, er.codigo_error, c.nombre, er.severidad;

CREATE OR REPLACE VIEW vw_bi_estatus_actual AS
SELECT e.*, TIMESTAMPDIFF(HOUR, e.fecha_inicio, NOW()) AS horas_desde_inicio,
       IF(TIMESTAMPDIFF(HOUR, e.fecha_inicio, NOW()) > 26,
          'ALERTA: no hay corrida en más de 26 horas', 'Vigencia OK') AS alerta_vigencia
FROM vw_bi_ejecuciones e
WHERE e.id_ejecucion = (SELECT MAX(id_ejecucion) FROM etl_ejecucion);
