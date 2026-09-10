#!/usr/bin/env python3
"""
CLI del agente de segmentacion.

    python3 run.py --mock                          # bucle completo, sin API key
    python3 run.py --data data/gt_sin_estructura.csv --mock
    python3 run.py                                 # con Claude de verdad
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent.loop import run

HERE = Path(__file__).parent


def main() -> None:
    p = argparse.ArgumentParser(description="Agente de segmentacion de clientes")
    p.add_argument("--data", default=str(HERE / "data" / "fact_sales.csv"))
    p.add_argument("--objective", default=(
        "Segmenta este portafolio y dime donde esta concentrado el valor y que "
        "haria distinto con cada segmento."
    ))
    p.add_argument("--model", default="claude-sonnet-4-5")
    p.add_argument("--mock", action="store_true", help="Planificador deterministico, sin API.")
    p.add_argument("--max-turns", type=int, default=20)
    p.add_argument("--quiet", action="store_true")
    a = p.parse_args()

    name = Path(a.data).stem
    print(f"\n\033[1mAGENTE DE SEGMENTACION\033[0m  |  {name}  |  "
          f"{'mock' if a.mock else a.model}\n" + "-" * 68)

    res = run(a.objective, {name: a.data}, model=a.model, mock=a.mock,
              max_turns=a.max_turns, echo=not a.quiet)

    print("\n" + "=" * 68)
    if res.findings:
        f = res.findings
        if f.get("structure_found"):
            print(f"\033[1mk elegida:\033[0m {f['chosen_k']}   "
                  f"\033[1msilhouette:\033[0m {f.get('silhouette')}")
            print(f"\033[1mpor que:\033[0m {f['justification']}\n")
            for s in f.get("segments", []):
                print(f"  \033[1m{s['name']}\033[0m")
                print(f"    {s['profile']}")
                print(f"    \033[36maccion:\033[0m {s['action']}\n")
        else:
            print("\033[1;33mSIN ESTRUCTURA UTIL\033[0m")
            print(f"  {f['justification']}\n")
        print(f"\033[1mcaveats:\033[0m {f['caveats']}")
    else:
        print(f"\033[31mSin conclusiones.\033[0m Motivo: {res.stopped_because}")

    print("\n" + "-" * 68)
    print("\033[1mtelemetria\033[0m " + json.dumps(res.trace_summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
