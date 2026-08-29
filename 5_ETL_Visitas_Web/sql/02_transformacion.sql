USE etl_visitas;

DROP TABLE IF EXISTS wrk_visitas;
CREATE TABLE wrk_visitas AS
SELECT
    s.id_stg, s.id_archivo, s.num_linea,
    TRIM(s.email)                          AS email,
    NULLIF(NULLIF(TRIM(s.jyv),''),'-')     AS jyv,
    NULLIF(NULLIF(TRIM(s.badmail),''),'-') AS badmail,
    NULLIF(NULLIF(TRIM(s.baja),''),'-')    AS baja,
    TRIM(s.fecha_envio) AS fecha_envio_txt,
    TRIM(s.fecha_open)  AS fecha_open_txt,
    TRIM(s.fecha_click) AS fecha_click_txt,
    STR_TO_DATE(NULLIF(NULLIF(TRIM(s.fecha_envio),''),'-'), '%d/%m/%Y %H:%i') AS fecha_envio,
    STR_TO_DATE(NULLIF(NULLIF(TRIM(s.fecha_open),''),'-'),  '%d/%m/%Y %H:%i') AS fecha_open,
    STR_TO_DATE(NULLIF(NULLIF(TRIM(s.fecha_click),''),'-'), '%d/%m/%Y %H:%i') AS fecha_click,
    CASE WHEN TRIM(s.opens)          REGEXP '^[0-9]+$' THEN CAST(TRIM(s.opens) AS UNSIGNED)          ELSE 0 END AS opens,
    CASE WHEN TRIM(s.opens_virales)  REGEXP '^[0-9]+$' THEN CAST(TRIM(s.opens_virales) AS UNSIGNED)  ELSE 0 END AS opens_virales,
    CASE WHEN TRIM(s.clicks)         REGEXP '^[0-9]+$' THEN CAST(TRIM(s.clicks) AS UNSIGNED)         ELSE 0 END AS clicks,
    CASE WHEN TRIM(s.clicks_virales) REGEXP '^[0-9]+$' THEN CAST(TRIM(s.clicks_virales) AS UNSIGNED) ELSE 0 END AS clicks_virales,
    (TRIM(s.opens) REGEXP '^[0-9]+$' AND TRIM(s.clicks) REGEXP '^[0-9]+$') AS numericos_ok,
    NULLIF(NULLIF(TRIM(s.links),''),'-')       AS links,
    NULLIF(NULLIF(TRIM(s.ips),''),'-')         AS ips,
    NULLIF(NULLIF(TRIM(s.navegadores),''),'-') AS navegadores,
    NULLIF(NULLIF(TRIM(s.plataformas),''),'-') AS plataformas,
    (TRIM(s.email) REGEXP '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}$') AS email_ok,
    CONCAT_WS(',', s.email, s.jyv, s.badmail, s.baja, s.fecha_envio, s.fecha_open,
                   s.opens, s.opens_virales, s.fecha_click, s.clicks, s.clicks_virales,
                   s.links, s.ips, s.navegadores, s.plataformas) AS registro_completo
FROM stg_visitas s;

ALTER TABLE wrk_visitas ADD PRIMARY KEY (id_stg), ADD INDEX idx_nat (email, fecha_envio);
ALTER TABLE wrk_visitas ADD COLUMN rn INT NULL;

DROP TABLE IF EXISTS wrk_dedupe;
CREATE TABLE wrk_dedupe AS
SELECT id_stg,
       ROW_NUMBER() OVER (
           PARTITION BY email, fecha_envio
           ORDER BY opens DESC, clicks DESC, num_linea DESC
       ) AS rn
FROM wrk_visitas
WHERE email_ok = 1 AND fecha_envio IS NOT NULL;

ALTER TABLE wrk_dedupe ADD PRIMARY KEY (id_stg);
UPDATE wrk_visitas w JOIN wrk_dedupe d ON d.id_stg = w.id_stg SET w.rn = d.rn;

START TRANSACTION;

