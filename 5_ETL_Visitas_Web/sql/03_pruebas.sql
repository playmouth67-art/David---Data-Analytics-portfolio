USE etl_visitas;

SELECT 'P-01 Cuadre general' AS prueba,
       IF((SELECT COUNT(*) FROM stg_visitas) = 
          (SELECT COUNT(*) FROM wrk_visitas WHERE rn = 1) + 
          (SELECT COUNT(*) FROM errores WHERE severidad='RECHAZO') + 
          (SELECT COUNT(*) FROM wrk_visitas WHERE rn > 1), 'PASA', 'FALLA') AS resultado;

SELECT 'P-02 Emails limpios en visitante' AS prueba,
       IF((SELECT COUNT(*) FROM visitante v WHERE v.email NOT REGEXP '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}$') = 0, 'PASA', 'FALLA') AS resultado;

SELECT 'P-03 Toda visita tiene su registro en estadistica' AS prueba,
       IF((SELECT COUNT(*) FROM visita v LEFT JOIN estadistica e ON e.email = v.email
           WHERE e.email IS NULL) = 0, 'PASA', 'FALLA') AS resultado;

SELECT 'P-03b Toda visita tiene fecha de clic propia' AS prueba,
       IF((SELECT COUNT(*) FROM visita WHERE fecha_visita IS NULL) = 0, 'PASA', 'FALLA') AS resultado;

SELECT 'P-03c Sin visitas duplicadas en su propio grano' AS prueba,
       IF((SELECT COUNT(*) FROM (SELECT email, fecha_visita FROM visita
                                 GROUP BY email, fecha_visita HAVING COUNT(*) > 1) x) = 0,
          'PASA', 'FALLA') AS resultado;

SELECT 'P-04 visitasTotales = suma de clics del visitante' AS prueba,
       IF((SELECT COUNT(*) FROM visitante vt
           JOIN (SELECT email, SUM(clicks) AS cnt FROM visita GROUP BY email) c
             ON vt.email = c.email
           WHERE vt.visitasTotales <> c.cnt) = 0, 'PASA', 'FALLA') AS resultado;

SELECT 'P-05 Fechas primera <= última' AS prueba,
       IF((SELECT COUNT(*) FROM visitante WHERE fechaPrimeraVisita > fechaUltimaVisita) = 0, 'PASA', 'FALLA') AS resultado;

SELECT 'P-06 Jerarquía de contadores' AS prueba,
       IF((SELECT COUNT(*) FROM visitante WHERE visitasMesActual > visitasAnioActual OR visitasAnioActual > visitasTotales) = 0, 'PASA', 'FALLA') AS resultado;

SELECT 'P-07 Unicidad de email en visitante' AS prueba,
       IF((SELECT COUNT(*) FROM (SELECT email, COUNT(*) c FROM visitante GROUP BY email HAVING c > 1) x) = 0, 'PASA', 'FALLA') AS resultado;

SELECT 'P-08 Unicidad de hash' AS prueba,
       IF((SELECT COUNT(*) FROM (SELECT hash_archivo, COUNT(*) c FROM etl_archivo GROUP BY hash_archivo HAVING c > 1) x) = 0, 'PASA', 'FALLA') AS resultado;

SELECT 'P-09 Visita apunta a archivo existente' AS prueba,
       IF((SELECT COUNT(*) FROM visita v LEFT JOIN etl_archivo a ON v.id_archivo = a.id_archivo WHERE a.id_archivo IS NULL) = 0, 'PASA', 'FALLA') AS resultado;
