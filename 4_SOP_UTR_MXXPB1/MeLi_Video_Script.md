# Guión — Video Presentación Caso Práctico S&OP UTR
**MercadoLibre · Analista Sr S&OP · Semana 27 · Site MXXPB1**
*Tiempo estimado: 5–7 minutos*

---

## Antes de grabar

- Abre el PPTX y usa el modo presentación (pantalla completa).
- Habla directo a cámara en los momentos de transición; mira los slides cuando expliques datos.
- Tono: seguro, conversacional. No tienes que leer palabra por palabra — usa esto como guía.

---

## SLIDE 1 — COVER

> *[Aparece en pantalla: portada oscura con título "Workample S&OP UTR"]*

"Hola, soy David Adrián González Molina. Les presento mi solución al caso práctico de S&OP para el site MXXPB1 de MercadoLibre Envíos, correspondiente a la Semana 27.

El caso cubre tres ejercicios: cálculo de headcount hora por hora, optimización de jornadas, y una estrategia de planeación a 12 semanas — además de un ejercicio de SQL. Voy a recorrer cada uno explicando tanto la metodología como los resultados."

---

## SLIDE 2 — AGENDA

> *[Aparece en pantalla: cuatro tarjetas de agenda]*

"La agenda tiene cuatro bloques. Los primeros tres corresponden al ejercicio de S&OP: primero calculamos el HC necesario por posición y por hora, después encontramos la mezcla óptima de jornadas, y por último diseñamos la estrategia de staffing para las próximas 12 semanas. El cuarto bloque es el ejercicio de SQL, donde identificamos países con ventas mayores a 500 dólares en 2024."

---

## SLIDE 3 — 1.1 METODOLOGÍA HC HORA × HORA

> *[Aparece en pantalla: fórmula en fondo oscuro + tres tarjetas de conceptos]*

"Para calcular el headcount arranqué con la fórmula base del S&OP de operaciones:

**HC necesario es igual al techo de: volumen diario, multiplicado por la curva de procesamiento, multiplicado por el split del proceso, dividido entre la productividad.**

Cada componente viene directo del archivo de datos:

- El **volumen diario** es el forecast de la Semana 27, dividido en paquetes V2 — que son los conveyables — y paquetes NC, que son los de gran volumen.
- La **curva de procesamiento** nos dice qué porcentaje del volumen diario llega a cada proceso en cada hora. No todo llega parejo — hay una hora pico que concentra el mayor flujo.
- La **productividad** es cuántos paquetes por hora procesa una persona en cada posición.

Un punto que vale la pena destacar: el sorter del site siempre opera con un split 85/15 — el 85% del flujo va al carril conveyable y el 15% al carril manual. Ese 15% es un parámetro empírico del sitio, no una configuración fija. Significa que aunque el día tenga volumen NC igual a cero, el carril manual siempre tiene flujo, y Water Spider NC nunca baja de 9 personas mientras haya operación activa."

---

## SLIDE 4 — 1.1 RESULTADOS PEAK HC

> *[Aparece en pantalla: tarjetas de HC por día + gráfica de barras]*

"Corriendo el modelo hora por hora para las ocho posiciones del site — Descarga V2, Descarga NC, Sorter Conveyable, Sorter NC, Inducción, Water Spider V2, Water Spider NC y Embarque — obtuve el peak de headcount diario.

Los resultados más relevantes son estos:

El **Lunes** necesita 33 personas en su hora pico, a las 3 de la tarde. El **Martes, Jueves y Viernes** requieren 37 cada uno, que es el máximo de la semana. El **Miércoles** 36, y el **Sábado** baja a 22 porque el volumen cae considerablemente.

Hay un insight importante aquí que la gráfica hace evidente: **el Lunes tiene el mayor volumen de la semana — 18,400 paquetes — pero no es el día de mayor HC**. El Martes tiene solo 13,987 paquetes y aun así necesita 37 personas. La razón es que lo que determina el headcount no es el volumen total del día, sino **cómo se concentra ese volumen en la hora pico**. Si el 20% del volumen llega en una sola hora, necesitas más gente que si ese mismo volumen llega distribuido. Ese es el principio central del modelo."

---

## SLIDE 5 — 1.2 OPTIMIZACIÓN DE JORNADAS

> *[Aparece en pantalla: tarjetas con mix + tabla de cobertura]*

"Para la optimización de jornadas, el objetivo era cubrir la demanda de los seis días activos al menor costo posible, combinando tres tipos de jornada:

- **FT 6x1**: trabaja seis días, descansa uno.
- **FT 5x2**: trabaja cinco días, descansa dos.
- **Diaristas**: solo se contratan el día que se necesitan.

Lo primero que resolví fue eliminar la jornada FT 4x3 — trabaja cuatro días, descansa tres — porque es la más costosa por cobertura entregada.

La clave de la solución óptima está en el día libre. Si asignamos el día libre de **todos los FT al Domingo**, que es el único día con volumen cero, convertimos la disponibilidad teórica en cobertura real del 100% durante los seis días activos. No hay costo adicional — simplemente hacemos que el día libre no cueste operación.

