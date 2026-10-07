"""Motor de edición: produce edl.json (fuente única de verdad).

Todo en frames enteros a la tasa de entrega. El timeline de origen es el de los
mics; cada pista de mic va continua y solo se corta por remociones GLOBALES
(aire muerto, muletillas). V1 cambia independiente del audio (J/L-cuts).
Cada unión de audio (remoción) cae exactamente en un corte de video con cambio
de ángulo o de encuadre (punch-in), así no hay jump cuts visibles.
"""
import bisect
import json
import random

import numpy as np
import yaml

from . import cache
from .errors import MappingError
from .sync import CameraClock
from .timecode import parse_rate, sec_to_frame, frame_to_sec

REASONS = ("speaker_change", "monologue_break", "reaction", "filler_hide", "silence_cut", "topic_change",
           "crosstalk_wide", "cold_open")


# ============================================================== mapeo cámaras / mics

def write_mapping_template(paths, ingest, analysis):
    ev = analysis.get("speaker_evidence", {})
    speakers = []
    for i, m in enumerate(ingest["mics"], 1):
        names = ev.get(m["id"], {}).get("probably_named", [])
        speakers.append({"id": f"S{i}", "name": names[0] if len(names) == 1 else "?", "mic": m["id"], "camera": "?"})
    tpl = {"confirmed": False, "speakers": speakers, "wide": ["?"], "exclude_cameras": [], "ignore_mics": [],
           "_cameras": {c["id"]: f"{c['name']} — frame: {ingest['frames'][c['id']]}" for c in ingest["cameras"]},
           "_evidence": ev}
    paths.mapping.write_text(yaml.safe_dump(tpl, allow_unicode=True, sort_keys=False), encoding="utf-8")


def load_mapping(paths, ingest, analysis):
    if not paths.mapping.exists():
        write_mapping_template(paths, ingest, analysis)
        raise MappingError(f"No hay mapeo confirmado. Escribí una propuesta en {paths.mapping}.")
    m = yaml.safe_load(paths.mapping.read_text(encoding="utf-8"))
    if not m.get("confirmed"):
        raise MappingError(f"El mapeo en {paths.mapping} no está confirmado (confirmed: false).")
    cams = {c["id"] for c in ingest["cameras"]}
    mics = {x["id"] for x in ingest["mics"]}
    used_mics = {s["mic"] for s in m["speakers"]} | set(m.get("ignore_mics", []))
    missing = mics - used_mics
    if missing:
        raise MappingError(f"Mics sin mapeo: {sorted(missing)}.")
    bad = [s for s in m["speakers"] if s["mic"] not in mics or (s.get("camera") not in cams | {None, "none"})]
    if bad:
        raise MappingError(f"Hablantes con mic o cámara inexistente: {bad}.")
    wide = [c for c in m.get("wide", []) if c in cams]
    if not wide:
        raise MappingError("No hay cámara 'wide' asignada.")
    used_cams = {s.get("camera") for s in m["speakers"]} | set(wide) | set(m.get("exclude_cameras", []))
    unmapped = cams - used_cams
    if unmapped:
        raise MappingError(f"Cámaras sin rol: {sorted(unmapped)}.")
    return {"speakers": m["speakers"], "wide": wide}


# ============================================================== remociones

def _frames(a, b, fps):
    return sec_to_frame(a, fps, "ceil"), sec_to_frame(b, fps, "floor")


def removal_candidates(analysis, fps, cfg, strict):
    """Rangos de origen [a, b) en frames a quitar, con tipo y prioridad. Devuelve (candidatos, descartados)."""
    dcfg, fcfg = cfg["dead_air"], cfg["fillers"]
    words = analysis["words"]
    w_iv = sorted((w["start"], w["end"]) for w in words)
    w_starts = [x[0] for x in w_iv]
    out, skipped = [], []
    for d in analysis["dead_air"]:
        if d["strict_only"] and not strict(d["start"]):
            continue
        a, b = _frames(d["cut_start"], d["cut_end"], fps)
        if b - a >= 2:
            out.append({"a": a, "b": b, "type": "silence_cut", "priority": d["silence_s"], "src": d})
    for k in analysis["keep_pauses"]:
        # Primer minuto: cero aire muerto -> la pausa KEEP se recorta a first_minute_keep_pause_max_s.
        if strict(k["start"]) and k["silence_s"] > dcfg["first_minute_keep_pause_max_s"]:
            half = dcfg["first_minute_keep_pause_max_s"] / 2
            a, b = _frames(max(k["cut_start"], k["start"] + half), min(k["cut_end"], k["end"] - half), fps)
            if b - a >= 2:
                out.append({"a": a, "b": b, "type": "silence_cut", "priority": k["silence_s"], "src": k,
                            "note": "keep_pause recortada (primer minuto)"})
    guard = dcfg["word_guard_s"]
    ks, ka = fcfg["keep_pause_each_side_s"]
    for f in analysis["fillers"]:
        if not f["removable"]:
            continue
        own = lambda s, e: s >= f["start"] - 1e-6 and e <= f["end"] + 1e-6
        # Vecinas de CUALQUIER mic: el rango nunca puede tapar palabras de otra persona.
        i = bisect.bisect_left(w_starts, f["start"] - 1e-6)
        prev_end = max((e for s, e in w_iv[max(0, i - 50):i] if e <= f["start"] + 1e-6 and not own(s, e)), default=None)
        next_start = next((s for s, e in w_iv[i:] if s >= f["end"] - 1e-6 and not own(s, e)), None)
        gb = f["start"] - prev_end if prev_end is not None else 0.2
        ga = next_start - f["end"] if next_start is not None else 0.2
        lo = f["start"] - gb + min(ks, gb / 2)
        hi = f["end"] + ga - min(ka, ga / 2)
        clash = any(s < hi + guard and e > lo - guard and not own(s, e)
                    for s, e in w_iv[bisect.bisect_left(w_iv, (lo - 2, 0)):bisect.bisect_right(w_iv, (hi + 2, 0))])
        a, b = _frames(lo, hi, fps)
        covers = a <= sec_to_frame(f["start"], fps, "floor") and b >= sec_to_frame(f["end"], fps, "ceil")
        if clash or not covers:
            skipped.append({"a": a, "b": b, "type": "filler_hide", "priority": 0.5, "src": f,
                            "why": "palabra de otro mic en el rango" if clash else "sin espacio a nivel de frame"})
            continue
        out.append({"a": a, "b": b, "type": "filler_hide", "priority": 0.5, "src": f})
    # Unir rangos que se tocan (aire muerto pegado a una muletilla).
    out.sort(key=lambda r: r["a"])
    merged = []
    for r in out:
        if merged and r["a"] <= merged[-1]["b"]:
            m = merged[-1]
            m["b"] = max(m["b"], r["b"])
            if r["type"] == "silence_cut":
                m["type"] = "silence_cut"
            m["priority"] = max(m["priority"], r["priority"])
            m.setdefault("merged", []).append(r["type"])
        else:
            merged.append(dict(r))
    return merged, skipped


