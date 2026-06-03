# Caso de Estudio — S&OP UTR · Site MXXPB1 (Semana 27)

**Autor:** David Adrián González Molina
**Tipo:** Caso práctico de Sales & Operations Planning (planeación de fuerza laboral)
**Stack:** Modelado en Excel · SQL en Google BigQuery · Storytelling ejecutivo

> **Aviso:** Proyecto de portafolio con fines demostrativos. Los datos son
> **sintéticos / ficticios** y no corresponden a información operativa real de
> ninguna empresa.

---

## Contexto y objetivo

Ejercicio de S&OP para el site **MXXPB1** en la Semana 27, orientado a dimensionar
la operación con el menor costo manteniendo cobertura completa. Cubre tres frentes
de decisión —planeación de headcount, optimización de jornadas y estrategia a 12
semanas— más un ejercicio de SQL en BigQuery, con hallazgos presentables a un
ejecutivo en pocos minutos.

## Hallazgos principales

- **Headcount:** el peak de la semana es **37 personas**, que se repite Martes,
  Jueves y Viernes. El dato contraintuitivo: el Lunes, con el mayor volumen semanal
  (18,400 paquetes), solo necesita 33 — el headcount lo define la concentración del
  volumen en la **hora pico**, no el total del día.
- **Jornadas:** el mix óptimo es **22 FT 6x1 + 11 FT 5x2 + 15 Diaristas**, con un
  costo de **$143,600 semanales** y cobertura 100% los seis días activos. La palanca
  clave es asignar el día libre de todos los FT al **Domingo**, el único día sin
  operación.
- **Estrategia (12 semanas):** FT base dimensionado al **P60 del forecast**,
  Diaristas como capa flex para los picos y revisión del plan FT solo cada cuatro
  semanas. KPI de seguimiento: **SER** (Staffing Efficiency Rate), zona óptima 95–105%.
- **SQL / BigQuery:** consulta con CTE + JOIN, GROUP BY y HAVING para identificar
  países con ventas > $500 en 2024 → México $700, Colombia $600, España $550.

## Contenido del proyecto

| Archivo | Qué demuestra |
|---|---|
| `MeLi_SOP_UTR_Workample.pptx` | Presentación completa del caso (HC, jornadas, estrategia, SQL). |
| `MeLi_SOP_Resumen_Ejecutivo.pptx` | Versión resumida ejecutiva. |
| `MXXPB1_SOP_UTR_Semana27.xlsx` | Modelo de datos y cálculos de staffing. |
| `MeLi_Video_Script.md` | Guión de video completo del caso. |
| `MeLi_Video_Script_Ejecutivo.md` | Guión del video resumen ejecutivo (90–120 s). |

## Habilidades demostradas

- **Planeación de capacidad / workforce planning:** dimensionamiento por hora pico,
  diseño de mix de jornadas y optimización de costo con restricciones de cobertura.
- **Pensamiento de S&OP:** forecast por percentiles (P60), capa flex y cadencia de
  revisión del plan.
- **SQL analítico en la nube:** agregación con CTE, JOIN y HAVING en BigQuery.
- **Comunicación ejecutiva:** traducción del análisis en una recomendación accionable
  y guiones de video para presentación.
