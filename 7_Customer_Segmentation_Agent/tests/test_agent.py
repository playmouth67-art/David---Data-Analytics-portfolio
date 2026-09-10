"""
Tests. Rapidos, deterministicos, sin red.

Regla que se siguio: la capa de analytics se prueba con pytest normal porque
es codigo normal. Solo el bucle necesita el modelo simulado. Si tus tests de
agente necesitan la API, no son tests, son facturas.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent import analytics as an
from agent import guardrails, tools
from agent.analytics import Workspace

DATA = Path(__file__).parent.parent / "data"


@pytest.fixture
def ws_k3():
    ws = Workspace()
    ws.tables["t"] = pd.read_csv(DATA / "gt_k3.csv")
    return ws


FEATS = ["Revenue_USD", "Avg_Margin_Pct", "Share_of_Country_Pct"]


# --------------------------------------------------------------- analytics
def test_describe_oculta_columnas_privadas(ws_k3):
    d = an.describe_table(ws_k3, "t")
    assert "_true_cluster" not in d["columns"]
    assert d["rows"] == 90  # 3 grupos x 30 por grupo


def test_escalado_deja_media_cero_y_std_uno(ws_k3):
    r = an.scale_features(ws_k3, "t", FEATS)
    assert all(abs(m) < 1e-9 for m in r["scaled_mean_check"])
    assert all(abs(s - 1) < 1e-3 for s in r["scaled_std_check"])


def test_sweep_encuentra_el_k_plantado(ws_k3):
    an.scale_features(ws_k3, "t", FEATS)
    r = an.sweep_k(ws_k3, "t")
    assert r["best_k_by_silhouette"] == 3, "el dataset tiene 3 grupos plantados"
    assert r["structure_detected"] is True


def test_inercia_siempre_baja(ws_k3):
    """La razon por la que el codo no puede decidir solo."""
    an.scale_features(ws_k3, "t", FEATS)
    inertias = [row["inertia"] for row in an.sweep_k(ws_k3, "t")["sweep"]]
    assert all(a > b for a, b in zip(inertias, inertias[1:]))


def test_el_silhouette_solo_no_detecta_ausencia_de_estructura():
    """
    El test que justifica el modelo nulo, y el que hizo cambiar el diseno.

    Sobre ruido uniforme puro el silhouette llega a ~0.32: por encima de
    cualquier umbral "razonable" que se te ocurra poner a mano. Lo unico que
    delata que no hay nada es que los datos no le ganan a su propia version
    barajada.
    """
    ws = Workspace()
    ws.tables["u"] = pd.read_csv(DATA / "gt_sin_estructura.csv")
    an.scale_features(ws, "u", FEATS)
    r = an.sweep_k(ws, "u")

    assert r["best_silhouette"] > 0.25, "ruido puro produce silhouettes enganosos"
    assert r["max_gap_vs_null"] < 0.05, "pero no le gana al modelo nulo"
    assert r["structure_strength"] == "ninguna"
    assert r["structure_detected"] is False


def test_el_modelo_nulo_si_detecta_estructura_real(ws_k3):
    """El otro lado: cuando SI hay grupos, el gap es de otro orden."""
    an.scale_features(ws_k3, "t", FEATS)
    r = an.sweep_k(ws_k3, "t")
    assert r["max_gap_vs_null"] > 0.20


def test_no_escalar_arruina_el_resultado():
    """El test que justifica el guardrail R4."""
    from sklearn.cluster import KMeans
    from sklearn.metrics import adjusted_rand_score

    df = pd.read_csv(DATA / "gt_escala_traidora.csv")
    X = df[FEATS].to_numpy(float)

    crudo = KMeans(2, random_state=42, n_init=10).fit_predict(X)
    ws = Workspace(); ws.tables["t"] = df
    an.scale_features(ws, "t", FEATS)
    escalado = KMeans(2, random_state=42, n_init=10).fit_predict(ws.scaled["t"])

    ari_crudo = adjusted_rand_score(df["_true_cluster"], crudo)
    ari_esc = adjusted_rand_score(df["_true_cluster"], escalado)
    assert ari_esc > 0.85, "escalado deberia recuperar los grupos reales"
    assert ari_crudo < 0.15, "sin escalar deberia ser practicamente azar"


def test_perfilado_mide_concentracion_de_valor():
    ws = Workspace()
    ws.tables["t"] = pd.read_csv(DATA / "gt_long_tail.csv")
    an.scale_features(ws, "t", FEATS)
    an.fit_kmeans(ws, "t", 2)
    p = an.profile_segments(ws, "t", value_col="Revenue_USD")
    ratios = [r["concentration_ratio"] for r in p["value_concentration"]]
    assert max(ratios) > 2.5, "el head deberia concentrar mucho mas valor que entidades"


def test_agregacion_rechaza_funcion_invalida():
    ws = Workspace()
    ws.tables["f"] = pd.DataFrame({"a": list("xxyy"), "b": [1, 2, 3, 4]})
    with pytest.raises(ValueError, match="no permitidas"):
        an.aggregate(ws, "f", "g", ["a"], {"b": "os.system"})


# -------------------------------------------------------------- guardrails
def test_r4_bloquea_clusterizar_sin_escalar(ws_k3):
    v = guardrails.check(ws_k3, "fit_segmentation", {"table": "t", "k": 3})
    assert not v.allowed and v.rule == "R4"


def test_r0_bloquea_columna_privada_como_feature(ws_k3):
    v = guardrails.check(ws_k3, "standardize_features",
                         {"table": "t", "features": ["Revenue_USD", "_true_cluster"]})
    assert not v.allowed and v.rule == "R0"


def test_r2_bloquea_muestra_diminuta():
    ws = Workspace()
    ws.tables["chico"] = pd.DataFrame({"a": np.arange(8.0), "b": np.arange(8.0)})
    v = guardrails.check(ws, "standardize_features", {"table": "chico", "features": ["a", "b"]})
    assert not v.allowed and v.rule == "R2"


def test_r5_bloquea_elegir_k_sin_barrer(ws_k3):
    an.scale_features(ws_k3, "t", FEATS)
    v = guardrails.check(ws_k3, "fit_segmentation", {"table": "t", "k": 3})
    assert not v.allowed and v.rule == "R5"


def test_r7_bloquea_concluir_sin_perfilar(ws_k3):
    v = guardrails.check(ws_k3, "submit_findings", {"structure_found": True, "chosen_k": 3})
    assert not v.allowed and v.rule == "R7"


def test_camino_feliz_pasa_todos_los_guardrails(ws_k3):
    assert guardrails.check(ws_k3, "inspect_table", {"table": "t"}).allowed
    tools.execute(ws_k3, "standardize_features",
                  {"table": "t", "features": FEATS, "rationale": "tres ejes distintos"})
    tools.execute(ws_k3, "sweep_k", {"table": "t"})
    assert guardrails.check(ws_k3, "fit_segmentation", {"table": "t", "k": 3}).allowed


# -------------------------------------------------------------------- bucle
def test_bucle_completo_en_mock(tmp_path):
    from agent.loop import run
    res = run("Segmenta esto.", {"gt_k3": str(DATA / "gt_k3.csv")},
              mock=True, echo=False, run_dir=tmp_path)
    assert res.findings is not None, "el agente debe terminar llamando submit_findings"
    assert res.findings["structure_found"] is True
    assert res.findings["chosen_k"] == 3


def test_el_guardrail_dispara_y_el_agente_se_corrige(tmp_path):
    """El comportamiento central: un rechazo no rompe la corrida, la endereza."""
    from agent.loop import run
    res = run("Segmenta esto.", {"gt_k3": str(DATA / "gt_k3.csv")},
              mock=True, echo=False, run_dir=tmp_path)
    reglas = [r for r, _ in res.trace_summary["blocked"]]
    assert "R4" in reglas, "el mock intenta clusterizar sin escalar a proposito"
    assert res.findings is not None, "y aun asi debe terminar bien"


def test_agente_reporta_ausencia_de_estructura(tmp_path):
    """El eval de complacencia, como test."""
    from agent.loop import run
    res = run("Segmenta esto.", {"u": str(DATA / "gt_sin_estructura.csv")},
              mock=True, echo=False, run_dir=tmp_path)
    assert res.findings["structure_found"] is False
    assert res.findings["chosen_k"] == 0