def accept_removals(cands, seg_a, seg_b, min_gap):
    """Greedy por prioridad: entre dos uniones debe quedar ≥ min_gap frames de material (plano mínimo)."""
    acc, rej = [], []
    for r in sorted(cands, key=lambda r: -r["priority"]):
        if r["a"] - seg_a < min_gap or seg_b - r["b"] < min_gap:
            rej.append({**r, "why": "muy cerca del borde"})
            continue
        if all(r["a"] - x["b"] >= min_gap or x["a"] - r["b"] >= min_gap for x in acc):
            acc.append(r)
        else:
            rej.append({**r, "why": "muy cerca de otra unión (no se puede ocultar sin plano < mínimo)"})
    return sorted(acc, key=lambda r: r["a"]), rej


def kept_pieces(a, b, removals):
    out, cur = [], a
    for r in removals:
        if r["b"] <= a or r["a"] >= b:
            continue
        if r["a"] > cur:
            out.append([cur, r["a"]])
        cur = max(cur, r["b"])
    if cur < b:
        out.append([cur, b])
    return out


# ============================================================== contexto en el grid de grabación

class Grid:
    def __init__(self, analysis, arrays, fps, layout, n_src):
        self.fps, self.hop, self.t0 = fps, analysis["hop_s"], analysis["t0"]
        self.mic_ids = analysis["mic_ids"]
        R = layout["rec_len"]
        self.R = R
        self.src = np.full(R, -1, np.int64)
        self.seg = np.full(R, -1, np.int8)
        for p in layout["pieces"]:
            self.src[p["rec_a"]: p["rec_a"] + p["src_b"] - p["src_a"]] = np.arange(p["src_a"], p["src_b"])
            self.seg[p["rec_a"]: p["rec_a"] + p["src_b"] - p["src_a"]] = 0 if p["segment"] == "cold_open" else 1
        valid = self.src >= 0
        t = np.where(valid, self.src, 0) / float(fps)
        idx = np.clip(np.round((t - self.t0) / self.hop).astype(np.int64), 0, arrays["speech"].shape[1] - 1)
        self.valid = valid
        self.speech = arrays["speech"][:, idx] & valid
        self.db = arrays["db"][:, idx]
        self.db_orig = arrays.get("db_orig", arrays["db"])[:, idx]
        self.raw = arrays["raw"][:, idx] & valid
        # palabras por mic en el grid de grabación
        self.word = np.zeros((len(self.mic_ids), R), bool)
        src_word = np.zeros((len(self.mic_ids), n_src + 1), bool)
        for w in analysis["words"]:
            k = self.mic_ids.index(w["mic"])
            a, b = sec_to_frame(w["start"], fps, "floor"), sec_to_frame(w["end"], fps, "ceil")
            src_word[k, max(0, a): min(n_src, b)] = True
        self.word = src_word[:, np.clip(self.src, 0, n_src)] & valid
        self.xt = np.zeros(R, bool)
        for a, b in analysis["crosstalk"]:
            fa, fb = sec_to_frame(a, fps), sec_to_frame(b, fps)
            self.xt |= (self.src >= fa) & (self.src < fb)

    def rec_of_src(self, src_f, layout, segment="main"):
        for p in layout["pieces"]:
            if p["segment"] == segment and p["src_a"] <= src_f < p["src_b"]:
                return p["rec_a"] + src_f - p["src_a"]
        return None

    def rec_of_sec(self, t, layout, segment="main"):
        return self.rec_of_src(sec_to_frame(t, self.fps), layout, segment)


# ============================================================== planificación de planos

