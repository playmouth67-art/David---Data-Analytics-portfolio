"""
Generador de datasets para el agente de segmentacion.

POR QUE ESTE ARCHIVO EXISTE
---------------------------
Un agente no se evalua con "se ve bien". Se evalua contra una respuesta
conocida. Por eso aqui se generan dos familias de datos:

  1. Un dataset REALISTA tipo Fact_Sales (marca x pais), para la demo.
     No tiene respuesta "correcta" oficial: sirve para ver al agente trabajar.

  2. Datasets con GROUND TRUTH PLANTADO: sabemos cuantos grupos hay porque
     nosotros los pusimos. Sirven para calificar al agente con un numero.

La familia 2 incluye a proposito tres trampas:
  - sin_estructura : datos sin grupos reales. La respuesta honesta es
                     "no hay segmentacion util aqui". Un agente complaciente
                     inventara 3 segmentos igual.
  - escala_traidora: una variable en cientos de miles y otra en decenas.
                     Si el agente no estandariza, la variable grande decide
                     sola y el resultado es basura con buena pinta.
  - long_tail      : un grupo chico y valioso contra uno enorme y pobre.
                     Mide si el agente lee la DESPROPORCION tamano/valor,
                     que es donde vive el negocio, o solo describe promedios.

TODOS los datos aqui son sinteticos y estan declarados como tales.
No son el Fact_Sales del caso de portafolio: son una re-creacion con la
misma forma, para que el ejercicio sea reproducible en cualquier maquina.
"""

import numpy as np
import pandas as pd
from pathlib import Path

OUT = Path(__file__).parent
RNG_BASE = 20260903


# ---------------------------------------------------------------------------
# 1. DATASET REALISTA: transacciones tipo Fact_Sales
# ---------------------------------------------------------------------------
BRANDS = {
    # marca: (division, escala_relativa, margen_base)
    "Lancome":        ("Luxe",            1.00, 0.72),
    "Kiehls":         ("Luxe",            0.55, 0.70),
    "YSL Beaute":     ("Luxe",            0.62, 0.74),
    "Armani Beauty":  ("Luxe",            0.48, 0.73),
    "Biotherm":       ("Luxe",            0.30, 0.66),
    "LOreal Paris":   ("Consumer",        1.60, 0.58),
    "Maybelline":     ("Consumer",        1.25, 0.55),
    "Garnier":        ("Consumer",        1.10, 0.52),
    "NYX":            ("Consumer",        0.45, 0.57),
    "Essie":          ("Consumer",        0.22, 0.60),
    "Vichy":          ("Dermatological",  0.70, 0.68),
    "La Roche-Posay": ("Dermatological",  0.95, 0.69),
    "CeraVe":         ("Dermatological",  1.15, 0.63),
    "SkinCeuticals":  ("Dermatological",  0.35, 0.78),
    "Kerastase":      ("Professional",    0.58, 0.71),
    "Redken":         ("Professional",    0.40, 0.64),
    "Matrix":         ("Professional",    0.33, 0.60),
    "Pureology":      ("Professional",    0.18, 0.67),
    "Mizani":         ("Professional",    0.09, 0.62),
    "Carita":         ("Luxe",            0.07, 0.75),
}

COUNTRIES = {
    # pais: peso de mercado
    "Mexico":    1.00,
    "Brasil":    1.35,
    "Colombia":  0.42,
    "Chile":     0.33,
    "Argentina": 0.38,
}

CHANNELS = ["E-commerce", "Retail", "Farmacia", "Salon", "Travel Retail"]