-- El orquestador inyecta @id_ejecucion antes de enviar este script.
-- El IFNULL permite ejecutarlo tambien standalone desde el CLI de MySQL.
SET @id_ejecucion = IFNULL(@id_ejecucion, 1);

INSERT INTO errores (id_ejecucion, id_archivo, nombre_archivo, num_linea, codigo_error, severidad, campo, valor_original, descripcion, registro_completo)
SELECT @id_ejecucion, w.id_archivo, a.nombre_archivo, w.num_linea, 'V-03', 'RECHAZO', 'email', LEFT(w.email,500), 'Email no cumple el patrón de correo válido', w.registro_completo
FROM wrk_visitas w JOIN etl_archivo a ON a.id_archivo = w.id_archivo
WHERE w.email_ok = 0 OR w.email IS NULL OR w.email = '';

INSERT INTO errores (id_ejecucion, id_archivo, nombre_archivo, num_linea, codigo_error, severidad, campo, valor_original, descripcion, registro_completo)
SELECT @id_ejecucion, w.id_archivo, a.nombre_archivo, w.num_linea, 'V-04', 'RECHAZO', 'Fecha envio', LEFT(w.fecha_envio_txt,500), 'Fecha envío nula o fuera del formato dd/mm/yyyy HH:mm', w.registro_completo
FROM wrk_visitas w JOIN etl_archivo a ON a.id_archivo = w.id_archivo
WHERE w.fecha_envio IS NULL AND w.email_ok = 1;

INSERT INTO errores (id_ejecucion, id_archivo, nombre_archivo, num_linea, codigo_error, severidad, campo, valor_original, descripcion, registro_completo)
SELECT @id_ejecucion, w.id_archivo, a.nombre_archivo, w.num_linea, 'V-07', 'ADVERTENCIA', 'email + Fecha envio', LEFT(CONCAT(w.email,' | ',w.fecha_envio_txt),500), 'Duplicado en el lote: se conservó el registro con más interacción', w.registro_completo
FROM wrk_visitas w JOIN etl_archivo a ON a.id_archivo = w.id_archivo
WHERE w.rn > 1;

INSERT INTO errores (id_ejecucion, id_archivo, nombre_archivo, num_linea, codigo_error, severidad, campo, valor_original, descripcion, registro_completo)
SELECT @id_ejecucion, w.id_archivo, a.nombre_archivo, w.num_linea, 'V-08', 'ADVERTENCIA', 'Fecha open', LEFT(CONCAT('envio=',w.fecha_envio_txt,' open=',w.fecha_open_txt),500), 'Fecha open anterior a Fecha envío', w.registro_completo
FROM wrk_visitas w JOIN etl_archivo a ON a.id_archivo = w.id_archivo
WHERE w.fecha_open IS NOT NULL AND w.fecha_open < w.fecha_envio AND w.rn = 1;

INSERT INTO errores (id_ejecucion, id_archivo, nombre_archivo, num_linea, codigo_error, severidad, campo, valor_original, descripcion, registro_completo)
SELECT @id_ejecucion, w.id_archivo, a.nombre_archivo, w.num_linea, 'V-10', 'ADVERTENCIA', 'Opens / Clicks', LEFT(CONCAT('opens=',w.opens,' clicks=',w.clicks),500), 'Clicks registrados sin fecha de apertura', w.registro_completo
FROM wrk_visitas w JOIN etl_archivo a ON a.id_archivo = w.id_archivo
WHERE w.clicks > 0 AND w.fecha_open IS NULL AND w.rn = 1;

-- V-05: fecha secundaria con contenido pero fuera del formato dd/mm/yyyy HH:mm.
-- Se compara el texto original contra la conversión: si había valor y la
-- conversión devolvió NULL, el formato no cumple.
INSERT INTO errores (id_ejecucion, id_archivo, nombre_archivo, num_linea, codigo_error, severidad, campo, valor_original, descripcion, registro_completo)
SELECT @id_ejecucion, w.id_archivo, a.nombre_archivo, w.num_linea, 'V-05', 'ADVERTENCIA', 'Fecha open', LEFT(w.fecha_open_txt,500), 'Fecha open fuera del formato dd/mm/yyyy HH:mm; se carga como NULL', w.registro_completo
FROM wrk_visitas w JOIN etl_archivo a ON a.id_archivo = w.id_archivo
WHERE w.fecha_open IS NULL AND w.fecha_open_txt NOT IN ('', '-') AND w.fecha_open_txt IS NOT NULL AND w.rn = 1;