class Planner:
    def __init__(self, cfg, grid, mapping, coverage, rng):
        e = cfg["edit"]
        self.e, self.g, self.rng = e, grid, rng
        fps = grid.fps
        self.F = lambda s: sec_to_frame(s, fps)
        self.min_f = self.F(e["min_shot_s"])
        self.laugh_min_f = self.F(e["reaction_laugh_min_s"])
        self.first_f = self.F(e["first_minute_s"])
        self.spk = mapping["speakers"]
        self.mic_of = {s["id"]: s["mic"] for s in self.spk}
        self.k_of = {s["id"]: grid.mic_ids.index(s["mic"]) for s in self.spk}
        self.cam_of = {s["id"]: s["camera"] for s in self.spk if s.get("camera") not in (None, "none")}
        self.wides = mapping["wide"]
        self.coverage = coverage
        self.zooms = [1.12, 1.14, 1.10]
        self._zi = 0
        self._wi = 0
        self.last_offset = None
        self._alt = 0
        self.last_jl_final = None
        lo, hi = np.percentile(grid.db_orig[grid.speech], [20, 95]) if grid.speech.any() else (-40, -10)
        self.e_lo, self.e_hi = float(lo), float(hi)

    # ---------- vistas
    def close(self, spk, zoom=1.0):
        cam = self.cam_of.get(spk)
        if cam is None:
            return self.wide()
        return {"kind": "close", "spk": spk, "cam": cam, "zoom": zoom}

    def wide(self, other_than=None):
        ws = [w for w in self.wides if w != other_than] or self.wides
        self._wi = (self._wi + 1) % len(ws)
        return {"kind": "wide", "spk": None, "cam": ws[self._wi], "zoom": 1.0}

    def punch(self, spk):
        self._zi = (self._zi + 1) % len(self.zooms)
        return self.close(spk, self.zooms[self._zi])

    @staticmethod
    def same(a, b):
        return a["cam"] == b["cam"] and abs(a["zoom"] - b["zoom"]) < 1e-6

    def alt_view(self, view, speaker, listener, prefer=None):
        """Otra vista distinta de `view` para romper/ocultar. prefer: reaction | punch | wide."""
        opts = []
        if prefer == "reaction" and listener and listener in self.cam_of:
            opts.append(self.close(listener))
        if prefer == "wide":
            opts.append(self.wide(view["cam"] if view["kind"] == "wide" else None))
        if view["kind"] == "close" and view["zoom"] == 1.0:
            opts.append(self.punch(view["spk"]))
        elif view["kind"] == "close":
            opts.append(self.close(view["spk"], 1.0))
        if speaker and speaker in self.cam_of and not (view["kind"] == "close" and view["spk"] == speaker):
            opts.append(self.close(speaker))
        opts.append(self.wide(view["cam"] if view["kind"] == "wide" else None))
        for o in opts:
            if not self.same(o, view):
                return o
        return self.wide()

    # ---------- utilidades de señal
    def active_speaker(self, a, b):
        best, score = None, 0
        for s, k in self.k_of.items():
            v = self.g.speech[k, a:b].sum()
            if v > score:
                best, score = s, v
        return best

    def listener(self, speaker, a, b):
        others = [s for s in self.k_of if s != speaker]
        if not others:
            return None
        return max(others, key=lambda s: self.g.speech[self.k_of[s], max(0, a - 300):b].sum())

    def max_len(self, spk, a, b):
        k = self.k_of.get(spk)
        lo_s, hi_s = self.e["max_shot_s"]
        if k is None or not self.g.speech[k, a:b].any():
            m = hi_s
        else:
            lvl = float(np.mean(self.g.db_orig[k, a:b][self.g.speech[k, a:b]]))
            en = np.clip((lvl - self.e_lo) / max(1e-6, self.e_hi - self.e_lo), 0, 1)
            m = hi_s - (hi_s - lo_s) * en
        if a < self.first_f:
            m = min(m, self.e["first_minute_max_shot_s"])
        return self.F(m)

    def gap_near(self, spk, target, lo, hi, win_s=0.5):
        """Frame más cercano a target, dentro de [lo, hi], donde nadie está a media palabra."""
        if lo >= hi:
            return int(np.clip(target, lo, hi))
        w = self.F(win_s)
        a, b = max(lo, target - w), min(hi, target + w)
        if a >= b:
            return int(np.clip(target, lo, hi))
        free = np.flatnonzero(~self.g.word[:, a:b].any(axis=0))
        if not len(free):
            return int(np.clip(target, lo, hi))
        return int(a + free[np.argmin(np.abs(a + free - target))])

    # ---------- turnos
    def turns(self, a, b):
        g = self.g
        R = b - a
        lab = np.full(R, -1)
        ids = list(self.k_of)
        ks = np.array([self.k_of[s] for s in ids])
        act = g.speech[ks, a:b]
        loud = np.where(act, g.db[ks, a:b], -200)
        anyact = act.any(axis=0)
        lab[anyact] = np.argmax(loud[:, anyact], axis=0)
        lab[g.xt[a:b]] = -2
        # sostener la última etiqueta en silencios
        last = next((x for x in lab if x != -1), 0)
        for i in range(R):
            if lab[i] == -1:
                lab[i] = last
            else:
                last = lab[i]
        runs = []
        i = 0
        while i < R:
            j = i
            while j < R and lab[j] == lab[i]:
                j += 1
            runs.append([int(lab[i]), a + i, a + j])
            i = j
        sw = self.F(self.e["speaker_switch_min_s"])
        bc_max = self.F(self.e["backchannel_max_s"])
        reactions = []
        merged = []
        for r in runs:
            if merged and r[2] - r[1] < sw and r[1] != a:
                if r[0] >= 0 and r[2] - r[1] <= bc_max:
                    reactions.append((ids[r[0]], r[1], r[2]))
                merged[-1][2] = r[2]
            elif merged and merged[-1][0] == r[0]:
                merged[-1][2] = r[2]
            else:
                merged.append(r)
        out = [("X" if r[0] == -2 else ids[r[0]], r[1], r[2]) for r in merged]
        return out, reactions

    # ---------- plan de un segmento
    def plan_segment(self, a, b, first_reason, joins, topics, laughs):
        turns, backch = self.turns(a, b)
        shots = []
        for lab, s, e in turns:
            if lab == "X":
                view, reason = self.wide(), "crosstalk_wide"
            else:
                view, reason = self.close(lab), "speaker_change"
            if shots and self.same(shots[-1]["view"], view):
                shots[-1]["end"] = e
                continue
            shots.append({"start": s, "end": e, "view": view, "reason": reason, "turn_b": s, "spk": lab})
        if not shots:
            shots = [{"start": a, "end": b, "view": self.wide(), "reason": first_reason, "turn_b": a, "spk": None}]
        shots[0]["reason"] = first_reason
        self.apply_jl(shots)
        for t in topics:
            if a + self.min_f <= t < b - self.min_f:
                L = self.F(self.rng.uniform(*self.e["wide_reestablish_s"]))
                self.overlay(shots, t, min(b, t + L), self.wide(), "topic_change")
        for spk, s, e in laughs:
            sh = self.at(shots, s)
            if sh is None or sh["view"].get("spk") == spk or spk not in self.cam_of:
                continue
            L = max(self.laugh_min_f, min(e - s, self.F(self.e["reaction_len_s"][1])))
            self.overlay(shots, s, min(b, s + L), self.close(spk), "reaction",
                         exception="reaction_laugh" if L < self.min_f else None)
        self.break_monologues(shots, backch)
        self.enforce_joins(shots, joins, a, b)
        self.normalize(shots, set(joins) | {a, b})
        self.fix_jl(shots, set(joins) | {a, b})
        return shots

    def fix_jl(self, shots, locked):
        """Recalcula offsets reales contra el cambio de turno y evita repetir el mismo dos veces seguidas."""
        prev = self.last_jl_final
        for i in range(1, len(shots)):
            o = shots[i].get("offset")
            if not o or o.get("type") not in ("J", "L"):
                continue
            o["frames"] = shots[i]["start"] - o["turn_b"]
            jr, lr = self.e["j_cut_frames"], self.e["l_cut_frames"]
            valid = (jr[0] <= o["frames"] <= jr[1]) or (lr[0] <= -o["frames"] <= lr[1])
            if not valid or shots[i]["start"] in locked:
                o["type"] = "none"
                continue
            o["type"] = "J" if o["frames"] > 0 else "L"
            if o["frames"] == prev:
                for d in (1, -1, 2, -2):
                    nf = o["frames"] + d
                    ok_rng = (jr[0] <= nf <= jr[1]) or (lr[0] <= -nf <= lr[1])
                    new = o["turn_b"] + nf
                    if ok_rng and new - shots[i - 1]["start"] >= self.min_f and shots[i]["end"] - new >= self.min_f:
                        shots[i - 1]["end"] = shots[i]["start"] = new
                        o["frames"] = nf
                        break
            prev = o["frames"]
        self.last_jl_final = prev

    def at(self, shots, r):
        for sh in shots:
            if sh["start"] <= r < sh["end"]:
                return sh
        return None

    def apply_jl(self, shots):
        jr, lr = self.e["j_cut_frames"], self.e["l_cut_frames"]
        for i in range(1, len(shots)):
            p, c = shots[i - 1], shots[i]
            if c["reason"] != "speaker_change" or p["view"]["kind"] != "close" or c["view"]["kind"] != "close":
                continue
            b = c["start"]
            for _ in range(8):
                kind = self.rng.choice(["J", "L"])
                off = self.rng.randint(*jr) if kind == "J" else -self.rng.randint(*lr)
                if off != self.last_offset:
                    break
            new = b + off
            if new - p["start"] >= self.min_f and c["end"] - new >= self.min_f:
                p["end"] = c["start"] = new
                c["offset"] = {"type": kind, "frames": off, "turn_b": b}
                self.last_offset = off
            else:
                c["offset"] = {"type": "none", "frames": 0}

    def overlay(self, shots, a, b, view, reason, exception=None):
        """Inserta [a, b) con `view`, partiendo lo que haya debajo."""
        if b <= a:
            return
        out = []
        for sh in shots:
            if sh["end"] <= a or sh["start"] >= b:
                out.append(sh)
                continue
            if sh["start"] < a:
                out.append({**sh, "end": a})
            if sh["end"] > b:
                out.append({**sh, "start": b, "reason": "monologue_break", "offset": None})
        out.append({"start": a, "end": b, "view": view, "reason": reason, "exception": exception,
                    "spk": view.get("spk")})
        out.sort(key=lambda s: s["start"])
        shots[:] = out

    def break_monologues(self, shots, backch):
        out = []
        for sh in shots:
            v = sh["view"]
            spk = v.get("spk") or sh.get("spk")
            if v["kind"] != "close" or sh.get("exception") or sh["reason"] == "reaction":
                out.append(sh)
                continue
            mx = self.max_len(spk, sh["start"], sh["end"])
            if sh["end"] - sh["start"] <= mx:
                out.append(sh)
                continue
            pos, base, n = sh["start"], v, 0
            listener = self.listener(spk, sh["start"], sh["end"])
            cur = dict(sh)
            while sh["end"] - pos > mx:
                hi_cut = sh["end"] - self.min_f
                target = pos + int(self.rng.uniform(0.6, 1.0) * mx)
                cut = self.gap_near(spk, target, pos + self.min_f, min(hi_cut, pos + mx))
                if cut <= pos or cut >= sh["end"]:
                    break
                cur["end"] = cut
                out.append(cur)
                n += 1
                has_bc = any(cut <= s < cut + mx for (_, s, _) in backch)
                if n % 2 == 1:
                    cycle = ("reaction", "punch", "wide", "punch")
                    prefer = "reaction" if has_bc else cycle[self._alt % len(cycle)]
                    self._alt += 1
                    nv = self.alt_view(base, spk, listener, prefer)
                    reason = "reaction" if nv["kind"] == "close" and nv["spk"] == listener else "monologue_break"
                else:
                    nv, reason = base, "monologue_break"
                cur = {"start": cut, "end": sh["end"], "view": nv, "reason": reason, "spk": spk}
                pos = cut
                if reason == "reaction":
                    L = self.F(self.rng.uniform(*self.e["reaction_len_s"]))
                    if sh["end"] - (cut + L) >= self.min_f:
                        cur["end"] = cut + L
                        out.append(cur)
                        n += 1
                        cur = {"start": cut + L, "end": sh["end"], "view": base, "reason": "monologue_break",
                               "spk": spk}
                        pos = cut + L
            out.append(cur)
        shots[:] = out

    def enforce_joins(self, shots, joins, a, b):
        snap = self.e["join_snap_frames"]
        jset = set(joins)
        for j in joins:
            cuts = [s["start"] for s in shots[1:]]
            if j in cuts:
                continue
            # 1) mover un corte cercano a la unión
            moved = False
            for i in sorted(range(1, len(shots)), key=lambda i: abs(shots[i]["start"] - j)):
                c = shots[i]["start"]
                if abs(c - j) > snap or c in jset:
                    break
                p, n = shots[i - 1], shots[i]
                if j - p["start"] >= self.min_f and n["end"] - j >= self.min_f:
                    p["end"] = n["start"] = j
                    n["join_moved_from"] = c
                    moved = True
                    break
            if moved:
                continue
            # 2) partir el plano que contiene la unión
            idx = next(i for i, s in enumerate(shots) if s["start"] < j < s["end"])
            sh = shots[idx]
            spk = sh["view"].get("spk") or self.active_speaker(j, min(b, j + self.min_f))
            nv = self.alt_view(sh["view"], spk, self.listener(spk, j, j + self.min_f) if spk else None)
            if j - sh["start"] < self.min_f and idx > 0 and sh["start"] not in jset:
                shots[idx - 1]["end"] = j      # el anterior se alarga hasta la unión
                sh["start"] = j
                if self.same(shots[idx - 1]["view"], sh["view"]):
                    sh["view"] = nv
                continue
            if sh["end"] - j < self.min_f and idx + 1 < len(shots) and sh["end"] not in jset:
                shots[idx + 1]["start"] = j    # el siguiente empieza antes
                sh["end"] = j
                if self.same(shots[idx + 1]["view"], sh["view"]):
                    shots[idx + 1]["view"] = nv
                continue
            shots.insert(idx + 1, {"start": j, "end": sh["end"], "view": nv, "reason": "filler_hide", "spk": spk})
            sh["end"] = j

    def normalize(self, shots, locked):
        for _ in range(30):
            changed = False
            # a) vistas iguales contiguas
            i = 1
            while i < len(shots):
                p, c = shots[i - 1], shots[i]
                if self.same(p["view"], c["view"]):
                    if c["start"] in locked:
                        spk = c["view"].get("spk") or self.active_speaker(c["start"], c["end"])
                        c["view"] = self.alt_view(c["view"], spk, self.listener(spk, c["start"], c["end"]) if spk else None)
                    else:
                        p["end"] = c["end"]
                        if c.get("exception") and not p.get("exception"):
                            p["exception"] = None
                        shots.pop(i)
                        changed = True
                        continue
                i += 1
            # b) planos cortos
            i = 0
            while i < len(shots):
                sh = shots[i]
                L = sh["end"] - sh["start"]
                lim = self.laugh_min_f if sh.get("exception") == "reaction_laugh" else self.min_f
                if L < lim and len(shots) > 1:
                    can_prev = i > 0 and sh["start"] not in locked
                    can_next = i + 1 < len(shots) and sh["end"] not in locked
                    if can_prev and (not can_next or shots[i - 1]["end"] - shots[i - 1]["start"] >=
                                     shots[i + 1]["end"] - shots[i + 1]["start"]):
                        shots[i - 1]["end"] = sh["end"]
                        shots.pop(i)
                        changed = True
                        continue
                    if can_next:
                        shots[i + 1]["start"] = sh["start"]
                        if sh["start"] in locked:
                            shots[i + 1]["reason"] = sh["reason"]
                        shots.pop(i)
                        changed = True
                        continue
                i += 1
            # c) planos largos
            i = 0
            while i < len(shots):
                sh = shots[i]
                spk = sh["view"].get("spk") or self.active_speaker(sh["start"], sh["end"])
                mx = self.max_len(spk, sh["start"], sh["end"])
                if sh["end"] - sh["start"] > mx and sh["end"] - sh["start"] >= 2 * self.min_f:
                    mid = (sh["start"] + sh["end"]) // 2
                    cut = self.gap_near(spk, mid, sh["start"] + self.min_f, sh["end"] - self.min_f)
                    nv = self.alt_view(sh["view"], spk, self.listener(spk, sh["start"], sh["end"]) if spk else None)
                    shots.insert(i + 1, {"start": cut, "end": sh["end"], "view": nv, "reason": "monologue_break",
                                         "spk": spk})
                    sh["end"] = cut
                    changed = True
                i += 1
            if not changed:
                break


