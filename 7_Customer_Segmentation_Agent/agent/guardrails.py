"""
CAPA 2 — GUARDRAILS. El agente pide; esta capa decide si se le concede.

Un agente sin barandales no es peligroso porque se rebele. Es peligroso
porque es COMPLACIENTE: le pides tres segmentos y te da tres segmentos,
haya estructura o no. Los guardrails son el "no" que el modelo no se dice
solo.

Diseno clave: un guardrail NO lanza una excepcion que mata el programa.
Devuelve un error AL MODELO como tool_result, y el modelo tiene que
corregirse en la siguiente vuelta. Ver ese ciclo (bloqueo -> correccion)
es la demo mas util de todo el proyecto.
"""

from __future__ import annotations

from dataclasses import dataclass

from .analytics import PRIVATE_PREFIX, Workspace

MIN_ENTITIES = 20
MIN_FEATURES = 2
K_HARD_MAX = 12


@dataclass
class Verdict:
    allowed: bool
    reason: str = ""
    rule: str = ""


def check(ws: Workspace, tool: str, args: dict) -> Verdict:
    """Se llama ANTES de ejecutar cualquier herramienta."""

    table = args.get("table") or args.get("dest") or args.get("source")

    # --- R0: integridad del eval -------------------------------------------
    # Las columnas con "_" son ground truth o metadatos internos. Si el modelo
    # las usa como feature, el eval deja de medir nada.
    for f in args.get("features", []) or []:
        if f.startswith(PRIVATE_PREFIX):
            return Verdict(False, rule="R0",
                reason=(f"La columna '{f}' es interna y no esta disponible como variable. "
                        "Usa solo columnas de negocio."))

    # --- R1: la tabla existe -----------------------------------------------
    if tool in {"inspect_table", "standardize_features", "sweep_k", "fit_segmentation",
                "profile_segments", "add_share_of_total"}:
        if table not in ws.tables:
            return Verdict(False, rule="R1",
                reason=f"No existe la tabla '{table}'. Tablas disponibles: {sorted(ws.tables)}.")

    # --- R2: muestra suficiente para clusterizar ---------------------------
    if tool in {"standardize_features", "sweep_k", "fit_segmentation"}:
        n = len(ws.tables[table])
        if n < MIN_ENTITIES:
            return Verdict(False, rule="R2",
                reason=(f"'{table}' tiene {n} entidades. Por debajo de {MIN_ENTITIES} una "
                        "segmentacion no es estable: cambia con la semilla aleatoria. "
                        "Agrega a un nivel mas grueso o reporta que no hay muestra."))

    # --- R3: minimo de variables -------------------------------------------
    if tool == "standardize_features":
        feats = args.get("features") or []
        if len(feats) < MIN_FEATURES:
            return Verdict(False, rule="R3",
                reason=(f"Diste {len(feats)} variable(s). Con menos de {MIN_FEATURES} esto no es "
                        "segmentacion multivariada, es cortar un histograma en pedazos."))

    # --- R4: NO clusterizar sin estandarizar -------------------------------
    # El guardrail central del proyecto.
    if tool in {"sweep_k", "fit_segmentation"} and table not in ws.scaled:
        return Verdict(False, rule="R4",
            reason=(f"'{table}' no esta estandarizada. K-means usa distancia euclidiana: "
                    "sin estandarizar, la variable de rango mas grande decide los clusters "
                    "ella sola. Llama standardize_features antes."))

    # --- R5: elegir k a ciegas ---------------------------------------------
    if tool == "fit_segmentation":
        k = int(args.get("k", 0))
        n = len(ws.tables[table])
        if not (2 <= k <= min(K_HARD_MAX, n - 1)):
            return Verdict(False, rule="R5",
                reason=f"k={k} fuera de rango. Debe estar entre 2 y {min(K_HARD_MAX, n - 1)}.")
        if table not in ws.scaled or not ws.notes or not any(
            n_.startswith(f"swept:{table}") for n_ in ws.notes
        ):
            return Verdict(False, rule="R5",
                reason=("Todavia no has corrido sweep_k sobre esta tabla. Elegir k sin ver "
                        "el silhouette es adivinar. Corre sweep_k primero."))

    # --- R6: perfilar antes de tener modelo --------------------------------
    if tool == "profile_segments" and "Cluster" not in ws.tables[table].columns:
        return Verdict(False, rule="R6",
            reason=f"'{table}' no tiene segmentos asignados todavia. Corre fit_segmentation antes.")

    # --- R7: no concluir sin haber perfilado -------------------------------
    if tool == "submit_findings" and args.get("structure_found"):
        if not any(n_.startswith("profiled:") for n_ in ws.notes):
            return Verdict(False, rule="R7",
                reason=("Estas por afirmar que encontraste segmentos sin haberlos perfilado. "
                        "Corre profile_segments: sin centroides y sin concentracion de valor "
                        "no hay nada que recomendar."))

    return Verdict(True)
