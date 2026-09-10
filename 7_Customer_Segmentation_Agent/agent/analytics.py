"""
CAPA 1 — ANALYTICS. Cero LLM aqui dentro.

La regla de diseno mas importante del proyecto vive en este archivo:
el agente NO sabe estadistica. La ejecuta. Toda la matematica esta aqui,
en funciones normales de pandas y sklearn que se pueden probar con pytest
sin gastar un solo token.

Si manana quitas a Claude del proyecto, este archivo sigue funcionando.
Si este archivo esta mal, ningun prompt lo salva.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

# Ninguna columna que empiece con "_" entra jamas al modelo:
# asi el ground truth de los datasets de eval no se puede filtrar por accidente.
PRIVATE_PREFIX = "_"

# Umbrales del gap contra el modelo nulo, calibrados empiricamente:
#   ruido puro (uniforme y gaussiana unica) -> 0.00 a 0.01
#   datos con grupos plantados              -> 0.20 a 0.43
# El hueco entre ambos es enorme, pero los datos comerciales de verdad caen
# justo en medio: el fact_sales de este repo da 0.087. Por eso hay tres
# estados y no dos. Un booleano habria escondido el caso mas frecuente.
GAP_NINGUNA = 0.05
GAP_CLARA = 0.15


# ---------------------------------------------------------------------------
# ESTADO
# ---------------------------------------------------------------------------
@dataclass
class Workspace:
    """
    La memoria de trabajo del agente.

    Un agente sin estado tendria que recibir la tabla entera en cada tool_result,
    lo cual es caro e imposible con 32,000 filas. En vez de eso las herramientas
    devuelven RESUMENES y guardan los objetos grandes aqui, referenciados por
    nombre. El modelo mueve nombres, no datos.
    """
    tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    scaled: dict[str, np.ndarray] = field(default_factory=dict)
    scalers: dict[str, StandardScaler] = field(default_factory=dict)
    features: dict[str, list[str]] = field(default_factory=dict)
    models: dict[str, KMeans] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def public_columns(self, name: str) -> list[str]:
        return [c for c in self.tables[name].columns if not c.startswith(PRIVATE_PREFIX)]


# ---------------------------------------------------------------------------
# INSPECCION
# ---------------------------------------------------------------------------
def load_table(ws: Workspace, path: str, name: str) -> dict[str, Any]:
    df = pd.read_csv(path)
    ws.tables[name] = df
    return describe_table(ws, name)


def describe_table(ws: Workspace, name: str, max_cats: int = 8) -> dict[str, Any]:
    """
    Lo que el agente ve de una tabla. A proposito NO devuelve filas crudas:
    devuelve la forma, los tipos, y estadisticas. Un agente que pide 'muestrame
    las filas' termina con 40k tokens de CSV en contexto y peor criterio.
    """
    df = ws.tables[name]
    cols = ws.public_columns(name)
    out: dict[str, Any] = {"table": name, "rows": int(len(df)), "columns": {}}
    for c in cols:
        s = df[c]
        if pd.api.types.is_numeric_dtype(s):
            out["columns"][c] = {
                "type": "numeric",
                "min": round(float(s.min()), 3),
                "max": round(float(s.max()), 3),
                "mean": round(float(s.mean()), 3),
                "std": round(float(s.std()), 3),
                "nulls": int(s.isna().sum()),
            }
        else:
            vc = s.value_counts()
            out["columns"][c] = {
                "type": "categorical",
                "distinct": int(vc.size),
                "top": vc.head(max_cats).to_dict(),
                "nulls": int(s.isna().sum()),
            }
    return out


# ---------------------------------------------------------------------------
# AGREGACION
# ---------------------------------------------------------------------------
AGG_FUNCS = {"sum", "mean", "count", "median", "min", "max", "nunique"}


def aggregate(
    ws: Workspace,
    source: str,
    dest: str,
    group_by: list[str],
    metrics: dict[str, str],
    min_rows_per_group: int = 0,
) -> dict[str, Any]:
    """
    K-means necesita UNA FILA POR ENTIDAD. Una tabla de transacciones no lo es.
    Elegir la unidad de analisis (marca x pais, cliente, tienda x mes) es la
    decision de negocio mas cara de toda la segmentacion, y es la que se le
    esta delegando al agente. Por eso el trace registra su justificacion.
    """
    df = ws.tables[source]
    bad = [f for f in metrics.values() if f not in AGG_FUNCS]
    if bad:
        raise ValueError(f"Funciones de agregacion no permitidas: {bad}. Validas: {sorted(AGG_FUNCS)}")

    spec = {f"{col}_{fn}": (col, fn) for col, fn in metrics.items()}
    agg = df.groupby(group_by, dropna=False).agg(**spec).reset_index()
    agg["_n_source_rows"] = df.groupby(group_by, dropna=False).size().values

    dropped = 0
    if min_rows_per_group > 0:
        before = len(agg)
        agg = agg[agg["_n_source_rows"] >= min_rows_per_group].reset_index(drop=True)
        dropped = before - len(agg)

    ws.tables[dest] = agg
    res = describe_table(ws, dest)
    res["dropped_groups_below_threshold"] = dropped
    res["unit_of_analysis"] = " x ".join(group_by)
    return res


def add_share_of_total(ws: Workspace, table: str, value_col: str, within: str, new_col: str) -> dict[str, Any]:
    """Participacion de una fila dentro de su grupo. El proxy de share de mercado."""
    df = ws.tables[table]
    totals = df.groupby(within)[value_col].transform("sum")
    df[new_col] = (100 * df[value_col] / totals).round(4)
    ws.tables[table] = df
    return describe_table(ws, table)


# ---------------------------------------------------------------------------
# ESCALADO
# ---------------------------------------------------------------------------
def scale_features(ws: Workspace, table: str, features: list[str]) -> dict[str, Any]:
    """
    StandardScaler: resta la media, divide entre la desviacion estandar.

    No es un tramite. K-means mide distancia euclidiana; si Revenue_USD va en
    cientos de miles y Avg_Margin_Pct en decenas, revenue decide los clusters
    solo y el margen no se entera. El dataset gt_escala_traidora.csv existe
    para que veas ese fallo con tus ojos.
    """
    df = ws.tables[table]
    missing = [f for f in features if f not in df.columns]
    if missing:
        raise ValueError(f"Columnas inexistentes en '{table}': {missing}")
    non_numeric = [f for f in features if not pd.api.types.is_numeric_dtype(df[f])]
    if non_numeric:
        raise ValueError(f"Columnas no numericas, no se pueden escalar: {non_numeric}")

    X = df[features].to_numpy(dtype=float)
    if np.isnan(X).any():
        raise ValueError("Hay nulos en las features. Resuelvelos antes de escalar.")

    scaler = StandardScaler()
    ws.scaled[table] = scaler.fit_transform(X)
    ws.scalers[table] = scaler
    ws.features[table] = list(features)
    return {
        "table": table,
        "features": features,
        "n_entities": int(X.shape[0]),
        "raw_ranges": {f: [round(float(df[f].min()), 2), round(float(df[f].max()), 2)] for f in features},
        "scaled_mean_check": [round(float(v), 6) for v in ws.scaled[table].mean(axis=0)],
        "scaled_std_check": [round(float(v), 4) for v in ws.scaled[table].std(axis=0)],
    }


# ---------------------------------------------------------------------------
# ELECCION DE K
# ---------------------------------------------------------------------------
def sweep_k(
    ws: Workspace,
    table: str,
    k_min: int = 2,
    k_max: int = 8,
    n_null: int = 5,
    random_state: int = 42,
) -> dict[str, Any]:
    """
    Responde DOS preguntas distintas, con dos herramientas distintas.
    Confundirlas es el error metodologico mas comun de una segmentacion.

    PREGUNTA 1: cuantos grupos hay -> silhouette, argmax.
        La inercia siempre baja al subir k (con un punto por cluster llega a 0),
        asi que el codo orienta pero no decide. El silhouette si tiene maximo.

    PREGUNTA 2: hay ALGUN grupo -> comparacion contra un modelo nulo.
        Y aqui esta el punto que casi todo el mundo se salta: el silhouette
        NUNCA te dice que no hay estructura. Sobre 140 puntos de ruido uniforme
        puro, el silhouette maximo da 0.32 en k=5. Un umbral fijo tipo
        "0.25 = no hay nada" reprueba: 0.32 pasa el umbral y no hay nada.

        La respuesta correcta es preguntar "0.32 comparado con QUE". Se
        permuta cada columna por separado: eso destruye la estructura conjunta
        y conserva las distribuciones marginales. Si los datos reales no
        superan a su propia version barajada, no hay grupos, hay geometria.

        Sobre datos reales con grupos el gap da 0.20-0.43.
        Sobre ruido -uniforme o una sola gaussiana- da entre -0.00 y 0.01.
        La separacion es de un orden de magnitud, no un empate.
    """
    X = ws.scaled.get(table)
    if X is None:
        raise ValueError(f"'{table}' no ha sido escalada. Llama scale_features primero.")
    k_max = min(k_max, len(X) - 1)
    rng = np.random.default_rng(random_state)

    rows = []
    for k in range(k_min, k_max + 1):
        km = KMeans(n_clusters=k, random_state=random_state, n_init=10)
        labels = km.fit_predict(X)
        real_sil = float(silhouette_score(X, labels))

        # modelo nulo: mismas marginales, estructura conjunta destruida
        null_sils = []
        for _ in range(n_null):
            P = np.column_stack([rng.permutation(X[:, j]) for j in range(X.shape[1])])
            null_sils.append(float(silhouette_score(
                P, KMeans(n_clusters=k, random_state=random_state, n_init=10).fit_predict(P))))

        rows.append({
            "k": k,
            "inertia": round(float(km.inertia_), 2),
            "silhouette": round(real_sil, 4),
            "silhouette_null": round(float(np.mean(null_sils)), 4),
            "gap_vs_null": round(real_sil - float(np.mean(null_sils)), 4),
            "smallest_cluster_pct": round(100 * float(np.bincount(labels).min()) / len(labels), 1),
        })

    best_sil = max(rows, key=lambda r: r["silhouette"])
    max_gap = max(r["gap_vs_null"] for r in rows)
    k = best_sil["k"]
    sil = best_sil["silhouette"]

    if max_gap < GAP_NINGUNA:
        strength = "ninguna"
        verdict = (
            f"NO hay estructura. El gap contra el modelo nulo es {max_gap:.3f}: los datos no "
            f"le ganan a su propia version barajada. El silhouette de {sil} en k={k} es un "
            "espejismo, ruido puro produce valores asi. Reporta structure_found=false."
        )
    elif max_gap < GAP_CLARA:
        strength = "marginal"
        verdict = (
            f"Estructura MARGINAL: gap {max_gap:.3f}, entre {GAP_NINGUNA} y {GAP_CLARA}. "
            f"El silhouette de {sil} en k={k} suena bien, pero datos barajados con estas "
            f"mismas distribuciones alcanzan {best_sil['silhouette'] - max_gap:.3f}, asi que casi "
            "todo ese numero es geometria, no grupos. Esto es lo que suele pasar con carteras "
            "comerciales reales: son un CONTINUO, no grupos naturales.\n"
            "Que hacer: puedes cortar el continuo en k partes si eso le sirve al negocio, pero "
            "reportalo como una particion operativa y NO como el descubrimiento de segmentos "
            "que existian. Ponlo en caveats con estas palabras. La alternativa honesta es "
            "structure_found=false y pedir mas variables (recencia, frecuencia, canal, "
            "comportamiento) antes de forzar clusters."
        )
    else:
        strength = "clara"
        verdict = (
            f"HAY estructura clara: gap {max_gap:.3f} contra el modelo nulo. "
            f"El silhouette apunta a k={k} ({sil})."
        )

    return {
        "table": table,
        "sweep": rows,
        "structure_detected": strength == "clara",
        "structure_strength": strength,
        "max_gap_vs_null": round(max_gap, 4),
        "gap_thresholds": {"ninguna_por_debajo_de": GAP_NINGUNA, "clara_por_encima_de": GAP_CLARA},
        "best_k_by_silhouette": k,
        "best_silhouette": sil,
        "verdict": verdict,
        "reading_guide": (
            "gap_vs_null contesta SI existe algo. silhouette contesta CUANTOS. No las confundas: "
            "un silhouette alto sobre datos sin estructura es comun. "
            "Un cluster con menos del 5% de las entidades suele ser ruido, no un segmento."
        ),
    }


# ---------------------------------------------------------------------------
# MODELO FINAL Y PERFILADO
# ---------------------------------------------------------------------------
def fit_kmeans(ws: Workspace, table: str, k: int, random_state: int = 42) -> dict[str, Any]:
    X = ws.scaled.get(table)
    if X is None:
        raise ValueError(f"'{table}' no ha sido escalada. Llama scale_features primero.")
    km = KMeans(n_clusters=k, random_state=random_state, n_init=10)
    labels = km.fit_predict(X)
    ws.models[table] = km
    ws.tables[table]["Cluster"] = labels
    return {
        "table": table,
        "k": k,
        "silhouette": round(float(silhouette_score(X, labels)), 4),
        "cluster_sizes": {int(c): int(n) for c, n in zip(*np.unique(labels, return_counts=True))},
    }


def profile_segments(ws: Workspace, table: str, value_col: str | None = None) -> dict[str, Any]:
    """
    El perfilado es donde la segmentacion se vuelve negocio.

    Los centroides describen. Lo que decide es la DESPROPORCION: un segmento
    con 15% de las entidades y 45% del valor es donde esta el dinero; uno con
    40% de las entidades y 8% del valor es donde esta el esfuerzo mal invertido.
    Por eso value_concentration se calcula siempre que haya una columna de valor.
    """
    df = ws.tables[table]
    if "Cluster" not in df.columns:
        raise ValueError(f"'{table}' no tiene columna Cluster. Corre fit_kmeans primero.")
    feats = ws.features.get(table, [])

    prof = df.groupby("Cluster")[feats].mean().round(3)
    prof["n_entities"] = df.groupby("Cluster").size()
    prof["pct_of_entities"] = (100 * prof["n_entities"] / len(df)).round(1)

    out: dict[str, Any] = {"table": table, "profiles": prof.reset_index().to_dict(orient="records")}

    if value_col and value_col in df.columns:
        share = df.groupby("Cluster")[value_col].sum()
        share_pct = (100 * share / share.sum()).round(1)
        out["value_concentration"] = [
            {
                "cluster": int(c),
                "pct_of_entities": float(prof.loc[c, "pct_of_entities"]),
                f"pct_of_{value_col}": float(share_pct[c]),
                "concentration_ratio": round(float(share_pct[c] / prof.loc[c, "pct_of_entities"]), 2),
            }
            for c in prof.index
        ]
        out["how_to_read"] = (
            "concentration_ratio > 1 => el segmento pesa mas en valor que en numero. "
            "< 1 => pesa menos. Un ratio cercano a 1 en todos los segmentos significa "
            "que la segmentacion no encontro nada accionable, y eso hay que decirlo."
        )

    # Ejemplos nombrados, si hay una columna de identidad
    id_cols = [c for c in df.columns if df[c].dtype == object and c != "Cluster"]
    if id_cols:
        key = id_cols[0]
        out["examples"] = {
            int(c): df[df["Cluster"] == c][key].head(4).tolist() for c in sorted(df["Cluster"].unique())
        }
    return out
