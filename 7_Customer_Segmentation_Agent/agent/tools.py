"""
CAPA 3 — HERRAMIENTAS. El contrato entre el modelo y el codigo.

Tres reglas de diseno que se aplicaron aqui:

1. UNA HERRAMIENTA HACE UNA COSA. Nada de un `analizar_todo()` que esconde
   las decisiones adentro. Si la herramienta decide, el agente no aprende
   nada y tu no puedes auditar por que salio ese resultado.

2. LA DESCRIPCION ES EL PROMPT. El modelo no ve el codigo, ve el `description`
   y el schema. Cada palabra que quites de ahi es criterio que le quitas.

3. EL RESULTADO ES CONTEXTO. Todo lo que devuelve una herramienta se paga en
   tokens y compite por la atencion del modelo. Por eso devuelven resumenes
   compactos, nunca la tabla.

La ultima herramienta, submit_findings, es terminal: cierra el bucle y
obliga a que la conclusion salga ESTRUCTURADA. Esa es la razon tecnica por
la que este agente se puede evaluar y un chatbot no.
"""

from __future__ import annotations

from typing import Any

from . import analytics as an
from .analytics import Workspace

TOOLS: list[dict[str, Any]] = [
    {
        "name": "inspect_table",
        "description": (
            "Devuelve la forma de una tabla: numero de filas, y por columna su tipo, "
            "rango, media, desviacion y nulos. Es el primer paso obligado: no elijas "
            "unidad de analisis ni variables sin haber visto esto. No devuelve filas "
            "crudas a proposito."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"table": {"type": "string", "description": "Nombre de la tabla en el workspace."}},
            "required": ["table"],
        },
    },
    {
        "name": "aggregate_to_entities",
        "description": (
            "Colapsa una tabla de transacciones a UNA FILA POR ENTIDAD, que es lo que "
            "k-means necesita. Elegir la unidad de analisis (marca x pais, cliente, "
            "tienda x mes) es la decision de negocio mas importante del ejercicio: "
            "define sobre que puede actuar un equipo comercial el lunes. "
            "Usa min_rows_per_group para descartar celdas con tan pocas transacciones "
            "que su promedio no es estimacion sino ruido."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "dest": {"type": "string", "description": "Nombre para la tabla agregada."},
                "group_by": {"type": "array", "items": {"type": "string"},
                             "description": "Columnas que definen la entidad."},
                "metrics": {
                    "type": "object",
                    "description": "Mapa columna -> funcion. Funciones: sum, mean, count, median, min, max, nunique.",
                    "additionalProperties": {"type": "string"},
                },
                "min_rows_per_group": {"type": "integer", "default": 0},
                "rationale": {"type": "string",
                              "description": "Por que ESTA unidad de analisis y no otra. Se registra en el trace."},
            },
            "required": ["source", "dest", "group_by", "metrics", "rationale"],
        },
    },
    {
        "name": "add_share_of_total",
        "description": (
            "Agrega una columna con el porcentaje que representa cada fila dentro de su "
            "grupo (por ejemplo, el ingreso de una marca como % del ingreso de su pais). "
            "Es el proxy de posicion competitiva, y suele ser mejor variable de "
            "segmentacion que el ingreso absoluto porque no confunde 'grande' con "
            "'grande para su mercado'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "table": {"type": "string"},
                "value_col": {"type": "string"},
                "within": {"type": "string", "description": "Columna que define el total (ej. Country)."},
                "new_col": {"type": "string"},
            },
            "required": ["table", "value_col", "within", "new_col"],
        },
    },
    {
        "name": "standardize_features",
        "description": (
            "Estandariza las variables elegidas (resta la media, divide entre la "
            "desviacion estandar). OBLIGATORIO antes de clusterizar: k-means mide "
            "distancia euclidiana, asi que sin esto la variable de rango mas grande "
            "decide los clusters sola. Elige variables que midan cosas DISTINTAS: "
            "meter ingreso y numero de transacciones a la vez cuenta la escala dos veces."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "table": {"type": "string"},
                "features": {"type": "array", "items": {"type": "string"}, "minItems": 2},
                "rationale": {"type": "string", "description": "Por que estas variables y que dejaste fuera."},
            },
            "required": ["table", "features", "rationale"],
        },
    },
    {
        "name": "sweep_k",
        "description": (
            "Corre k-means para cada k y contesta DOS preguntas distintas.\n"
            "(1) CUANTOS grupos: el silhouette, que tiene un maximo real. La inercia "
            "siempre baja al subir k, asi que el codo orienta pero no decide.\n"
            "(2) Si hay ALGUN grupo: compara contra un modelo nulo (los mismos datos "
            "con cada columna barajada por separado). Lee el campo "
            "structure_detected y el veredicto. Un silhouette alto NO prueba que "
            "haya estructura: ruido puro produce silhouettes de 0.32. Lo que lo "
            "prueba es superar a la version barajada de si mismo.\n"
            "Lee structure_strength: 'ninguna' significa parar y reportar "
            "structure_found=false; 'marginal' significa que los datos son un "
            "continuo y que si cortas, lo declaras como particion operativa en "
            "caveats; 'clara' significa seguir normal."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "table": {"type": "string"},
                "k_min": {"type": "integer", "default": 2},
                "k_max": {"type": "integer", "default": 8},
            },
            "required": ["table"],
        },
    },
    {
        "name": "fit_segmentation",
        "description": (
            "Ajusta el k-means final con la k elegida y asigna cada entidad a un segmento. "
            "Justifica la k con el silhouette Y con usabilidad comercial. Si eliges una k "
            "que el silhouette no respalda, dilo explicitamente y da la razon de negocio."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "table": {"type": "string"},
                "k": {"type": "integer"},
                "rationale": {"type": "string"},
            },
            "required": ["table", "k", "rationale"],
        },
    },
    {
        "name": "profile_segments",
        "description": (
            "Devuelve el retrato de cada segmento: promedio de cada variable, cuantas "
            "entidades tiene, que porcentaje del valor total concentra, y ejemplos "
            "nombrados. Lo que decide no son los centroides sino la DESPROPORCION entre "
            "% de entidades y % de valor: ahi esta el negocio."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "table": {"type": "string"},
                "value_col": {"type": "string", "description": "Columna de valor para medir concentracion (ej. Revenue_USD_sum)."},
            },
            "required": ["table"],
        },
    },
    {
        "name": "submit_findings",
        "description": (
            "Entrega la conclusion final y TERMINA el trabajo. Llamala una sola vez, "
            "al final. Si los datos no soportan una segmentacion util, pon "
            "structure_found=false y explica por que: eso es una respuesta correcta, "
            "no un fracaso. Inventar segmentos donde no los hay es el peor resultado posible."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "structure_found": {"type": "boolean"},
                "chosen_k": {"type": "integer", "description": "0 si structure_found es false."},
                "silhouette": {"type": "number"},
                "justification": {"type": "string", "description": "Por que esta k y no otra."},
                "segments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Nombre de negocio, no 'Cluster 0'."},
                            "n_entities": {"type": "integer"},
                            "pct_of_entities": {"type": "number"},
                            "pct_of_value": {"type": "number"},
                            "profile": {"type": "string", "description": "Retrato en una frase."},
                            "action": {"type": "string", "description": "Que se hace distinto con este segmento."},
                        },
                        "required": ["name", "profile", "action"],
                    },
                },
                "caveats": {"type": "string", "description": "Que NO soportan estos datos."},
            },
            "required": ["structure_found", "chosen_k", "justification", "caveats"],
        },
    },
]

