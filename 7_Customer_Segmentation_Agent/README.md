# 7 — Agente de segmentación de clientes

**Stack:** Python · Claude API (tool use) · scikit-learn · pandas · pytest

Un agente que recibe datos de ventas y entrega segmentos accionables: decide la unidad de
análisis, elige las variables, estandariza, barre k, perfila y recomienda. O concluye que
no hay nada que segmentar, que resultó ser la parte difícil.

A diferencia de los otros casos del portafolio, este no es un análisis: es un sistema que
decide. El bucle agéntico está escrito a mano, sin LangChain ni framework, y corre completo
sin API key gracias a un planificador determinista incluido.

> **Aviso:** todos los datos son **sintéticos**, generados con `data/make_datasets.py`. Las
> marcas aparecen solo como contexto de negocio simulado y no corresponden a cifras reales de
> ninguna empresa. Los archivos `gt_*.csv` tienen los grupos **plantados a propósito**, con la
> respuesta guardada en una columna que el agente tiene prohibido leer. Sin esa respuesta
> conocida no habría forma de calificarlo con un número en vez de con una impresión.

---

## El hallazgo que justifica todo lo demás

Sobre **140 puntos de ruido uniforme puro** —sin grupos, sin estructura, nada— el
silhouette máximo da **0.32**.

Eso destruye cualquier umbral puesto a mano. La primera versión del criterio decía
"silhouette menor a 0.25 significa que no hay estructura", que suena razonable y **deja
pasar el ruido**. El agente obedeció perfectamente esa regla y entregó cinco segmentos con
nombres de negocio sobre datos aleatorios.

La pregunta correcta nunca fue "¿0.32 es alto?". Fue **"¿0.32 comparado con qué?"**.

La respuesta es un **modelo nulo**. Se permuta cada columna por separado: eso destruye la
estructura conjunta y conserva las distribuciones marginales. Si los datos no le ganan a su
propia versión barajada, no hay grupos, hay geometría.

| Datos | silhouette máx | gap contra el nulo |
|---|---|---|
| Ruido uniforme | 0.31 | **+0.01** |
| Una sola gaussiana | 0.26 | **−0.00** |
| Grupos plantados (k=3) | 0.85 | **+0.43** |
| Cartera marca × país | 0.41 | **+0.087** |

Son dos preguntas distintas y necesitan dos herramientas distintas. **¿Hay algún grupo?** lo
contesta el gap contra el nulo. **¿Cuántos grupos?** lo contesta el silhouette. Confundirlas
es el error metodológico más común de una segmentación, y es fácil de cometer porque el
silhouette contesta las dos con la misma cara de seguridad.

---

## El renglón incómodo de esa tabla

La cartera de marca × país —98 celdas agregadas desde 32,000 transacciones— da silhouette
**0.41**, que suena perfectamente respetable, y un gap contra el nulo de **0.087**. Los
mismos datos barajados alcanzan 0.33.

**Casi todo ese 0.41 es geometría.** Una cartera de marcas por país es un **continuo**: no
hay grupos naturales esperando a que alguien los encuentre.

Eso obligó a un tercer estado, porque un booleano escondía justamente el caso más frecuente:

| gap | estado | qué hace el agente |
|---|---|---|
| < 0.05 | `ninguna` | Se detiene. `structure_found=false`. No se negocia |
| 0.05 – 0.15 | `marginal` | Corta el continuo si al negocio le sirve, pero lo declara **partición operativa** |
| > 0.15 | `clara` | Adelante |

La diferencia entre *"encontré dos segmentos"* y *"partí un continuo en dos pedazos
operables"* no es una cuestión de redacción. La primera afirmación es falsa y se cae en
cuanto alguien la repregunta. La segunda es verdadera, igual de accionable, y sostiene la
repregunta. El agente está obligado a escribir la segunda en sus caveats, y hay un eval que
lo verifica.

---

## Arquitectura

Ocho capas, una por etapa del proceso de construir un agente. El orden importa: quien
empieza por el prompt termina con algo que suena bien y no hace nada verificable.

```
analytics.py    Estadística pura. Cero LLM. Se prueba con pytest sin gastar un token
tools.py        Los schemas: el contrato entre el modelo y el código
guardrails.py   El "no" que el modelo no se dice solo. Ocho reglas
prompts.py      Un trabajo, un criterio de calidad, una condición de paro
loop.py         El bucle, a mano, ~90 líneas. Más un planificador determinista
trace.py        Cada vuelta a JSONL, para contestar "¿por qué eligió k=5?"
```

**El agente no sabe estadística. La ejecuta.** Toda la matemática vive en `analytics.py`,
en funciones normales de pandas y scikit-learn. Si mañana se quita el modelo, ese archivo
sigue funcionando; si ese archivo está mal, ningún prompt lo salva.

