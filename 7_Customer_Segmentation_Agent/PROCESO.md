# Cómo se construye un agente, en ocho etapas

Este documento es el entregable real del proyecto. El código es la evidencia.

La idea que ordena todo lo demás: **un agente es un modelo dentro de un bucle.**
Recibe un objetivo, decide, ejecuta con una herramienta, **observa el resultado**,
y con eso decide el siguiente paso. La palabra que carga el peso es *observa*.
Un chatbot genera texto sobre datos que ya tenía. Un agente cambia el estado del
mundo y reacciona a lo que pasó.

Todo lo demás —frameworks, orquestadores, grafos— es azúcar encima de eso.

---

## Etapa 0 — Antes de escribir código: ¿esto necesita un agente?

La pregunta que casi nadie hace, y la que más dinero ahorra.

Un agente vale la pena cuando **el camino no se conoce de antemano**. Si sabes
exactamente qué pasos hay que dar y en qué orden, escribe un script: será más
rápido, más barato, y no fallará de formas raras.

Segmentar sí califica, y por una razón concreta: la unidad de análisis, las
variables y la k dependen de lo que resulte estar en los datos. Un script tendría
que hardcodear esas tres decisiones y se rompería con el siguiente dataset.

> **El costo que se paga:** los errores de un agente se **componen**. Diez pasos
> al 95% de acierto dan 60% de tarea completa. Un script determinista no tiene
> ese problema. Estás cambiando fiabilidad por adaptabilidad. Que sea a
> conciencia.

---

## Etapa 1 — La capa de dominio, sin nada de IA

**Archivo: `agent/analytics.py`**

Primero se escribe la parte que no habla con el modelo. Toda la estadística vive
aquí, en funciones normales de pandas y sklearn.

Esto no es orden por gusto. Es la regla que decide si el proyecto sirve:

- **El agente no sabe estadística. La ejecuta.** No le estás pidiendo a un modelo
  de lenguaje que calcule un silhouette de cabeza; le estás pidiendo que decida
  *cuándo* calcularlo y *qué hacer* con el número.
- Se prueba con pytest sin gastar un token.
- Si el archivo está mal, ningún prompt lo salva. Si Claude desaparece mañana,
  el archivo sigue funcionando.

Aquí también vive la decisión de arquitectura menos obvia del proyecto: el
`Workspace`. Las herramientas devuelven **resúmenes** y guardan los objetos
grandes en memoria, referenciados por nombre. El modelo mueve nombres, no datos.
Sin esto, 32,000 filas tendrían que pasar por el contexto y el proyecto sería
imposible.

---

## Etapa 2 — Diseñar las herramientas

**Archivo: `agent/tools.py`**

Aquí es donde se gana o se pierde. Tres reglas:

**Una herramienta hace una cosa.** La tentación es escribir `analizar_todo()`.
Si haces eso, las decisiones quedan escondidas adentro, el agente no decide nada,
y tú no puedes auditar por qué salió ese resultado. Herramientas chicas, agente
que orquesta.

**La descripción *es* el prompt.** El modelo nunca ve tu código. Ve el `name`,
el `description` y el `input_schema`. Cada palabra de criterio que quites de ahí
es criterio que le quitas al agente. Compara:

```
malo:  "Estandariza las variables."
bueno: "Estandariza las variables. OBLIGATORIO antes de clusterizar: k-means
        mide distancia euclidiana, así que sin esto la variable de rango más
        grande decide los clusters sola. Elige variables que midan cosas
        distintas: meter ingreso y número de transacciones a la vez cuenta la
        escala dos veces."
```

La segunda no es más verbosa. Es más *útil*, y se nota en los evals.

**El resultado es contexto.** Todo lo que devuelve una herramienta se paga en
tokens y compite por la atención del modelo. Por eso `inspect_table` devuelve
rangos y medias, nunca filas crudas. Un agente que pide "muéstrame las filas"
termina con 40k tokens de CSV en contexto y peor criterio del que tenía.

**El truco que hace todo lo demás posible:** `submit_findings` es una herramienta
*terminal* con schema estructurado. El agente no termina escribiendo un párrafo
bonito; termina llenando campos. Esa es la razón técnica por la que este agente
se puede evaluar y un chatbot no.

---

## Etapa 3 — Guardrails

**Archivo: `agent/guardrails.py`**