Con esa lógica, el mix óptimo es: **22 FT 6x1 + 11 FT 5x2 + 15 Diaristas**, con un costo semanal de $143,600. La tabla confirma cobertura exacta todos los días — los Diaristas solo se activan Martes, Miércoles, Jueves y Viernes, donde la demanda supera la base de 33 HC que dan los FT."

---

## SLIDE 6 — 1.3 ESTRATEGIA 12 SEMANAS

> *[Aparece en pantalla: tres pasos del modelo + panel KPI derecho]*

"Para la estrategia de 12 semanas, el principio es separar la planta fija de la capa variable. El modelo tiene tres pasos:

**Primero**, dimensionar el FT base al **percentil P60 del forecast**. No al máximo — eso genera desperdicio en semanas de baja demanda. No al promedio — eso deja descubierto el 50% de los escenarios. El P60 cubre la mayoría de situaciones sin necesitar Diaristas.

**Segundo**, usar Diaristas como **capa flex** para todo lo que esté por encima del FT base. Máximo un 20% del headcount total. Se activan o desactivan semana a semana sin impacto en la plantilla fija ni en el engagement del equipo.

**Tercero**, revisar el plan FT **solo cada cuatro semanas**, y únicamente si el forecast se desvía más del 15% por dos semanas consecutivas. Ajustar el FT cada semana genera rotación, costo de onboarding y baja en productividad — cosas que cuestan más que el ahorro teórico.

Para medir qué tan bien está funcionando el plan, propongo el KPI **Staffing Efficiency Rate**:

SER = HC Real dividido entre HC Planeado por 100%.

La zona óptima es entre 95 y 105%. Por debajo del 90% hay riesgo de backlog; por encima del 115% estamos sobredimensionados. Se mide diariamente por turno y se reporta semanalmente al Director de Site."

---

## SLIDE 7 — SQL

> *[Aparece en pantalla: bloque de código + tabla de resultados]*

"El ejercicio de SQL pedía identificar los países con ventas totales mayores a $500 dólares en el año 2024, usando las tablas de clientes y pedidos.

La solución que construí usa una **CTE** — Common Table Expression — para tener todas las tablas definidas en una sola consulta autocontenida, sin depender de que existan tablas permanentes en el esquema.

La lógica es:
- **JOIN** para unir pedidos con clientes y traer el país de cada transacción.
- **WHERE** filtra las filas individuales — solo pedidos del año 2024.
- **GROUP BY** agrupa por país para sumar las ventas.
- **HAVING** filtra los grupos cuya suma supera los $500. A diferencia de WHERE, HAVING opera sobre el resultado ya agregado.

Corrí la query en BigQuery en tiempo real. El resultado fue tres países calificados: **México con $700, Colombia con $600, y España con $550**."

---

## SLIDE 8 — INSIGHTS CLAVE

> *[Aparece en pantalla: cuatro tarjetas de insights]*

"Más allá de los números, hay cuatro aprendizajes que quiero destacar del ejercicio.

**Primero**: la concentración del volumen importa más que el volumen total. El Lunes tiene más paquetes que el Martes pero necesita menos gente. El modelo de HC debe mirar la curva, no solo el total.

**Segundo**: el sorter siempre opera ambos carriles. Ese 15% del split no es programable — viene del comportamiento físico de la banda. Ignorarlo subestimaría el HC de Water Spider NC y dejaría posiciones sin cubrir.

**Tercero**: el día libre al Domingo no es una restricción — es una ventaja. Convertir el único día sin operación en el día de descanso unificado elimina huecos de cobertura sin costo adicional.

**Cuarto**: la estabilidad de la plantilla tiene valor económico. Ajustar el FT semana a semana puede parecer eficiente en papel, pero el costo de rotación, onboarding y pérdida de productividad supera el ahorro. El modelo Base + Flex absorbe la volatilidad sin tocar el FT."

---

## SLIDE 9 — CIERRE

> *[Aparece en pantalla: slide de cierre oscuro]*

"Para cerrar, las herramientas que utilicé fueron Python para el modelo de HC y la optimización de jornadas, BigQuery para el ejercicio de SQL, y el Excel que adjunto con todos los cálculos detallados.

Adjunto también el script de Python y el archivo SQL por separado para revisión.

Muchas gracias por la oportunidad. Quedo disponible para cualquier pregunta o para profundizar en cualquier parte del modelo."

---

## Checklist antes de enviar

- [ ] **PPTX**: `MeLi_SOP_UTR_Workample.pptx`
- [ ] **Excel** con cálculos: `MXXPB1_SOP_UTR_Semana27.xlsx`
- [ ] **Python** script: `saop_solution.py`
- [ ] **Video** grabado (5–7 min, usando este guión)
- [ ] Responder al correo incluyendo a todas las personas en copia

---

## Tips para la grabación

- **Duración objetivo**: 5–7 minutos. No más. Mantén el ritmo.
- **Slides 3 y 4** son los más técnicos — tómate el tiempo de explicar la fórmula con calma.
- **Slide 6** es el que más te diferencia — el modelo P60 + Flex demuestra criterio de negocio, no solo cálculo.
- Si te equivocas, pausa 2 segundos y vuelve a empezar esa sección. En edición es fácil cortar.
- No leas el guión — úsalo para recordar los puntos clave y habla con tus propias palabras.
