"""
CAPA 5 — OBSERVABILIDAD.

Un agente que no deja rastro no se puede depurar ni mejorar. Cada vuelta del
bucle se escribe como una linea JSON: que penso, que herramienta pidio, con
que argumentos, si el guardrail la dejo pasar, que devolvio, cuantos tokens
costo.

Esto no es lujo de produccion. Es la unica forma de contestar la pregunta
"por que el agente eligio k=5 aqui", que es la pregunta que siempre se hace.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class Trace:
    def __init__(self, run_dir: Path, run_id: str, echo: bool = True):
        run_dir.mkdir(parents=True, exist_ok=True)
        self.path = run_dir / f"{run_id}.jsonl"
        self.echo = echo
        self.t0 = time.time()
        self.events: list[dict[str, Any]] = []

    def log(self, kind: str, **payload: Any) -> None:
        ev = {"t": round(time.time() - self.t0, 3), "kind": kind, **payload}
        self.events.append(ev)
        with self.path.open("a") as fh:
            fh.write(json.dumps(ev, ensure_ascii=False, default=str) + "\n")
        if self.echo:
            self._print(ev)

    def _print(self, ev: dict[str, Any]) -> None:
        k = ev["kind"]
        if k == "thinking":
            txt = ev["text"].strip()
            if txt:
                print(f"\n  \033[90m{txt}\033[0m")
        elif k == "tool_call":
            args = {a: v for a, v in ev["args"].items() if a != "rationale"}
            print(f"\n  \033[36m-> {ev['tool']}\033[0m {json.dumps(args, ensure_ascii=False)[:160]}")
            if ev["args"].get("rationale"):
                print(f"     \033[90mmotivo: {ev['args']['rationale'][:150]}\033[0m")
        elif k == "blocked":
            print(f"     \033[31mBLOQUEADO [{ev['rule']}]\033[0m {ev['reason'][:200]}")
        elif k == "tool_error":
            print(f"     \033[31mERROR\033[0m {ev['error'][:200]}")
        elif k == "tool_result":
            print(f"     \033[32mok\033[0m {ev['summary'][:200]}")
        elif k == "done":
            print(f"\n\033[1m== terminado en {ev['turns']} vueltas ==\033[0m")

    def _relpath(self) -> str:
        """Ruta relativa al proyecto: una ruta absoluta filtra el entorno de quien corrio."""
        try:
            return str(self.path.relative_to(Path(__file__).parent.parent))
        except ValueError:
            return self.path.name

    def summary(self) -> dict[str, Any]:
        calls = [e for e in self.events if e["kind"] == "tool_call"]
        blocks = [e for e in self.events if e["kind"] == "blocked"]
        errors = [e for e in self.events if e["kind"] == "tool_error"]
        usage = [e for e in self.events if e["kind"] == "usage"]
        return {
            "trace_file": self._relpath(),
            "tool_calls": len(calls),
            "tools_used": [c["tool"] for c in calls],
            "blocked": [(b["rule"], b["tool"]) for b in blocks],
            "errors": len(errors),
            "input_tokens": sum(u.get("input", 0) for u in usage),
            "output_tokens": sum(u.get("output", 0) for u in usage),
            "wall_seconds": round(time.time() - self.t0, 1),
        }