# ============================================================== etapa

def build_layout(fps, main_a, main_b, removals, cold_open, sting_f, min_f):
    pieces, rec = [], 0
    co = None
    if cold_open:
        ca, cb = cold_open
        # el cold open no puede empezar/terminar dentro de una remoción
        for r in removals:
            if r["a"] < ca < r["b"]:
                ca = r["b"]
            if r["a"] < cb < r["b"]:
                cb = r["a"]
        cps = [p for p in kept_pieces(ca, cb, removals) if p[1] - p[0] >= min_f]
        if cps:
            co = (cps[0][0], cps[-1][1])
            for a, b in cps:
                pieces.append({"segment": "cold_open", "src_a": a, "src_b": b, "rec_a": rec})
                rec += b - a
    sting = None
    if pieces:
        sting = (rec, rec + sting_f)
        rec += sting_f
    main_rec_a = rec
    for a, b in kept_pieces(main_a, main_b, removals):
        pieces.append({"segment": "main", "src_a": a, "src_b": b, "rec_a": rec})
        rec += b - a
    return {"pieces": pieces, "rec_len": rec, "sting": sting, "cold_open_src": co, "main_rec_a": main_rec_a}


def choose_cold_open(clips, sents, cfg):
    lo, hi = cfg["cold_open"]["length_s"]
    for c in clips:
        if c["duration"] <= hi and c["duration"] >= lo:
            return c["start"], c["end"], c
        ends = [s["end"] for s in sents if c["start"] + lo <= s["end"] <= c["start"] + hi]
        if ends:
            return c["start"], max(ends), c
    return None