**Las herramientas devuelven resúmenes, nunca la tabla.** Un `tool_result` de 40,000 tokens
de CSV ahoga el contexto y empeora todas las decisiones siguientes. El modelo mueve nombres
de tablas; los objetos grandes se quedan en memoria.

**`submit_findings` es una herramienta terminal con schema estructurado.** El agente no
termina escribiendo un párrafo bonito: termina llenando campos. Esa es la razón técnica por
la que este agente se puede evaluar y un chatbot no.

---

## Los guardrails

Un agente sin barandales no es peligroso porque se rebele. Es peligroso porque es
**complaciente**: le pides tres segmentos y te da tres segmentos, haya estructura o no.

La decisión de diseño que importa es que un guardrail **no lanza una excepción que mata el
proceso**. Devuelve el error al modelo como `tool_result`, y el modelo tiene que corregirse
en la siguiente vuelta. Corriendo la demo se ve así:

```
-> sweep_k {"table": "entities"}
   BLOQUEADO [R4] 'entities' no está estandarizada. K-means usa distancia euclidiana:
   sin estandarizar, la variable de rango más grande decide los clusters ella sola.
-> standardize_features {"table": "entities", "features": [...]}
   ok
```

| Regla | Bloquea | Modo de fallo que ataca |
|---|---|---|
| R0 | Usar la columna con la respuesta como variable | Si el modelo la toca, el eval deja de medir |
| R1 | Tabla inexistente | Alucinación de nombres |
| R2 | Clusterizar con menos de 20 entidades | Con esa muestra el resultado cambia con la semilla |
| R3 | Segmentar con una sola variable | Eso no es segmentación, es cortar un histograma |
| R4 | **Clusterizar sin estandarizar** | El error metodológico clásico |
| R5 | Elegir k sin haber barrido | Elegir k sin ver el silhouette es adivinar |
| R6 | Perfilar sin modelo | Orden de operaciones |
| R7 | Concluir sin perfilar | Afirmar hallazgos sin haberlos mirado |

---

## Lo que pasó al correr los evals por primera vez

**33 de 40 checks. Tres de siete casos completos.** Cuatro casos fallaron, y al abrirlos
**solo uno era culpa del agente**:

**El dataset de k=5 tenía dos centros traslapados.** Los centros se habían colocado al azar
y dos cayeron a 1.0 desviaciones de distancia. k=4 era la respuesta estadísticamente
correcta para esos datos, y el eval reprobaba al agente por acertar.

> Cuando un eval falla, el primer sospechoso es el eval. Un caso cuyo ground truth no está
> realmente en los datos no mide al agente: mide tu descuido.

**El dataset de "escala traidora" no servía, y falló dos veces antes de quedar bien.** Con
ruido uniforme, el ruido se dejaba clusterizar mejor que la señal. Con la señal en una sola
dimensión, k-means multivariado no la recuperaba aunque estuviera ahí. La señal tiene que
ser multivariada para que un método multivariado la vea. La tercera versión da ARI de 1.00
estandarizando y 0.02 sin estandarizar: azar.

**El calificador reprobó una frase por la palabra que contenía, ignorando la negación.** La
frase era *"margen sano con poca escala **no es motivo de discontinuación**"*, y dice
exactamente lo contrario de lo que el check quería castigar.

> La negación es el falso positivo clásico de cualquier eval basado en texto. Por eso el
> string-matching es el último recurso y no el primero.

**Y la que sí fue del agente:** inventó cinco segmentos sobre ruido puro, obedeciendo
perfectamente un umbral mal puesto. Arreglarla cambió el diseño del proyecto y produjo el
hallazgo de arriba.

Segunda corrida: **39 de 39, siete de siete.** Pero el número no es el resultado. El
resultado son los cuatro diagnósticos, y que tres de ellos estuvieran en mis datos de
prueba y en mi calificador.

---

## Los evals

Siete casos, y cada uno ataca un modo de fallo **distinto**. Una suite donde los siete casos
miden la misma habilidad es una colección de ejemplos bonitos, no un eval.

| Caso | Qué mide |
|---|---|
| `k2` `k3` `k5` | Precisión básica, y sesgo hacia pocos segmentos |
| `sin_estructura` | **Complacencia.** El fallo más común de los agentes analíticos |
| `escala_traidora` | Rigor: los grupos solo aparecen si estandariza |
| `long_tail` | Criterio comercial: leer la desproporción tamaño contra valor |
| `fact_sales_e2e` | Proceso completo sobre transacciones crudas, y honestidad en el caso marginal |