def make_fact_sales(n_rows: int = 32_000, seed: int = RNG_BASE) -> pd.DataFrame:
    """Transacciones a nivel linea. Una fila = una venta."""
    rng = np.random.default_rng(seed)

    brand_names = list(BRANDS)
    # probabilidad de aparicion proporcional a escala x peso de pais
    brand_scale = np.array([BRANDS[b][1] for b in brand_names])
    country_names = list(COUNTRIES)
    country_w = np.array([COUNTRIES[c] for c in country_names])

    brands = rng.choice(brand_names, size=n_rows, p=brand_scale / brand_scale.sum())
    countries = rng.choice(country_names, size=n_rows, p=country_w / country_w.sum())

    divisions = np.array([BRANDS[b][0] for b in brands])
    margin_base = np.array([BRANDS[b][2] for b in brands])

    # ticket: lognormal, escalado por division
    div_ticket = {"Luxe": 78.0, "Consumer": 14.0, "Dermatological": 31.0, "Professional": 44.0}
    base_ticket = np.array([div_ticket[d] for d in divisions])
    revenue = base_ticket * rng.lognormal(mean=0.0, sigma=0.55, size=n_rows)

    discount = np.clip(rng.beta(2.0, 9.0, size=n_rows) * 0.55, 0, 0.5)
    margin_pct = np.clip(margin_base + rng.normal(0, 0.035, n_rows) - discount * 0.45, 0.05, 0.92)

    dates = pd.to_datetime("2022-01-01") + pd.to_timedelta(
        rng.integers(0, 365 * 3, size=n_rows), unit="D"
    )

    df = pd.DataFrame({
        "TransactionID": np.arange(1, n_rows + 1),
        "Date": dates,
        "Brand": brands,
        "Division": divisions,
        "Country": countries,
        "Channel": rng.choice(CHANNELS, size=n_rows),
        "Revenue_USD": revenue.round(2),
        "Discount_Pct": (discount * 100).round(2),
        "Margin_Pct": (margin_pct * 100).round(2),
    })
    df["Margin_USD"] = (df["Revenue_USD"] * df["Margin_Pct"] / 100).round(2)
    return df.sort_values("Date").reset_index(drop=True)


# ---------------------------------------------------------------------------
# 2. DATASETS CON GROUND TRUTH
# ---------------------------------------------------------------------------
def planted_clusters(k: int, n_per: int = 30, min_sep: float = 4.0,
                     sd: float = 0.55, seed: int = 7) -> pd.DataFrame:
    """
    k grupos gaussianos con SEPARACION MINIMA GARANTIZADA entre centros.

    El min_sep no es cosmetico. La primera version ponia los centros al azar,
    y con k=5 dos de ellos cayeron a 1.0 desviaciones de distancia: se
    traslapaban. El silhouette apuntaba a k=4, y k=4 era la respuesta
    ESTADISTICAMENTE CORRECTA para esos datos. El eval reprobaba al agente
    por acertar.

    Leccion, y es de las caras: cuando un eval falla, el primer sospechoso
    es el eval. Un caso de prueba cuyo ground truth no esta en los datos no
    mide al agente, mide tu descuido.
    """
    rng = np.random.default_rng(seed)
    centers: list[np.ndarray] = []
    guard = 0
    while len(centers) < k and guard < 50_000:
        guard += 1
        c = rng.normal(0, 3.4, 3)
        if all(np.linalg.norm(c - o) >= min_sep for o in centers):
            centers.append(c)
    if len(centers) < k:
        raise RuntimeError(f"No se pudieron colocar {k} centros con min_sep={min_sep}")

    X = np.vstack([rng.normal(c, sd, size=(n_per, 3)) for c in centers])
    return pd.DataFrame({
        "EntityID": [f"E{i:04d}" for i in range(len(X))],
        "Revenue_USD": (X[:, 0] * 9_000 + 45_000).round(2),
        "Avg_Margin_Pct": (X[:, 1] * 4 + 62).round(2),
        "Share_of_Country_Pct": (X[:, 2] * 1.8 + 7).round(3),
        "_true_cluster": [i for i in range(k) for _ in range(n_per)],
    })


def sin_estructura(n: int = 140, seed: int = 11) -> pd.DataFrame:
    """Nube uniforme. No hay grupos. La respuesta honesta es 'ninguno util'."""
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "EntityID": [f"U{i:04d}" for i in range(n)],
        "Revenue_USD": rng.uniform(8_000, 95_000, n).round(2),
        "Avg_Margin_Pct": rng.uniform(48, 79, n).round(2),
        "Share_of_Country_Pct": rng.uniform(0.4, 16, n).round(3),
        "_true_cluster": [-1] * n,
    })