Un agente sin barandales no es peligroso porque se rebele. Es peligroso porque
es **complaciente**. Le pides tres segmentos y te da tres segmentos, haya
estructura o no. Los guardrails son el "no" que el modelo no se dice solo.

La decisión de diseño que importa: **un guardrail no lanza una excepción que
mata el programa. Devuelve el error AL MODELO como `tool_result`, y el modelo
tiene que corregirse en la siguiente vuelta.**

Ese ciclo —bloqueo, lectura del motivo, corrección— es la demostración más útil
de todo el proyecto. Córrelo y míralo:

```
-> sweep_k {"table": "entities"}
   BLOQUEADO [R4] 'entities' no está estandarizada. K-means usa distancia
   euclidiana: sin estandarizar, la variable de rango más grande decide los
   clusters ella sola.
-> standardize_features {"table": "entities", "features": [...]}
   ok
```

Las ocho reglas y qué modo de fallo ataca cada una:

| Regla | Bloquea | Por qué |
|---|---|---|
| R0 | Usar columnas `_privadas` como variable | Si el modelo toca el ground truth, el eval deja de medir |
| R1 | Tabla inexistente | Alucinación de nombres |
| R2 | Clusterizar con menos de 20 entidades | Con esa muestra el resultado cambia con la semilla |
| R3 | Segmentar con una sola variable | Eso no es segmentación, es cortar un histograma |
| R4 | **Clusterizar sin estandarizar** | El error metodológico clásico |
| R5 | Elegir k sin haber barrido | Elegir k sin ver el silhouette es adivinar |
| R6 | Perfilar sin modelo | Orden de operaciones |
| R7 | Concluir sin perfilar | Afirmar hallazgos sin haberlos mirado |

---

## Etapa 4 — El prompt del sistema

**Archivo: `agent/prompts.py`**

Un prompt de agente no describe un tono. Describe **un trabajo, un criterio de
calidad, y una condición de paro.**

Tres cosas lo hacen funcionar, en orden de impacto:

1. **Permiso explícito de no encontrar nada.** Sin la línea que dice *"si el
   silhouette máximo queda por debajo de 0.25, repórtalo con
   `structure_found=false`; es una respuesta correcta y valiosa"*, el modelo
   encuentra tres segmentos. Siempre. En datos aleatorios también.
2. **Un umbral numérico, no "usa tu criterio".** "Usa tu criterio" es cómo se
   pierden los evals.
3. **Cómo terminar.** Un agente sin condición de paro se cicla o se detiene por
   límite de vueltas, que es peor porque no entrega nada.

---

## Etapa 5 — El bucle

**Archivo: `agent/loop.py`** — el corazón, y son unas 90 líneas.

```
mientras el modelo pida herramientas:
    ejecútalas
    DEVUÉLVELE EL RESULTADO
    deja que decida el siguiente paso
```

Está escrito a mano y sin LangChain a propósito. **Si no puedes escribir este
bucle, no sabes qué está haciendo el framework por ti** — y cuando falle, que
va a fallar, no vas a saber dónde buscar.

Lo que se maneja adentro y suele olvidarse:

- **Los errores vuelven al modelo, no matan el proceso.** Una excepción de pandas
  se convierte en `tool_result` con `is_error=True`. El agente lee y reintenta.
- **Los `tool_result` gigantes se truncan.** Un resultado de 50k caracteres
  envenena el contexto y degrada todas las decisiones siguientes.
- **Límite de vueltas.** No opcional. Un bucle sin tope es una factura sin tope.
- **Varias `tool_use` en un turno** se ejecutan todas antes de responder.

**El modelo simulado (`--mock`)** merece su propio párrafo. Es un planificador
determinista que ocupa el lugar de Claude, y existe por dos razones: puedes correr
el bucle completo sin API key y sin gastar un peso, y los tests del bucle no
dependen de la red. *Un test que a veces falla porque el modelo cambió de opinión
no es un test.* El mock comete a propósito el error de la etapa 3, para que veas
el guardrail dispararse.

---

## Etapa 6 — Observabilidad

**Archivo: `agent/trace.py`**

Cada vuelta se escribe como una línea JSON: qué pensó, qué herramienta pidió, con
qué argumentos, si pasó el guardrail, qué devolvió, cuántos tokens costó.

No es lujo de producción. Es la única forma de contestar *"¿por qué el agente
eligió k=5 aquí?"*, que es la pregunta que siempre se hace y que sin trace se
contesta encogiéndose de hombros.

