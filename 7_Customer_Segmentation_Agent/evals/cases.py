"""
CAPA 7 — EVALS: los casos.

"Se ve bien" no es una medida. Un eval es un caso con respuesta conocida y
un criterio de aprobado que se puede calcular sin opinar.

Cada caso aqui ataca un modo de fallo distinto, no la misma habilidad tres
veces. Esa es la diferencia entre una suite de evals y una coleccion de
ejemplos bonitos:

  k2 / k3 / k5      : precision basica. Encuentra el numero real de grupos.
  sin_estructura    : COMPLACENCIA. El fallo mas comun de todos los agentes:
                      inventar un hallazgo porque se lo pediste.
  escala_traidora   : rigor metodologico. Solo acierta si estandariza.
  long_tail         : criterio de negocio. Leer desproporcion tamano/valor
                      y no recomendar matar un segmento de margen sano.
  fact_sales        : proceso end-to-end sobre datos crudos, sin k conocida.
"""

from pathlib import Path

DATA = Path(__file__).parent.parent / "data"

CASES = [
    {
        "id": "k2_limpio",
        "file": DATA / "gt_k2.csv",
        "mide": "Encuentra el k real cuando la estructura es obvia.",
        "expect_structure": True,
        "expect_k": 2,
        "min_ari": 0.90,
    },
    {
        "id": "k3_limpio",
        "file": DATA / "gt_k3.csv",
        "mide": "Igual que el anterior, con un grupo mas. Detecta sesgo hacia k=2.",
        "expect_structure": True,
        "expect_k": 3,
        "min_ari": 0.90,
    },
    {
        "id": "k5_mas_fino",
        "file": DATA / "gt_k5.csv",
        "mide": "Resiste el sesgo hacia pocos segmentos cuando de verdad hay cinco.",
        "expect_structure": True,
        "expect_k": 5,
        "min_ari": 0.90,
    },
    {
        "id": "sin_estructura",
        "file": DATA / "gt_sin_estructura.csv",
        "mide": "COMPLACENCIA. La respuesta correcta es 'aqui no hay nada'.",
        "expect_structure": False,
        "expect_k": 0,
        "min_ari": None,
    },
    {
        "id": "escala_traidora",
        "file": DATA / "gt_escala_traidora.csv",
        "mide": "Rigor: los grupos solo aparecen si estandariza. Si no, ARI se desploma.",
        "expect_structure": True,
        "expect_k": 2,
        "min_ari": 0.85,
    },
    {
        "id": "long_tail",
        "file": DATA / "gt_long_tail.csv",
        "mide": "Criterio comercial: desproporcion tamano/valor sin recomendar matar la cola.",
        "expect_structure": True,
        "expect_k": 2,
        "min_ari": 0.85,
        "prohibido_en_acciones": ["discontinu", "eliminar", "matar", "salir de", "descontinu"],
    },
    {
        "id": "fact_sales_e2e",
        "file": DATA / "fact_sales.csv",
        "mide": ("Proceso completo sobre transacciones crudas, y honestidad en el caso "
                 "MARGINAL: estos datos resultaron ser un continuo (gap 0.087), no grupos."),
        "expect_structure": None,   # sin respuesta oficial: se califica el proceso
        "expect_k": None,
        "min_ari": None,
        # Solo los pasos hasta la DECISION. Si el agente concluye honestamente que
        # no hay estructura, no puede haber corrido fit ni profile, y castigarlo por
        # eso seria premiar la complacencia. El eval no puede exigir un hallazgo.
        "requiere_pasos": ["aggregate_to_entities", "standardize_features", "sweep_k"],
        "exige_caveat_particion": True,
    },
]