def escala_traidora(seed: int = 13) -> pd.DataFrame:
    """
    Dos grupos reales, separados por MARGEN y por SHARE (rangos de decenas).
    Revenue_USD es ruido gaussiano puro con rango de cientos de miles.

    Sin estandarizar, revenue domina la distancia euclidiana y los clusters
    salen partidos por puro ruido: ARI ~ 0.02, es decir, azar.
    Con estandarizar, los dos grupos reales aparecen limpios: ARI = 1.00.

    Dos intentos previos de este dataset no servian, y por que fallaron
    tambien ensena:
      v1: ruido UNIFORME en dos dimensiones. Un rango uniforme estandarizado
          abarca 3.46 desviaciones y se parte facil; el ruido se dejaba
          clusterizar mejor que la senal.
      v2: senal en UNA sola dimension. Con dos dimensiones de ruido alrededor,
          k-means no recupera un corte unidimensional aunque este ahi.
    La senal tiene que ser multivariada para que k-means multivariado la vea.
    """
    rng = np.random.default_rng(seed)
    n = 60
    return pd.DataFrame({
        "EntityID": [f"T{i:04d}" for i in range(2 * n)],
        "Revenue_USD": rng.normal(450_000, 145_000, 2 * n).round(2),
        "Avg_Margin_Pct": np.concatenate([rng.normal(56, 1.6, n), rng.normal(74, 1.6, n)]).round(2),
        "Share_of_Country_Pct": np.concatenate([rng.normal(4.2, 0.7, n), rng.normal(11.5, 0.7, n)]).round(3),
        "_true_cluster": [0] * n + [1] * n,
    })


def long_tail(seed: int = 17) -> pd.DataFrame:
    """
    Un grupo chico (12 celdas) con casi todo el ingreso, y uno enorme
    (88 celdas) con poco. Mide si el agente reporta la desproporcion
    tamano/valor y no solo los promedios.
    """
    rng = np.random.default_rng(seed)
    head = pd.DataFrame({
        "Revenue_USD": rng.normal(310_000, 38_000, 12),
        "Avg_Margin_Pct": rng.normal(69, 2.5, 12),
        "Share_of_Country_Pct": rng.normal(18, 2.2, 12),
        "_true_cluster": 0,
    })
    tail = pd.DataFrame({
        "Revenue_USD": rng.normal(21_000, 6_500, 88),
        "Avg_Margin_Pct": rng.normal(66, 3.0, 88),
        "Share_of_Country_Pct": rng.normal(1.6, 0.6, 88),
        "_true_cluster": 1,
    })
    df = pd.concat([head, tail], ignore_index=True)
    df.insert(0, "EntityID", [f"L{i:04d}" for i in range(len(df))])
    for c in ["Revenue_USD", "Avg_Margin_Pct", "Share_of_Country_Pct"]:
        df[c] = df[c].round(2)
    return df


# ---------------------------------------------------------------------------
def main() -> None:
    fact = make_fact_sales()
    fact.to_csv(OUT / "fact_sales.csv", index=False)
    print(f"fact_sales.csv          {len(fact):>6,} filas  (transacciones, para la demo)")

    catalogo = {
        "gt_k2.csv": planted_clusters(2, seed=101),
        "gt_k3.csv": planted_clusters(3, seed=102),
        "gt_k5.csv": planted_clusters(5, n_per=28, seed=103),
        "gt_sin_estructura.csv": sin_estructura(),
        "gt_escala_traidora.csv": escala_traidora(),
        "gt_long_tail.csv": long_tail(),
    }
    for name, df in catalogo.items():
        df.to_csv(OUT / name, index=False)
        k = df["_true_cluster"].nunique() if df["_true_cluster"].iloc[0] != -1 else 0
        print(f"{name:<24}{len(df):>6,} filas  k_real={k if k else 'ninguno'}")


if __name__ == "__main__":
    main()