def run_edit(paths, cfg, ingest, sync, audio, analysis, arrays, viral, force=False):
    mapping = load_mapping(paths, ingest, analysis)
    h = cache.input_hash("edit", cache.code_hash("edit_engine", "timecode"), [cache.stage_hash(paths.cache, s) for s in ("sync", "audio", "analyze", "viral")],
                         {k: cfg[k] for k in ("edit", "cold_open", "dead_air", "fillers", "broll", "markers")}, mapping)
    cached = None if force else cache.load(paths.cache, "edit", h)
    if cached:
        return cached, True

    fps = parse_rate(ingest["delivery"]["fps"])
    F = lambda s: sec_to_frame(s, fps)
    e = cfg["edit"]
    min_f = F(e["min_shot_s"])
    rng = random.Random(e["seed"])
    words = analysis["words"]
    t0, t_end = analysis["t0"], analysis["t_end"]
    main_a = F(max(t0, (words[0]["start"] - 0.3) if words else t0))
    main_b = F(min(t_end, (words[-1]["end"] + 0.8) if words else t_end))
    n_src = F(t_end) + 1

    co = choose_cold_open(viral["clips"], analysis["sentences"], cfg) if cfg["cold_open"]["enabled"] else None
    co_len = (co[1] - co[0]) if co else 0
    sting_f = F(cfg["cold_open"]["sting_s"]) if co else 0
    strict_until = frame_to_sec(main_a, fps) + max(0.0, e["first_minute_s"] - co_len - cfg["cold_open"]["sting_s"]) + 15
    co_rng = (co[0], co[1]) if co else (0.0, -1.0)
    cands, skipped = removal_candidates(analysis, fps, cfg,
                                        lambda t: t < strict_until or co_rng[0] - 0.5 <= t < co_rng[1])
    removals, rejected = accept_removals(cands, main_a, main_b, min_f)
    rejected += skipped
    layout = build_layout(fps, main_a, main_b, removals, (F(co[0]), F(co[1])) if co else None, sting_f, min_f)

    grid = Grid(analysis, arrays, fps, layout, n_src)
    clocks = {cid: CameraClock(s) for cid, s in sync["cameras"].items()}
    coverage = {cid: s["mic_coverage_s"] for cid, s in sync["cameras"].items()}
    planner = Planner(cfg, grid, mapping, coverage, rng)

    # uniones (cada inicio de pieza que no sea inicio de segmento) y su tipo
    joins_by_seg = {"cold_open": [], "main": []}
    join_type = {}
    for i, p in enumerate(layout["pieces"]):
        prev = layout["pieces"][i - 1] if i else None
        if prev and prev["segment"] == p["segment"]:
            joins_by_seg[p["segment"]].append(p["rec_a"])
            r = next((r for r in removals if r["a"] == prev["src_b"]), None)
            join_type[p["rec_a"]] = r["type"] if r else "silence_cut"

    def seg_bounds(name):
        ps = [p for p in layout["pieces"] if p["segment"] == name]
        return (ps[0]["rec_a"], ps[-1]["rec_a"] + ps[-1]["src_b"] - ps[-1]["src_a"]) if ps else None

    def laughs_in(a, b, seg):
        out = []
        for l in analysis["laughter"]:
            r = grid.rec_of_sec(l["start"], layout, seg)
            r2 = grid.rec_of_sec(l["end"], layout, seg)
            spk = next((s["id"] for s in mapping["speakers"] if s["mic"] == l["mic"]), None)
            if r is not None and spk and a <= r < b:
                out.append((spk, r, r2 if r2 is not None else r + F(1.0)))
        return out

    shots = []
    for seg, reason in (("cold_open", "cold_open"), ("main", "cold_open" if layout["sting"] else "speaker_change")):
        bnd = seg_bounds(seg)
        if not bnd:
            continue
        topics = [] if seg == "cold_open" else [r for r in (grid.rec_of_sec(t["time"], layout) for t in analysis["topics"])
                                                if r is not None]
        seg_shots = planner.plan_segment(bnd[0], bnd[1], reason, joins_by_seg[seg], topics, laughs_in(*bnd, seg))
        for sh in seg_shots:
            sh["segment"] = seg
        shots += seg_shots

    # Razón de los cortes en uniones = la remoción que ocultan (la original queda en `also`).
    for sh in shots:
        if sh["start"] in join_type:
            if sh["reason"] != join_type[sh["start"]]:
                sh["also"] = sh["reason"]
            sh["reason"] = join_type[sh["start"]]

    # Cobertura de cámaras: si la cámara no cubre el tramo, se cae a una que sí.
    cams = {c["id"]: c for c in ingest["cameras"]}
    piece_starts = [p["rec_a"] for p in layout["pieces"]]
    video = []
    warnings = []
    for i, sh in enumerate(shots):
        pi = bisect.bisect_right(piece_starts, sh["start"]) - 1
        p = layout["pieces"][pi]
        if sh["end"] > p["rec_a"] + p["src_b"] - p["src_a"]:
            warnings.append(f"Plano {i} cruza una unión (defecto).")
        src_a = p["src_a"] + sh["start"] - p["rec_a"]
        length = sh["end"] - sh["start"]
        t_a, t_b = frame_to_sec(src_a, fps), frame_to_sec(src_a + length, fps)
        cam = sh["view"]["cam"]
        cov = coverage[cam]
        if not (cov[0] <= t_a and t_b <= cov[1]):
            alt = next((c for c in mapping["wide"] + list(cams) if coverage[c][0] <= t_a and t_b <= coverage[c][1]), None)
            if alt is None:
                warnings.append(f"Ninguna cámara cubre {t_a:.1f}–{t_b:.1f} s.")
                alt = cam
            sh["view"] = {**sh["view"], "cam": alt, "kind": "wide" if alt in mapping["wide"] else sh["view"]["kind"],
                          "zoom": 1.0}
            sh["coverage_fallback"] = cam
        cfps = parse_rate(cams[sh["view"]["cam"]]["fps"])
        cam_in = sec_to_frame(clocks[sh["view"]["cam"]].cam_time(t_a), cfps)
        cam_len = length if cfps == fps else sec_to_frame(frame_to_sec(length, fps), cfps)
        video.append({
            "id": i, "rec_start_f": sh["start"], "rec_end_f": sh["end"], "camera": sh["view"]["cam"],
            "file": cams[sh["view"]["cam"]]["path"], "src_in_f": cam_in, "src_out_f": cam_in + cam_len,
            "mic_src_f": src_a, "zoom": sh["view"]["zoom"], "pan": 0.0, "tilt": 0.0,
            "view": f"{sh['view']['kind']}:{sh['view'].get('spk') or sh['view']['cam']}",
            "reason": sh["reason"], "also": sh.get("also"), "exception": sh.get("exception"),
            "offset": sh.get("offset"), "segment": sh["segment"],
        })

    audio_tracks = []
    for ti, m in enumerate(analysis["mic_ids"], 1):
        audio_tracks.append({"track": ti, "mic": m, "file": audio["tracks"][m],
                             "speaker": next((s["name"] for s in mapping["speakers"] if s["mic"] == m), m),
                             "clips": [{"src_start_f": p["src_a"], "src_end_f": p["src_b"], "rec_start_f": p["rec_a"]}
                                       for p in layout["pieces"]]})

    markers = build_markers(cfg, grid, layout, analysis, viral, sync, rejected, fps)
    edl = {
        "version": 1, "episode": paths.episode,
        "fps": {"rate": f"{fps.numerator}/{fps.denominator}", "drop_frame": ingest["delivery"]["drop_frame"]},
        "resolution": [ingest["delivery"]["width"], ingest["delivery"]["height"]],
        "record_duration_f": layout["rec_len"], "source_range_f": [main_a, main_b],
        "cold_open": {"src": layout["cold_open_src"], "clip_rank": co[2]["rank"] if co else None},
        "sting": {"rec_start_f": layout["sting"][0], "rec_end_f": layout["sting"][1],
                  "path": cfg["cold_open"]["sting_path"]} if layout["sting"] else None,
        "pieces": layout["pieces"],
        "removals": [{"src_start_f": r["a"], "src_end_f": r["b"], "type": r["type"],
                      "text": r["src"].get("text"), "merged": r.get("merged"), "note": r.get("note")} for r in removals],
        "rejected_removals": [{"src_start_f": r["a"], "src_end_f": r["b"], "type": r["type"], "why": r["why"]}
                              for r in rejected],
        "joins": sorted(join_type), "video_track": {"track": 1, "shots": video},
        "audio_tracks": audio_tracks, "markers": markers, "mapping": mapping, "warnings": warnings,
    }
    edl["qc"] = qc(edl, analysis, grid, cfg, fps)
    (paths.out / "edl.json").write_text(json.dumps(edl, ensure_ascii=False, indent=1, default=cache._default),
                                        encoding="utf-8")
    cache.save(paths.cache, "edit", h, edl)
    return edl, False


