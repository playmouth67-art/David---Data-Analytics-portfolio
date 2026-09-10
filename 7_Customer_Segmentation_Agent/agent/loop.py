"""
CAPA 6 — EL BUCLE. El corazon, y son ~90 lineas.

Esto es lo unico que separa a un agente de una llamada a un chatbot:

    mientras el modelo pida herramientas:
        ejecutalas
        DEVUELVELE EL RESULTADO
        deja que decida el siguiente paso

La palabra que importa es "devuelvele". Un chatbot genera texto sobre datos
que ya tenia. Un agente actua, OBSERVA lo que paso, y ajusta. Todo lo demas
-frameworks, orquestadores, grafos- es azucar encima de estas lineas.

Se escribio a mano y sin LangChain a proposito: si no puedes escribir este
bucle, no sabes lo que el framework esta haciendo por ti.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import guardrails, tools
from .analytics import Workspace
from .prompts import SYSTEM

MAX_RESULT_CHARS = 6_000  # un tool_result gigante envenena el contexto


@dataclass
class RunResult:
    findings: dict[str, Any] | None
    workspace: Workspace
    trace_summary: dict[str, Any]
    turns: int
    stopped_because: str
    transcript: list[dict[str, Any]] = field(default_factory=list)


def _dictify(content: Any) -> list[dict[str, Any]]:
    """Normaliza bloques del SDK o del mock a dicts planos."""
    out = []
    for b in content:
        t = getattr(b, "type", None) or b.get("type")
        if t == "text":
            out.append({"type": "text", "text": getattr(b, "text", None) or b.get("text", "")})
        elif t == "tool_use":
            out.append({
                "type": "tool_use",
                "id": getattr(b, "id", None) or b.get("id"),
                "name": getattr(b, "name", None) or b.get("name"),
                "input": getattr(b, "input", None) or b.get("input", {}),
            })
    return out


def _shrink(payload: Any) -> str:
    s = json.dumps(payload, ensure_ascii=False, default=str)
    if len(s) > MAX_RESULT_CHARS:
        s = s[:MAX_RESULT_CHARS] + f'... [truncado, {len(s)} chars]'
    return s


def run(
    objective: str,
    datasets: dict[str, str],
    *,
    model: str = "claude-sonnet-4-5",
    max_turns: int = 20,
    mock: bool = False,
    echo: bool = True,
    run_dir: Path | None = None,
    run_id: str | None = None,
) -> RunResult:
    from .trace import Trace

    run_id = run_id or uuid.uuid4().hex[:8]
    tr = Trace(run_dir or Path(__file__).parent.parent / "runs", run_id, echo=echo)

    # --- estado inicial: cargar tablas ANTES de que el modelo hable ---------
    ws = Workspace()
    inventory = {}
    for name, path in datasets.items():
        import pandas as pd
        ws.tables[name] = pd.read_csv(path)
        inventory[name] = f"{len(ws.tables[name]):,} filas, columnas: {ws.public_columns(name)}"

    client = _MockModel(ws) if mock else _real_client()

    first = (
        f"{objective}\n\nTablas cargadas en el workspace:\n"
        + "\n".join(f"- {n}: {d}" for n, d in inventory.items())
    )
    messages: list[dict[str, Any]] = [{"role": "user", "content": first}]
    tr.log("objective", text=objective, tables=list(datasets))

    findings: dict[str, Any] | None = None
    stopped = "limite de vueltas alcanzado"
    turn = 0

    # ================= EL BUCLE =================
    while turn < max_turns:
        turn += 1
        resp = client.messages.create(
            model=model, max_tokens=4096, system=SYSTEM, tools=tools.TOOLS, messages=messages
        )
        usage = getattr(resp, "usage", None)
        if usage is not None:
            tr.log("usage", input=getattr(usage, "input_tokens", 0), output=getattr(usage, "output_tokens", 0))

        blocks = _dictify(resp.content)
        for b in blocks:
            if b["type"] == "text" and b["text"].strip():
                tr.log("thinking", turn=turn, text=b["text"])

        calls = [b for b in blocks if b["type"] == "tool_use"]
        messages.append({"role": "assistant", "content": blocks})

        if not calls:
            stopped = "el modelo dejo de pedir herramientas sin entregar conclusion"
            break

        results = []
        for call in calls:
            name, args, cid = call["name"], call["input"] or {}, call["id"]
            tr.log("tool_call", turn=turn, tool=name, args=args)

            # --- guardrail: se revisa ANTES de ejecutar --------------------
            v = guardrails.check(ws, name, args)
            if not v.allowed:
                tr.log("blocked", turn=turn, tool=name, rule=v.rule, reason=v.reason)
                results.append({"type": "tool_result", "tool_use_id": cid,
                                "content": f"RECHAZADO [{v.rule}]: {v.reason}", "is_error": True})
                continue

            try:
                out = tools.execute(ws, name, args)
            except Exception as exc:  # el error vuelve al modelo, no mata el proceso
                tr.log("tool_error", turn=turn, tool=name, error=f"{type(exc).__name__}: {exc}")
                results.append({"type": "tool_result", "tool_use_id": cid,
                                "content": f"ERROR {type(exc).__name__}: {exc}", "is_error": True})
                continue

            if name == tools.TERMINAL_TOOL:
                findings = out
                stopped = "el agente entrego conclusiones"
                tr.log("tool_result", turn=turn, tool=name, summary="conclusiones entregadas")
                tr.log("done", turns=turn)
                messages.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": cid, "content": "Recibido."}]})
                return RunResult(findings, ws, tr.summary(), turn, stopped, messages)

            payload = _shrink(out)
            tr.log("tool_result", turn=turn, tool=name, summary=payload[:400])
            results.append({"type": "tool_result", "tool_use_id": cid, "content": payload})

        messages.append({"role": "user", "content": results})

    tr.log("done", turns=turn)
    return RunResult(findings, ws, tr.summary(), turn, stopped, messages)


# ---------------------------------------------------------------------------
def _real_client():
    import os

    import anthropic

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "Falta ANTHROPIC_API_KEY. Exportala, o corre con --mock para ver el "
            "bucle funcionando sin gastar tokens."
        )
    return anthropic.Anthropic()


# ---------------------------------------------------------------------------
# MODELO SIMULADO
# ---------------------------------------------------------------------------
class _Blk(dict):
    __getattr__ = dict.get


class _Resp:
    def __init__(self, content):
        self.content = content
        self.stop_reason = "tool_use"
        self.usage = None


class _MockModel:
    """
    Un planificador deterministico que ocupa el lugar del modelo.

    Existe por dos razones:
      1. Puedes correr el bucle completo sin API key y sin gastar un peso.
      2. Los tests del bucle no deben depender de una llamada de red. Un test
         que a veces falla porque el modelo cambio de opinion no es un test.

    Comete a proposito un error en el paso 3: intenta clusterizar sin
    estandarizar. Es para que veas al guardrail R4 rechazarlo y al plan
    corregirse solo. Ese ciclo es la demostracion.
    """

    def __init__(self, ws: Workspace):
        self.ws = ws
        self.messages = self
        self.step = 0
        self.tried_unscaled = False

    def create(self, **kw):
        msgs = kw["messages"]
        last = self._last_results(msgs)
        main = next(iter(self.ws.tables))
        work = "entities" if "entities" in self.ws.tables else main
        self.step += 1

        def call(name, args, text):
            return _Resp([_Blk(type="text", text=text),
                          _Blk(type="tool_use", id=f"m{self.step}", name=name, input=args)])

        if self.step == 1:
            return call("inspect_table", {"table": main}, "Primero veo la forma de la tabla.")

        df = self.ws.tables[main]
        needs_agg = len(df) > 1000 and "entities" not in self.ws.tables

        if self.step == 2 and needs_agg:
            return call("aggregate_to_entities", {
                "source": main, "dest": "entities",
                "group_by": ["Brand", "Country"],
                "metrics": {"Revenue_USD": "sum", "Margin_Pct": "mean", "TransactionID": "count"},
                "min_rows_per_group": 20,
                "rationale": ("Marca x pais es la unidad sobre la que un equipo comercial puede "
                              "actuar; el cliente individual no existe en esta tabla."),
            }, "Son transacciones. Hay que colapsar a una fila por entidad.")

        if "entities" in self.ws.tables and "Share_of_Country_Pct" not in self.ws.tables["entities"].columns:
            return call("add_share_of_total", {
                "table": "entities", "value_col": "Revenue_USD_sum",
                "within": "Country", "new_col": "Share_of_Country_Pct",
            }, "Agrego posicion competitiva dentro de cada pais.")

        feats = self._features(work)

        # --- error deliberado: clusterizar sin escalar ---------------------
        if not self.tried_unscaled and work not in self.ws.scaled:
            self.tried_unscaled = True
            return call("sweep_k", {"table": work, "k_min": 2, "k_max": 8},
                        "Barro k para ver donde esta el mejor silhouette.")

        if work not in self.ws.scaled:
            return call("standardize_features", {
                "table": work, "features": feats,
                "rationale": ("Escala, rentabilidad y posicion competitiva son tres ejes distintos. "
                              "Dejo fuera el conteo de transacciones porque duplica la escala."),
            }, "Tienes razon: sin estandarizar la variable de mayor rango decide sola. Escalo.")

        if not any(n.startswith(f"swept:{work}") for n in self.ws.notes):
            return call("sweep_k", {"table": work, "k_min": 2, "k_max": 8},
                        "Ahora si, barro k sobre los datos estandarizados.")

        sweep = self._find(msgs, "structure_detected")
        best_k = int(sweep.get("best_k_by_silhouette", 3)) if sweep else 3
        best_sil = float(sweep.get("best_silhouette", 0)) if sweep else 0.0
        max_gap = float(sweep.get("max_gap_vs_null", 1)) if sweep else 1.0
        strength = sweep.get("structure_strength", "clara") if sweep else "clara"

        if strength == "ninguna":
            return call("submit_findings", {
                "structure_found": False, "chosen_k": 0, "silhouette": round(best_sil, 4),
                "justification": (f"El silhouette llega a {best_sil:.3f} en k={best_k}, pero contra el "
                                  f"modelo nulo el gap es de solo {max_gap:.3f}: los datos no le ganan "
                                  "a su propia version barajada. Ese silhouette es geometria, no "
                                  "estructura. Cualquier corte aqui seria arbitrario."),
                "segments": [],
                "caveats": ("Reportar segmentos aqui seria inventar estructura. Si se necesita "
                            "accionar, conviene traer mas variables antes que forzar clusters."),
            }, f"El gap contra el nulo es {max_gap:.3f}. No hay estructura. Lo reporto asi.")

        if "Cluster" not in self.ws.tables[work].columns:
            return call("fit_segmentation", {
                "table": work, "k": best_k,
                "rationale": f"k={best_k} maximiza el silhouette ({best_sil:.3f}) y son pocos "
                             "segmentos como para que un equipo los pueda operar.",
            }, f"El silhouette manda: k={best_k}.")

        if not any(n.startswith("profiled:") for n in self.ws.notes):
            vcol = "Revenue_USD_sum" if "Revenue_USD_sum" in self.ws.tables[work].columns else "Revenue_USD"
            return call("profile_segments", {"table": work, "value_col": vcol},
                        "Perfilo para ver la desproporcion entre tamano y valor.")

        prof = self._find(msgs, "value_concentration") or {}
        segs = []
        for row in prof.get("value_concentration", []):
            ratio = row["concentration_ratio"]
            vkey = next(k for k in row if k.startswith("pct_of_") and k != "pct_of_entities")
            name = ("Motor de valor" if ratio >= 1.6 else
                    "Cola larga / vigilancia" if ratio <= 0.6 else "Bloque medio")
            segs.append({
                "name": f"{name} (c{row['cluster']})",
                "n_entities": 0,
                "pct_of_entities": row["pct_of_entities"],
                "pct_of_value": row[vkey],
                "profile": f"{row['pct_of_entities']}% de las entidades, {row[vkey]}% del valor "
                           f"(ratio {ratio}).",
                "action": ("Proteger y expandir: aqui esta el negocio." if ratio >= 1.6 else
                           "Consolidar y bajar costo de ejecucion; margen sano con poca escala "
                           "no es motivo de discontinuacion." if ratio <= 0.6 else
                           "Mantener y buscar el gatillo que mueva a estas entidades hacia arriba."),
            })
        caveats = ("Los segmentos describen, no explican: no hay causalidad aqui. Son cortes "
                   "sobre un continuo, y las entidades en la frontera podrian caer del otro "
                   "lado con otra semilla.")
        if strength == "marginal":
            caveats = (f"PARTICION OPERATIVA, no hallazgo. El gap contra el modelo nulo es "
                       f"{max_gap:.3f}: estos datos son un continuo, no grupos naturales. El corte "
                       f"en {best_k} partes sirve para repartir esfuerzo comercial, pero seria "
                       "falso presentarlo como el descubrimiento de segmentos preexistentes. "
                       "Para segmentar de verdad hacen falta mas variables: recencia, frecuencia, "
                       "canal, comportamiento de compra. ") + caveats
        return call("submit_findings", {
            "structure_found": True, "chosen_k": best_k, "silhouette": round(best_sil, 4),
            "justification": (f"k={best_k} maximiza el silhouette ({best_sil:.3f}) en el rango 2-8."
                              + (f" Estructura marginal (gap {max_gap:.3f}): ver caveats."
                                 if strength == "marginal" else "")),
            "segments": segs, "caveats": caveats,
        }, "Cierro con las conclusiones.")

    # -- utilidades del mock ------------------------------------------------
    def _features(self, table):
        import pandas as pd
        df = self.ws.tables[table]
        pref = ["Revenue_USD_sum", "Revenue_USD", "Margin_Pct_mean", "Avg_Margin_Pct",
                "Share_of_Country_Pct"]
        feats = [c for c in pref if c in df.columns]
        if len(feats) < 2:
            feats = [c for c in df.columns
                     if pd.api.types.is_numeric_dtype(df[c]) and not c.startswith("_")][:3]
        return feats[:3]

    def _last_results(self, msgs):
        return msgs[-1] if msgs else None

    def _find(self, msgs, key):
        for m in reversed(msgs):
            if m["role"] != "user" or not isinstance(m["content"], list):
                continue
            for blk in m["content"]:
                c = blk.get("content")
                if isinstance(c, str) and key in c:
                    try:
                        return json.loads(c)
                    except Exception:
                        return None
        return None