La métrica que hace la diferencia es el **ARI** (Adjusted Rand Index). Acertar el *número*
de grupos no prueba nada si las entidades quedaron en el grupo equivocado. El ARI compara la
asignación real contra la del agente y corrige por azar: 0 es tirar una moneda, 1 es
perfecto. Es lo que atrapa al agente que dice "k=2" sobre `escala_traidora` sin haber
estandarizado, donde la k está bien y el resultado es basura.

---

## Cómo correrlo

Sin API key, con un planificador determinista en lugar del modelo:

```bash
pip install -r requirements.txt
python3 data/make_datasets.py     # genera los datasets
python3 run.py --mock             # el bucle completo
```

Con Claude de verdad:

```bash
export ANTHROPIC_API_KEY="sk-..."
python3 run.py
```

Los evals y las pruebas:

```bash
python3 evals/run_evals.py --mock     # 39 checks
python3 -m pytest tests/ -q           # 18 pruebas
```

**Qué mirar, en orden.** Primero el guardrail R4 disparándose en la demo y el agente
corrigiéndose solo en la siguiente vuelta. Después el agente diciendo que no:

```bash
python3 run.py --data data/gt_sin_estructura.csv --mock
```

Y por último los caveats al final de la corrida sobre `fact_sales`, donde el agente declara
que lo que entregó es una partición operativa y no un hallazgo.

---

## Por qué hay un modo `--mock`

Es un planificador determinista que ocupa el lugar del modelo. Existe por dos razones: el
bucle completo se puede correr sin API key y sin gastar un peso, y los tests del bucle no
dependen de una llamada de red. **Un test que a veces falla porque el modelo cambió de
opinión no es un test.**

Comete a propósito el error de clusterizar sin estandarizar, para que el ciclo de bloqueo y
corrección se vea en cada corrida.

---

## Estructura

```
├── run.py                   CLI
├── PROCESO.md               las ocho etapas, con la decisión y el porqué de cada una
├── agent/
│   ├── analytics.py         estadística pura, cero LLM
│   ├── tools.py             8 herramientas; submit_findings es terminal y estructurada
│   ├── guardrails.py        8 reglas que rechazan y devuelven el error al modelo
│   ├── prompts.py           trabajo, criterio de calidad, condición de paro
│   ├── loop.py              el bucle a mano + el planificador determinista
│   └── trace.py             JSONL por vuelta
├── data/make_datasets.py    ground truth plantado + una tabla tipo Fact_Sales
├── evals/                   7 casos, 7 dimensiones, ARI contra ground truth
├── tests/                   18 pruebas, rápidas y sin red
└── runs/                    traza de ejemplo y reporte de evals
```

**[PROCESO.md](./PROCESO.md) es el documento que importa.** El código es la evidencia; ahí
están las ocho etapas en orden, los cinco errores típicos y el post-mortem completo de la
primera corrida de evals.

---

## Dónde queda ciego el diseño

**El umbral del gap es una elección, no una ley.** Está calibrado contra dos controles
negativos —ruido uniforme y una sola gaussiana— que dan 0.01 o menos, frente a datos con
grupos que dan de 0.20 para arriba. El hueco es de un orden de magnitud, así que cualquier
corte entre 0.05 y 0.15 separa igual de bien. Pero es un corte, y los casos que caen cerca
de él necesitan criterio humano. Por eso existe el estado `marginal` en vez de un booleano.

**El modelo nulo por permutación no ve estructura que viva en una sola marginal.** Permutar
conserva las distribuciones de cada columna, así que si la señal es que una variable es
bimodal, la versión barajada sigue siendo bimodal y el gap no la detecta. Se encontró
construyendo el dataset de escala traidora, y es la razón de que su señal esté repartida en
dos dimensiones. Queda declarado.

**K-means asume grupos aproximadamente esféricos y de tamaño similar.** Con formas alargadas
falla, y nada en este agente lo detecta. Un DBSCAN o un modelo de mezclas gaussianas como
segunda opinión cerraría ese hueco.

**No está probado contra la API real de Claude.** Los 39 checks se corrieron con el
planificador determinista, que respeta el criterio del modelo nulo porque así está
programado. Falta ver si Claude también lo respeta o si es complaciente donde el mock no lo
es. Ése es el eval más interesante que queda pendiente.

---

## Pendientes conocidos

- Correr la suite completa contra la API real y comparar tasa de acierto contra el mock.
- Segunda opinión con un método que no asuma clusters esféricos.
- Fase 2, clientes sintéticos: `fit_distributions`, `sample_synthetic_cohort` y
  `validate_against_holdout` como herramientas nuevas. El bucle, los guardrails y el trace
  no cambian. El problema difícil no es generar, es validar.