# ============================================================== marcadores

def build_markers(cfg, grid, layout, analysis, viral, sync, rejected, fps):
    mc = cfg["markers"]
    F = lambda s: sec_to_frame(s, fps)
    out = []

    def add(r, color, name, note="", dur=1):
        if r is None:
            return
        while any(m["rec_f"] == r for m in out):
            r += 1
        out.append({"rec_f": int(r), "color": color, "name": name[:80], "note": note[:400], "duration_f": int(max(1, dur))})

    for c in viral["clips"]:
        r0, r1 = grid.rec_of_sec(c["start"], layout), grid.rec_of_sec(c["end"] - 0.05, layout)
        add(r0, mc["viral"], c["hook"], f"score={c['score']} {json.dumps(c['breakdown'], default=cache._default)}",
            (r1 - r0) if (r0 is not None and r1 is not None) else 1)
    for k in analysis["keep_pauses"]:
        add(grid.rec_of_sec(k["start"], layout), mc["keep_pause"], f"KEEP_PAUSE ({k['reason']})",
            f"{k['silence_s']:.2f} s")
    for t in analysis["topics"]:
        add(grid.rec_of_sec(t["time"], layout), mc["topic"], "Cambio de tema", t.get("text", ""))
    for cid, s in sync["cameras"].items():
        for p in s["points"]:
            if not p.get("ok"):
                add(grid.rec_of_sec(p["cam_t"] + s["offset_s"], layout), mc["sync"], f"Sync dudoso {cid}",
                    f"corr={p['corr']:.2f}")
        if s["model"] != "linear":
            add(layout["main_rec_a"], mc["sync"], f"Sync por tramos {cid}", "deriva no lineal")
    for r in rejected:
        if r["type"] == "silence_cut" and (r["b"] - r["a"]) >= F(1.5):
            add(grid.rec_of_src(r["a"], layout), mc["review"], "Revisar: silencio no cortado", r["why"])
    if layout["sting"]:
        add(layout["sting"][0], mc["review"], "STING", "placeholder de sting", layout["sting"][1] - layout["sting"][0])

    # B-roll / lower-third cada 45–90 s.
    bmin, bmax = F(cfg["broll"]["min_gap_s"]), F(cfg["broll"]["max_gap_s"])
    ments = sorted([(grid.rec_of_sec(m["time"], layout), m) for m in analysis["mentions"]
                    if grid.rec_of_sec(m["time"], layout) is not None], key=lambda x: x[0])
    sents = sorted([r for r in (grid.rec_of_sec(s["start"], layout) for s in analysis["sentences"]) if r is not None])
    last, seen, mi = layout["main_rec_a"], set(), 0
    end = layout["rec_len"]
    while last + bmin < end:
        cand = [(r, m) for r, m in ments[mi:] if last + bmin <= r <= last + bmax]
        if cand:
            fresh = [c for c in cand if c[1]["text"] not in seen] or cand
            r, m = fresh[0]
            kind = "lower-third" if m["kind"].startswith("persona") and m["text"] not in seen else "B-roll"
            add(r, mc["broll"], f"{kind}: {m['text']}", m["kind"])
            seen.add(m["text"])
            last = r
            mi = next((i for i, (rr, _) in enumerate(ments) if rr > r), len(ments))
        else:
            target = last + (bmin + bmax) // 2
            opts = [r for r in sents if last + bmin <= r <= last + bmax]
            if not opts:
                if last + bmax >= end:
                    break
                r = last + bmax
            else:
                r = min(opts, key=lambda x: abs(x - target))
            add(r, mc["broll"], "B-roll libre", "pattern interrupt")
            last = r
    return sorted(out, key=lambda m: m["rec_f"])