TERMINAL_TOOL = "submit_findings"


def execute(ws: Workspace, tool: str, args: dict[str, Any]) -> Any:
    """Dispatch. Las excepciones se capturan arriba, en el bucle."""
    if tool == "inspect_table":
        return an.describe_table(ws, args["table"])

    if tool == "aggregate_to_entities":
        res = an.aggregate(
            ws, args["source"], args["dest"], args["group_by"], args["metrics"],
            int(args.get("min_rows_per_group", 0)),
        )
        ws.notes.append(f"aggregated:{args['dest']}:{args['rationale']}")
        return res

    if tool == "add_share_of_total":
        return an.add_share_of_total(ws, args["table"], args["value_col"], args["within"], args["new_col"])

    if tool == "standardize_features":
        res = an.scale_features(ws, args["table"], args["features"])
        ws.notes.append(f"scaled:{args['table']}:{args['rationale']}")
        return res

    if tool == "sweep_k":
        res = an.sweep_k(ws, args["table"], int(args.get("k_min", 2)), int(args.get("k_max", 8)))
        ws.notes.append(f"swept:{args['table']}:best_k={res['best_k_by_silhouette']}")
        return res

    if tool == "fit_segmentation":
        res = an.fit_kmeans(ws, args["table"], int(args["k"]))
        ws.notes.append(f"fitted:{args['table']}:k={args['k']}:{args['rationale']}")
        return res

    if tool == "profile_segments":
        res = an.profile_segments(ws, args["table"], args.get("value_col"))
        ws.notes.append(f"profiled:{args['table']}")
        return res

    if tool == TERMINAL_TOOL:
        return args

    raise ValueError(f"Herramienta desconocida: {tool}")