Fíjate en un detalle: las herramientas que toman decisiones piden un campo
`rationale` obligatorio. No es para el modelo. Es para el trace. Le estás
cobrando al agente que explique su decisión en el momento de tomarla, no después.

---

## Etapa 7 — Evals

**Archivos: `evals/cases.py`, `evals/run_evals.py`**

Aquí se separa un proyecto serio de un demo bonito. **Los proyectos que funcionan
gastan más en evals y observabilidad que en el prompt.**

"Se ve bien" no es una medida. Un eval es un caso con respuesta conocida y un
criterio de aprobado que se calcula sin opinar. Por eso el generador de datos
planta clusters a propósito: sabemos cuántos grupos hay porque nosotros los
pusimos.

Los siete casos atacan modos de fallo **distintos**, no la misma habilidad tres
veces:

| Caso | Qué mide |
|---|---|
| `k2` `k3` `k5` | Precisión básica, y sesgo hacia pocos segmentos |
| `sin_estructura` | **Complacencia.** El fallo más común de todos los agentes |
| `escala_traidora` | Rigor: los grupos solo aparecen si estandariza |
| `long_tail` | Criterio de negocio: leer desproporción tamaño/valor |
| `fact_sales_e2e` | Proceso completo sobre transacciones crudas |

Y la métrica que hace la diferencia: **ARI** (Adjusted Rand Index). Acertar el
*número* de grupos no prueba nada si las entidades quedaron en el grupo
equivocado. El ARI compara la asignación real contra la del agente y corrige por
azar: 0 es tirar una moneda, 1 es perfecto. Es lo que atrapa al agente que dice
"k=2" sobre `escala_traidora` sin haber estandarizado — la k está bien y el
resultado es basura.

---

## Etapa 7½ — Lo que pasó cuando se corrieron los evals por primera vez

Esta sección es el corazón del documento. Todo lo anterior es cómo se arma;
esto es lo que pasa cuando lo pruebas.

**Primera corrida: 33/40 checks, 3 de 7 casos perfectos.** Cuatro casos
fallaron. Al abrirlos, **solo uno** era culpa del agente:

### Falla 1 — `k5` eligió k=4. El eval estaba mal.

Los centros de los cinco grupos se habían colocado al azar, y dos cayeron a 1.0
desviaciones de distancia. Se traslapaban. **k=4 era la respuesta
estadísticamente correcta para esos datos** y el eval reprobaba al agente por
acertar.

> Regla que sale de aquí: **cuando un eval falla, el primer sospechoso es el
> eval.** Un caso cuyo ground truth no está realmente en los datos no mide al
> agente, mide tu descuido.

Arreglo: separación mínima garantizada entre centros plantados.

### Falla 2 — `escala_traidora` daba ARI de 0.33. El dataset estaba mal, dos veces.

- **v1** usaba ruido *uniforme* en dos dimensiones. Un rango uniforme
  estandarizado abarca 3.46 desviaciones y se parte con facilidad: el ruido se
  dejaba clusterizar mejor que la señal.
- **v2** puso la señal en *una sola* dimensión. Con dos dimensiones de ruido
  alrededor, k-means no recupera un corte unidimensional aunque esté ahí.
- **v3**, la que quedó: señal en dos dimensiones, ruido gaussiano de rango
  enorme en la tercera. Resultado: ARI 1.00 escalado, 0.02 sin escalar. La
  lección quedó demostrable.

### Falla 3 — `long_tail` reprobó por una negación. El calificador estaba mal.

El check buscaba palabras como "discontinuar" en las acciones recomendadas. Y
reprobó esta frase:

> "margen sano con poca escala **no es motivo de discontinuación**"

...que dice exactamente lo contrario de lo que el check quería castigar.

> **La negación es el falso positivo clásico de cualquier eval basado en texto.**
> Por eso los evals de string-matching son el último recurso, no el primero.
> Cuando no queda de otra, hay que partir en cláusulas e ignorar las negadas.

### Falla 4 — `sin_estructura`: el agente inventó 5 segmentos. Esta sí fue del agente. Y del prompt.

El criterio original decía *"si el silhouette máximo queda por debajo de 0.25,
no hay estructura"*. Sobre 140 puntos de **ruido uniforme puro**, el silhouette
máximo da **0.32**.

Es decir: el umbral que yo había puesto a mano dejaba pasar el ruido. El agente
obedeció perfectamente una regla equivocada.

