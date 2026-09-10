# Portafolio de Datos — David Adrián González Molina

**Data Analyst / Data Engineer**
Python · SQL · Google BigQuery · Power BI · Tableau · Looker Studio · MCP · Claude API

Siete casos completos: cuatro análisis de negocio que van del dato crudo al dashboard, un proceso ETL que corre de verdad, un agente que lo opera, y un agente que decide por su cuenta cómo segmentar una cartera. Cada uno arranca con una pregunta que alguien haría en una junta y termina en un entregable que la responde con números.

> **Aviso:** todos los datos son sintéticos, generados para este portafolio. No corresponden a información real de ninguna empresa; las marcas aparecen solo como contexto de negocio simulado.

---

## Proyectos

| # | Proyecto | De qué trata | Stack |
|---|----------|--------------|-------|
| 1 | [Plataforma BI L'Oréal LATAM](./1_LOreal_BI_LATAM) | Ventas, market share y ROI de 5 países en una sola plataforma. Modelo estrella, arquitectura medallion y RLS para que cada país vea solo lo suyo. | Power BI · BigQuery · DAX · SQL |
| 2 | [Promise & Speed (Mercado Libre)](./2_MeLi_Mercado_Libre) | ¿Por qué cayó la conversión de una ruta? El análisis rastrea el problema hasta la promesa de entrega y propone cómo recalibrarla. | Python (pandas) · SQL · Tableau |
| 3 | [Jellyfish — Investment Analytics](./3_Jellyfish_Investment_Analytics) | El gasto de marketing subió 19.7% y el alcance quedó plano. Un dashboard de una página se lo explica a un CMO sin que tenga que preguntar. | BigQuery · Looker Studio · SQL |
| 4 | [S&OP UTR — Site MXXPB1](./4_SOP_UTR_MXXPB1) | ¿Cuánta gente necesita un sitio en hora pico y con qué mix de jornadas? Dimensionamiento de headcount a 12 semanas. | Excel · SQL · S&OP |
| 5 | [ETL de integración de visitas web](./5_ETL_Visitas_Web) | Un proceso diario que trae archivos de un servidor, los valida, los consolida en MySQL y los borra del origen. No es un análisis: es un sistema que corre, con puntos de control que atrapan lo que las validaciones no ven. | Python · MySQL · Docker · SQL |
| 6 | [Agente de operación del ETL](./6_Agente_MCP_ETL) | Un servidor MCP de 14 herramientas que deja operar y auditar el caso 5 desde un agente. Probarlo destapó cuatro defectos del ETL que los archivos de ejemplo no revelaban. | Python · MCP · MySQL · Pydantic |
| 7 | [Agente de segmentación de clientes](./7_Customer_Segmentation_Agent) | Un agente que segmenta solo: elige la unidad de análisis, las variables y el número de grupos. Lo difícil no fue que encontrara segmentos, fue enseñarle a decir cuándo no los hay: sobre ruido puro el silhouette da 0.32 y engaña a cualquier umbral fijo. | Python · Claude API · scikit-learn · pytest |

Cada carpeta trae su README con el contexto, la metodología y los hallazgos.

---

## Cómo navegar

Empieza por el README de cada proyecto: ahí está el resumen ejecutivo. El código (SQL, notebooks) y los datos sintéticos van en la misma carpeta, así que todo se puede reproducir. Los archivos de Power BI (.pbix) y Tableau (.twbx) están incluidos; donde hay versión interactiva publicada, el README del proyecto tiene el enlace.

Los casos 5 y 6 se leen juntos: primero el sistema, después el agente que lo opera y lo audita.

Los casos 6 y 7 son las dos mitades de trabajar con agentes. El 6 le da herramientas a un agente para que opere un sistema que ya existe. El 7 construye el agente desde cero — el bucle, los barandales y los evals — y se pelea con el problema de que un agente, si lo dejas, siempre encuentra lo que le pediste que buscara.

## Competencias

Modelado dimensional, SQL analítico en BigQuery, ETL/ELT con arquitectura medallion, Power BI con DAX y RLS, visualización en Tableau y Looker Studio, Python para análisis de datos. Del lado de ingeniería: orquestación de procesos batch, idempotencia, reconciliación y control de calidad del dato. Del lado de IA: servidores MCP, diseño de herramientas para agentes, bucles agénticos escritos a mano, barandales que rechazan una llamada mal formada y obligan al modelo a corregirse, evaluación contra ground truth en vez de contra la impresión de que el resultado se ve bien, y el criterio de dónde un modelo aporta y dónde hay que dejar el cálculo en SQL.

En clustering, la parte que más se salta: el silhouette dice cuántos grupos hay, no si los hay. Para lo segundo hace falta comparar contra un modelo nulo, y buena parte de los datos comerciales reales resultan ser un continuo y no grupos.

---

## Contacto

David Adrián González Molina
📧 davedrian@icloud.com · 💼 [LinkedIn](https://www.linkedin.com/in/david-adri%C3%A1n-gonz%C3%A1lez/) · 🐙 [GitHub](https://github.com/playmouth67-art)
