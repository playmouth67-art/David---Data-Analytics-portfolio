#!/usr/bin/env python3
"""
CAPA 7 — EVALS: el calificador.

    python3 evals/run_evals.py --mock
    python3 evals/run_evals.py --model claude-sonnet-4-5

Siete dimensiones, todas calculables sin opinar:

  estructura   El agente acerto en si hay o no segmentacion util.
  k            Acerto el numero de grupos.
  ARI          Adjusted Rand Index contra el ground truth: mide si las
               entidades quedaron en el grupo correcto, no solo si el
               conteo cuadro. Corrige por azar (0 = azar, 1 = perfecto).
  escalado     Estandarizo antes de clusterizar.
  silhouette   Justifico la k con el silhouette y no de oido.
  nombres      Puso nombres de negocio, no "Cluster 0".
  criterio     No recomendo matar un segmento de margen sano y poca escala.

Nota sobre por que esto importa mas de lo que parece: los errores de un
agente se COMPONEN. Diez pasos al 95% de acierto dan 60% de tarea completa.
Sin evals no sabes en cual de los diez estas perdiendo.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sklearn.metrics import adjusted_rand_score  # noqa: E402

from agent.loop import run  # noqa: E402
from evals.cases import CASES  # noqa: E402

OK, NO, NA = "\033[32mPASA\033[0m", "\033[31mFALLA\033[0m", "\033[90m --\033[0m"

NEGADORES = (" no ", "no es", "nunca", " sin ", "en vez de", "lejos de", "antes que")


def _recomienda_matar(accion: str, prohibidas: list[str]) -> bool:
    """
    Buscar palabras prohibidas a pelo produce falsos positivos, y este eval
    se comio uno en la primera corrida: reprobo la frase

        "margen sano con poca escala no es motivo de discontinuacion"

    porque contiene "discontinu". La frase dice exactamente lo contrario de
    lo que el check queria castigar.

    Leccion aplicable a cualquier eval basado en texto: la NEGACION es el
    falso positivo clasico. Aqui se parte la accion en clausulas y se ignora
    la que venga negada. Sigue siendo fragil -por eso los evals de texto son
    el ultimo recurso, no el primero-, pero ya no reprueba lo correcto.
    """
    for clausula in re.split(r"[;,.]", accion.lower()):
        if any(p in clausula for p in prohibidas) and not any(n in f" {clausula} " for n in NEGADORES):
            return True
    return False


def score_case(case, res) -> dict:
    f = res.findings or {}
    ws = res.workspace
    tools_used = res.trace_summary["tools_used"]
    checks: dict[str, bool | None] = {}

    # -- estructura ---------------------------------------------------------
    if case["expect_structure"] is None:
        checks["estructura"] = None
    else:
        checks["estructura"] = bool(f.get("structure_found")) == case["expect_structure"]

    # -- k ------------------------------------------------------------------
    if case["expect_k"] is None:
        checks["k"] = None
    else:
        checks["k"] = int(f.get("chosen_k", -1)) == case["expect_k"]

    # -- ARI contra ground truth -------------------------------------------
    ari = None
    if case["min_ari"] is not None:
        tbl = next((t for t in ws.tables.values()
                    if "Cluster" in t.columns and "_true_cluster" in t.columns), None)
        if tbl is not None:
            ari = adjusted_rand_score(tbl["_true_cluster"], tbl["Cluster"])
            checks["ARI"] = ari >= case["min_ari"]
        else:
            checks["ARI"] = False
    else:
        checks["ARI"] = None

    # -- escalado antes de clusterizar -------------------------------------
    if "fit_segmentation" in tools_used:
        i_scale = tools_used.index("standardize_features") if "standardize_features" in tools_used else 99
        checks["escalado"] = i_scale < tools_used.index("fit_segmentation")
    else:
        checks["escalado"] = None if not case["expect_structure"] else False

    # -- justifico con silhouette ------------------------------------------
    just = (f.get("justification") or "").lower()
    checks["silhouette"] = ("silhouette" in just) or (f.get("silhouette") is not None)

    # -- nombres de negocio -------------------------------------------------
    segs = f.get("segments") or []
    if segs:
        checks["nombres"] = not any(s["name"].strip().lower().startswith("cluster") for s in segs)
    else:
        checks["nombres"] = None

    # -- criterio comercial -------------------------------------------------
    prohibidas = case.get("prohibido_en_acciones")
    if prohibidas and segs:
        checks["criterio"] = not any(
            _recomienda_matar(s.get("action", ""), prohibidas) for s in segs
        )
    else:
        checks["criterio"] = None

    # -- pasos obligatorios del proceso -------------------------------------
    req = case.get("requiere_pasos")
    if req:
        checks["proceso"] = all(step in tools_used for step in req)

    # -- honestidad en el caso marginal -------------------------------------
    # Si el agente entrego segmentos sobre datos que son un continuo, tiene que
    # decirlo con esas palabras. Es el check mas parecido a lo que un cliente
    # notaria: no que el numero este mal, sino que este vendido como algo que no es.
    if case.get("exige_caveat_particion") and f.get("structure_found"):
        cav = (f.get("caveats") or "").lower()
        checks["honestidad"] = ("particion operativa" in cav or "continuo" in cav)

    evaluados = [v for v in checks.values() if v is not None]
    return {
        "checks": checks,
        "ari": None if ari is None else round(float(ari), 3),
        "passed": sum(evaluados),
        "total": len(evaluados),
        "all_pass": all(evaluados),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mock", action="store_true")
    p.add_argument("--model", default="claude-sonnet-4-5")
    p.add_argument("--only", help="Correr solo un caso por id.")
    a = p.parse_args()

    cases = [c for c in CASES if not a.only or c["id"] == a.only]
    print(f"\n\033[1mEVALS\033[0m  {len(cases)} casos  |  "
          f"{'mock' if a.mock else a.model}\n" + "=" * 78)

    rows, total_p, total_t = [], 0, 0
    for case in cases:
        print(f"\n\033[1m{case['id']}\033[0m  \033[90m{case['mide']}\033[0m")
        res = run(
            "Segmenta estos datos y dime donde esta el valor y que haria distinto "
            "con cada segmento.",
            {case["file"].stem: str(case["file"])},
            model=a.model, mock=a.mock, echo=False, max_turns=20,
        )
        sc = score_case(case, res)
        total_p += sc["passed"]
        total_t += sc["total"]

        line = "  "
        for name, val in sc["checks"].items():
            mark = NA if val is None else (OK if val else NO)
            line += f"{name}:{mark}  "
        print(line)
        got_k = (res.findings or {}).get("chosen_k")
        struct = (res.findings or {}).get("structure_found")
        detail = f"  \033[90mk={got_k} structure={struct}"
        if sc["ari"] is not None:
            detail += f" ARI={sc['ari']}"
        detail += (f" | vueltas={res.turns} bloqueos={len(res.trace_summary['blocked'])}"
                   f" tokens_in={res.trace_summary['input_tokens']}\033[0m")
        print(detail)
        if res.trace_summary["blocked"]:
            for rule, tool in res.trace_summary["blocked"]:
                print(f"  \033[33m  guardrail {rule} freno {tool} (y el agente se corrigio)\033[0m")

        rows.append({"case": case["id"], **{k: v for k, v in sc.items() if k != "checks"},
                     "checks": {k: v for k, v in sc["checks"].items()}})

    pct = 100 * total_p / total_t if total_t else 0
    print("\n" + "=" * 78)
    print(f"\033[1mTOTAL: {total_p}/{total_t} checks ({pct:.0f}%)   "
          f"casos perfectos: {sum(r['all_pass'] for r in rows)}/{len(rows)}\033[0m")

    root = Path(__file__).parent.parent
    out = root / "runs" / "eval_report.json"
    out.write_text(json.dumps({"pct": round(pct, 1), "rows": rows}, indent=2, ensure_ascii=False))
    print(f"\033[90mreporte: {out.relative_to(root)}\033[0m")


if __name__ == "__main__":
    main()