INSERT INTO errores (id_ejecucion, id_archivo, nombre_archivo, num_linea, codigo_error, severidad, campo, valor_original, descripcion, registro_completo)
SELECT @id_ejecucion, w.id_archivo, a.nombre_archivo, w.num_linea, 'V-05', 'ADVERTENCIA', 'Fecha click', LEFT(w.fecha_click_txt,500), 'Fecha click fuera del formato dd/mm/yyyy HH:mm; se carga como NULL', w.registro_completo
FROM wrk_visitas w JOIN etl_archivo a ON a.id_archivo = w.id_archivo
WHERE w.fecha_click IS NULL AND w.fecha_click_txt NOT IN ('', '-') AND w.fecha_click_txt IS NOT NULL AND w.rn = 1;

-- V-06: campo numérico no convertible. La marca numericos_ok se calcula en la
-- capa de trabajo; aquí se materializa como incidencia auditable.
INSERT INTO errores (id_ejecucion, id_archivo, nombre_archivo, num_linea, codigo_error, severidad, campo, valor_original, descripcion, registro_completo)
SELECT @id_ejecucion, w.id_archivo, a.nombre_archivo, w.num_linea, 'V-06', 'ADVERTENCIA', 'Opens / Clicks', LEFT(w.registro_completo,500), 'Campo numérico no convertible; se carga con valor 0', w.registro_completo
FROM wrk_visitas w JOIN etl_archivo a ON a.id_archivo = w.id_archivo
WHERE w.numericos_ok = 0 AND w.rn = 1;

-- V-09: columna esperada que llegó vacía en el 100% de los registros del
-- archivo. Es una alerta de nivel archivo: puede significar que el origen
-- dejó de poblar un campo. COUNT(columna) cuenta solo los valores no nulos.
INSERT INTO errores (id_ejecucion, id_archivo, nombre_archivo, codigo_error, severidad, campo, descripcion)
SELECT @id_ejecucion, t.id_archivo, a.nombre_archivo, 'V-09', 'ADVERTENCIA', t.campo,
       CONCAT('La columna ', t.campo, ' llegó vacía en el 100% de los registros del archivo')
FROM (
      SELECT id_archivo, 'jyv'            AS campo FROM wrk_visitas GROUP BY id_archivo HAVING COUNT(jyv)            = 0
UNION SELECT id_archivo, 'badmail'              FROM wrk_visitas GROUP BY id_archivo HAVING COUNT(badmail)        = 0
UNION SELECT id_archivo, 'baja'                 FROM wrk_visitas GROUP BY id_archivo HAVING COUNT(baja)           = 0
UNION SELECT id_archivo, 'fecha_open'           FROM wrk_visitas GROUP BY id_archivo HAVING COUNT(fecha_open)     = 0
UNION SELECT id_archivo, 'fecha_click'          FROM wrk_visitas GROUP BY id_archivo HAVING COUNT(fecha_click)    = 0
UNION SELECT id_archivo, 'links'                FROM wrk_visitas GROUP BY id_archivo HAVING COUNT(links)          = 0
UNION SELECT id_archivo, 'ips'                  FROM wrk_visitas GROUP BY id_archivo HAVING COUNT(ips)            = 0
UNION SELECT id_archivo, 'navegadores'          FROM wrk_visitas GROUP BY id_archivo HAVING COUNT(navegadores)    = 0
UNION SELECT id_archivo, 'plataformas'          FROM wrk_visitas GROUP BY id_archivo HAVING COUNT(plataformas)    = 0
) t JOIN etl_archivo a ON a.id_archivo = t.id_archivo;

