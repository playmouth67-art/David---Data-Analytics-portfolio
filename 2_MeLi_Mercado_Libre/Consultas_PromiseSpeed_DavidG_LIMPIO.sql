-- ============================================================================
-- PROYECTO: Caso de Negocio Promise & Speed
-- AUTOR: David Adrián González Molina
-- PLATAFORMA: Google BigQuery (SQL Estándar) — data warehouse en la nube de GCP
-- OBJETIVO: Extracción de métricas de conversión (CVR) y SLA logístico (Ruta ZAC-OAX)
--
-- Las consultas fueron escritas y ejecutadas en la consola de Google BigQuery,
-- sobre la tabla cargada como fuente única de verdad (Single Source of Truth):
--   gen-lang-client-0812859211.CasoNegocioPromiseSpeed.tabla_Caso_NegocioPromiseSpeed
-- ============================================================================


-- ----------------------------------------------------------------------------
-- ANÁLISIS 1: Tasa de Conversión (CVR) por Hora de Compra
-- Descripción: Identifica la eficiencia del Marketplace por hora del día.
-- Justificación de Negocio: Saber en qué horas el tráfico se convierte en ventas
-- reales permite definir el corte de ruta logístico.
-- ----------------------------------------------------------------------------

SELECT
    -- Dimensión principal de análisis
    HORA_COMPRA,

    -- Volumen total de envíos generados en esa hora
    SUM(TOTAL_ENVIOS) AS envios_totales,

    -- Tráfico total (visitas) en esa misma hora
    SUM(VISITAS) AS visitas_totales,

    -- KPI principal (CVR). Usamos SAFE_DIVIDE en lugar del operador "/":
    -- si una hora tuviera 0 visitas, devuelve NULL en vez de un error de
    -- "división por cero" que detendría el pipeline. Esto también cubre la
    -- advertencia del caso sobre posibles valores en 0 y/o nulos.
    SAFE_DIVIDE(SUM(TOTAL_ENVIOS), SUM(VISITAS)) AS CVR

FROM
    `gen-lang-client-0812859211.CasoNegocioPromiseSpeed.tabla_Caso_NegocioPromiseSpeed`

GROUP BY
    -- Empaqueta los registros por cada hora del día (0 a 23) para que SUM() agregue
    HORA_COMPRA

ORDER BY
    -- La hora más eficiente queda en la primera fila, lista para decisión
    CVR DESC;


-- ----------------------------------------------------------------------------
-- ANÁLISIS 2: % de entregas a tiempo (SLA logístico) por mes en 2024
-- Descripción: Mide la proporción de éxito mensual de la ruta ofensora.
-- Justificación de Negocio: Visualiza la estacionalidad del cumplimiento para saber
-- si la red soporta una promesa de entrega más agresiva (Next-Day).
-- ----------------------------------------------------------------------------

SELECT
    -- Dimensión temporal para ver la tendencia estacional
    MES,

    -- Paquetes que cumplieron la promesa de entrega
    SUM(ENTREGA_A_TIEMPO) AS total_on_time,

    -- Universo total de paquetes que viajaron en el mes
    SUM(TOTAL_ENVIOS) AS envios_totales,

    -- Service Level Agreement (SLA) en formato porcentual, listo para graficar.
    -- SAFE_DIVIDE protege contra meses sin envíos (0/nulo).
    SAFE_DIVIDE(SUM(ENTREGA_A_TIEMPO), SUM(TOTAL_ENVIOS)) * 100 AS porcentaje_on_time

FROM
    `gen-lang-client-0812859211.CasoNegocioPromiseSpeed.tabla_Caso_NegocioPromiseSpeed`

WHERE
    -- Gobernanza de datos y optimización de costos: filtramos en el servidor ANTES
    -- de procesar. Aísla la muestra al año (2024) y a la ruta ofensora (ZAC-OAX).
    -- En BigQuery, filtrar temprano reduce los bytes leídos y el costo de la consulta.
    ANIO = 2024
    AND ORIGEN = 'ZACATECAS'
    AND DESTINO = 'OAXACA'

GROUP BY
    -- Agrupamos por mes (1 = Enero, ... 12 = Diciembre)
    MES

ORDER BY
    -- Orden cronológico ascendente, de enero a diciembre
    MES ASC;

-- ============================================================================
-- FIN DEL SCRIPT
-- ============================================================================