# ============================================================== QC

def qc(edl, analysis, grid, cfg, fps):
    e = cfg["edit"]
    F = lambda s: sec_to_frame(s, fps)
    shots = edl["video_track"]["shots"]
    lens = np.array([s["rec_end_f"] - s["rec_start_f"] for s in shots])
    first_f = F(e["first_minute_s"])
    viol_long, viol_short = [], []
    for s, L in zip(shots, lens):
        mx = F(e["first_minute_max_shot_s"]) if s["rec_start_f"] < first_f else F(e["max_shot_s"][1])
        if L > mx and not s["exception"]:
            viol_long.append(s["id"])
        lim = F(e["reaction_laugh_min_s"]) if s["exception"] == "reaction_laugh" else F(e["min_shot_s"])
        if L < lim:
            viol_short.append(s["id"])
    # Uniones ocultas: debe haber un corte exacto con cambio de cámara o de zoom.
    starts = {s["rec_start_f"]: i for i, s in enumerate(shots)}
    hidden, unhidden = 0, []
    for j in edl["joins"]:
        i = starts.get(j)
        if i is not None and i > 0 and (shots[i]["camera"] != shots[i - 1]["camera"] or
                                         abs(shots[i]["zoom"] - shots[i - 1]["zoom"]) > 1e-6):
            hidden += 1
        else:
            unhidden.append(j)
    # Cortes dentro de palabras: ninguna remoción puede solapar una palabra.
    w = [(sec_to_frame(x["start"], fps, "floor"), sec_to_frame(x["end"], fps, "ceil"), x["text"])
         for x in analysis["words"]]
    inside = []
    for r in edl["removals"]:
        for a, b, t in w:
            is_removed_filler = r["type"] == "filler_hide" and a >= r["src_start_f"] and b <= r["src_end_f"]
            if a < r["src_end_f"] and b > r["src_start_f"] and not is_removed_filler:
                if r.get("merged") and a >= r["src_start_f"] and b <= r["src_end_f"]:
                    continue  # muletilla dentro de una remoción combinada
                inside.append((r["src_start_f"], t))
    # J/L: nunca el mismo offset dos veces seguidas.
    offs = [s["offset"]["frames"] for s in shots if s.get("offset") and s["offset"]["type"] in ("J", "L")]
    repeats = sum(1 for a, b in zip(offs, offs[1:]) if a == b)
    # Primer minuto: silencios residuales > umbral.
    R = min(grid.R, first_f)
    silent = ~grid.raw[:, :R].any(axis=0) & grid.valid[:R]
    runs, cur = [], 0
    for v in silent:
        cur = cur + 1 if v else 0
        runs.append(cur)
    first_min_dead = int(sum(1 for i in range(1, len(runs)) if runs[i] == 0 and runs[i - 1] > F(cfg["dead_air"]["min_silence_s"])))
    rm_fillers = [f for f in analysis["fillers"] if f["removable"]]
    removed = [f for f in rm_fillers if any(r["src_start_f"] <= sec_to_frame(f["start"], fps, "floor") and
                                            r["src_end_f"] >= sec_to_frame(f["end"], fps, "ceil")
                                            for r in edl["removals"])]
    reasons = {}
    for s in shots[1:]:
        reasons[s["reason"]] = reasons.get(s["reason"], 0) + 1
    src_len = edl["source_range_f"][1] - edl["source_range_f"][0]
    return {
        "shot_count": len(shots), "avg_shot_s": round(float(lens.mean()) / float(fps), 2),
        "max_shot_s": round(float(lens.max()) / float(fps), 2), "min_shot_s": round(float(lens.min()) / float(fps), 2),
        "shots_too_long": viol_long, "shots_too_short": viol_short,
        "exceptions": sum(1 for s in shots if s["exception"]),
        "cuts_by_reason": dict(sorted(reasons.items())),
        "removals": len(edl["removals"]), "rejected_removals": len(edl["rejected_removals"]),
        "fillers_removable": len(rm_fillers), "fillers_removed": len(removed),
        "joins_total": len(edl["joins"]), "joins_hidden": hidden, "joins_unhidden": unhidden,
        "cuts_inside_words": inside, "jl_offsets": len(offs), "jl_consecutive_repeats": repeats,
        "first_minute_dead_air": first_min_dead,
        "runtime_source_s": round(src_len / float(fps), 2),
        "runtime_main_s": round(sum(p["src_b"] - p["src_a"] for p in edl["pieces"] if p["segment"] == "main") / float(fps), 2),
        "runtime_record_s": round(edl["record_duration_f"] / float(fps), 2),
        "markers_by_color": {c: sum(1 for m in edl["markers"] if m["color"] == c)
                             for c in sorted({m["color"] for m in edl["markers"]})},
    }