INSERT INTO estadistica
    (email, jyv, badmail, baja, fecha_envio, fecha_open, opens, opens_virales,
     fecha_click, clicks, clicks_virales, links, ips, navegadores, plataformas, id_archivo)
SELECT w.email, w.jyv, w.badmail, w.baja, w.fecha_envio, w.fecha_open, w.opens,
       w.opens_virales, w.fecha_click, w.clicks, w.clicks_virales, w.links,
       w.ips, w.navegadores, w.plataformas, w.id_archivo
FROM wrk_visitas w
WHERE w.rn = 1
ON DUPLICATE KEY UPDATE
    fecha_open     = VALUES(fecha_open),
    opens          = GREATEST(estadistica.opens, VALUES(opens)),
    opens_virales  = GREATEST(estadistica.opens_virales, VALUES(opens_virales)),
    fecha_click    = VALUES(fecha_click),
    clicks         = GREATEST(estadistica.clicks, VALUES(clicks)),
    clicks_virales = GREATEST(estadistica.clicks_virales, VALUES(clicks_virales)),
    links = VALUES(links), ips = VALUES(ips),
    navegadores = VALUES(navegadores), plataformas = VALUES(plataformas),
    fecha_carga = NOW();

-- Una visita es un clic en el enlace del correo. Es el unico evento que
-- produce una visita real al sitio: una apertura solo dispara el pixel de
-- seguimiento en el servidor de correo y nunca toca el sitio web.
-- Por eso fecha_visita toma fecha_click, no fecha_envio, y solo entran los
-- registros con clic. Los envios sin clic quedan completos en estadistica.
--
-- No se filtra por rn = 1 a proposito. Ese ranking deduplica el grano del
-- ENVIO (email + fecha_envio), que es el de estadistica. El grano de visita
-- es otro: email + fecha_click. Un mismo envio puede llegar en dos archivos
-- distintos (dos segmentos de la misma campana) con clics en instantes
-- distintos, y son dos visitas reales al sitio.
--
-- La llave primaria (email, fecha_visita) hace la deduplicacion correcta en
-- ambos escenarios: si las fechas de clic difieren son dos visitas; si
-- coinciden, el origen mando el mismo evento dos veces y se colapsa en una.
-- Se exige rn IS NOT NULL para admitir solo registros que pasaron V-03 y
-- V-04: sin email valido no hay a quien atribuir la visita.
INSERT INTO visita (email, fecha_visita, clicks, id_archivo)
SELECT w.email, w.fecha_click, w.clicks, w.id_archivo
FROM wrk_visitas w
WHERE w.rn IS NOT NULL AND w.clicks > 0 AND w.fecha_click IS NOT NULL
ON DUPLICATE KEY UPDATE
    clicks     = GREATEST(visita.clicks, VALUES(clicks)),
    id_archivo = VALUES(id_archivo);

INSERT INTO visitante
    (email, fechaPrimeraVisita, fechaUltimaVisita, visitasTotales,
     visitasAnioActual, visitasMesActual, fecha_actualizacion)
-- visitasTotales suma los clics, no cuenta las filas: si alguien hizo tres
-- clics en un correo, visito el sitio tres veces.
SELECT
    v.email,
    DATE(MIN(v.fecha_visita)),
    DATE(MAX(v.fecha_visita)),
    SUM(v.clicks),
    SUM(IF(YEAR(v.fecha_visita) = YEAR(CURDATE()), v.clicks, 0)),
    SUM(IF(YEAR(v.fecha_visita) = YEAR(CURDATE())
           AND MONTH(v.fecha_visita) = MONTH(CURDATE()), v.clicks, 0)),
    NOW()
FROM visita v
GROUP BY v.email
ON DUPLICATE KEY UPDATE
    fechaPrimeraVisita = VALUES(fechaPrimeraVisita),
    fechaUltimaVisita  = VALUES(fechaUltimaVisita),
    visitasTotales     = VALUES(visitasTotales),
    visitasAnioActual  = VALUES(visitasAnioActual),
    visitasMesActual   = VALUES(visitasMesActual),
    fecha_actualizacion = NOW();

COMMIT;