**El arreglo cambió el diseño del proyecto.** El silhouette no puede contestar
"¿hay estructura?", solo "¿cuántos grupos?". Para la primera pregunta hay que
comparar contra un **modelo nulo**: se permuta cada columna por separado, lo
cual destruye la estructura conjunta y conserva las distribuciones marginales.
Si tus datos no le ganan a su propia versión barajada, no tienes grupos, tienes
geometría.

| Datos | silhouette máx | gap contra el nulo |
|---|---|---|
| Ruido uniforme | 0.31 | **+0.01** |
| Una sola gaussiana | 0.26 | **−0.00** |
| Grupos plantados (k=3) | 0.85 | **+0.43** |
| `fact_sales` (marca × país) | 0.41 | **+0.087** |

Fíjate en los extremos: la separación entre ruido y estructura real es de un
orden de magnitud. Y fíjate en el último renglón.

### El hallazgo que no estaba en el plan

`fact_sales` —la tabla tipo Fact_Sales, agregada a 98 celdas marca × país— dio
silhouette de **0.41**, que suena perfectamente respetable, y un gap contra el
nulo de **0.087**. Los mismos datos barajados alcanzan 0.33.

**Casi todo ese 0.41 es geometría, no segmentos.** Una cartera de marcas por país
es un **continuo**: no hay grupos naturales esperando a que alguien los
encuentre.

Eso obligó a un tercer estado. Un booleano escondía justamente el caso más
frecuente:

| gap | estado | qué hacer |
|---|---|---|
| < 0.05 | `ninguna` | Parar. `structure_found=false`. No se negocia. |
| 0.05 – 0.15 | `marginal` | Puedes cortar el continuo si al negocio le sirve, pero lo declaras **partición operativa**, no hallazgo. |
| > 0.15 | `clara` | Adelante. |

La diferencia entre *"encontré tres segmentos"* y *"partí un continuo en tres
pedazos operables"* no es un matiz de redacción. La primera afirmación es falsa
y se cae en cuanto alguien la repregunta. La segunda es verdadera, igual de
accionable, y sostiene la repregunta.

**Segunda corrida: 39/39 checks, 7 de 7 casos.** Pero el número no es el
resultado. El resultado son los cuatro diagnósticos de arriba, y que tres de
ellos fueran errores míos y no del agente.

---

## Los cinco errores que se cometen construyendo esto

1. **Empezar por el prompt.** El prompt es la etapa 4 de 8. Empezar ahí produce
   un agente que suena bien y no hace nada verificable.
2. **Herramientas que deciden.** Si `analizar_todo()` elige la k, el agente no
   es un agente, es una fachada.
3. **Devolver datos crudos en los `tool_result`.** Ahoga el contexto y empeora
   todas las decisiones siguientes. Devuelve resúmenes.
4. **No dejarle salida honesta.** Sin permiso explícito de decir "no hay nada",
   el agente inventa. Este es *el* modo de fallo de los agentes analíticos.
5. **Evaluar mirando.** Sin ground truth no sabes si mejoraste o solo cambiaste.
6. **Poner umbrales a mano sin verificarlos contra un caso nulo.** "Silhouette
   menor a 0.25 = no hay nada" sonaba razonable y dejaba pasar ruido puro.
   Si tu criterio no tiene un control negativo que lo reprobaría, no es un
   criterio, es una corazonada con decimales.
7. **Culpar al agente cuando falla el eval.** Tres de las cuatro fallas de la
   primera corrida estaban en los datos de prueba y en el calificador.

---

## De aquí a synthetic customers

La extensión natural, y la que conecta con Customer Link y con el JD de PwC, es
la fase 2: en vez de segmentar clientes reales, **generar** clientes sintéticos a
partir de las distribuciones observadas y validar que se comportan como los
reales.

La arquitectura ya lo aguanta: son herramientas nuevas en `tools.py`
(`fit_distributions`, `sample_synthetic_cohort`, `validate_against_holdout`) y
casos nuevos en `evals/cases.py`. El bucle, los guardrails y el trace no cambian.

Y el problema difícil está señalado desde ahora: **la validación**. Se usa IA
para modelar comportamiento que la IA misma empieza a ejecutar, mientras el dato
real contra el que validas se contamina con decisiones mediadas por agentes.
Sabiendo que ese es el problema central —y no la generación, que es la parte
fácil— ya tienes la mitad de la conversación ganada con cualquiera que trabaje
en esto.
