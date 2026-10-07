"""Puntaje de clips virales (ventanas de 20–90 s ajustadas a frases).

Componentes: energía (picos de RMS), varianza de tono (librosa pyin), risas,
cambios de ritmo del habla y un puntaje semántico. El semántico lo asigna
Claude leyendo la transcripción: viral_candidates.json -> semantic_scores.json.
Si ese archivo no existe se usa una heurística (gancho en los primeros 3 s,
historia cerrada, frase polarizante, remate, frase citable) y se avisa.
"""
import json
import re

import numpy as np

from . import cache, media
from .analyze import strip_accents, norm_token, LAUGH_RE

POLAR = ["nunca", "jamás", "siempre", "nadie", "todos", "odio", "mentira", "verdad", "error", "peor", "mejor",
         "miedo", "dinero", "secreto", "increíble", "absurdo", "polémico", "no es cierto", "la neta"]


def _rank(x):
    x = np.asarray(x, float)
    if len(x) < 2 or np.ptp(x) == 0:
        return np.zeros_like(x)
    return np.argsort(np.argsort(x)) / (len(x) - 1)


def mix_level(db):
    return 10 * np.log10(np.sum(10 ** (db / 10), axis=0) + 1e-12)


def candidates(sents, vcfg):
    lo, hi = vcfg["window_s"]
    starts = [s for s in sents]
    ends = sorted(sents, key=lambda s: s["end"])
    out = []
    j0 = 0
    for s in starts:
        while j0 < len(ends) and ends[j0]["end"] < s["start"] + lo:
            j0 += 1
        j = j0
        while j < len(ends) and ends[j]["end"] <= s["start"] + hi:
            out.append((s["start"], ends[j]["end"]))
            j += 1
    return sorted(set(out))


def heuristic_semantic(text_first3, text, laugh_near_end, hook_words):
    low = strip_accents(text.lower())
    first = strip_accents(text_first3.lower())
    hooks = [strip_accents(h) for h in hook_words]
    s_hook = min(1.0, sum(h in first for h in hooks) * 0.5 + ("?" in text_first3) * 0.3
                 + bool(re.search(r"\d", text_first3)) * 0.3)
    s_polar = min(1.0, sum(strip_accents(p) in low for p in POLAR) / 4)
    s_punch = 1.0 if laugh_near_end else 0.0
    sentences = re.split(r"(?<=[.?!])\s+", text)
    quotable = any(5 <= len(s.split()) <= 14 and any(h in strip_accents(s.lower()) for h in hooks) for s in sentences)
    s_story = 1.0 if text.rstrip().endswith((".", "!", "?")) else 0.5
    parts = {"hook": s_hook, "polar": s_polar, "punchline": s_punch, "quotable": float(quotable), "story": s_story}
    return 0.35 * s_hook + 0.2 * s_polar + 0.2 * s_punch + 0.15 * float(quotable) + 0.1 * s_story, parts


def speaker_pitch(tracks, speech, hop_s, t0, t1, sr=8000, hop=160, chunk_s=60.0):
    """pyin por mic, solo donde ese mic domina, en semitonos respecto a la mediana del hablante.

    Devuelve (tiempos ordenados, valores) de todo el tramo: la varianza mide
    expresividad de cada voz, no la alternancia entre una voz grave y una aguda.
    """
    import librosa
    times, vals = [], []
    for k, path in enumerate(tracks):
        tt, vv = [], []
        for a in np.arange(t0, t1, chunk_s):
            x = media.decode_audio(path, sr, a, min(chunk_s, t1 - a))
            if len(x) < sr // 2:
                continue
            f0, voiced, _ = librosa.pyin(x, fmin=65, fmax=500, sr=sr, frame_length=1024, hop_length=hop,
                                         n_thresholds=30)
            ft = a + np.arange(len(f0)) * hop / sr
            idx = np.clip(((ft - t0) / hop_s).astype(int), 0, speech.shape[1] - 1)
            ok = voiced & np.isfinite(f0) & speech[k, idx]
            tt.append(ft[ok])
            vv.append(12 * np.log2(f0[ok]))
        if tt and sum(len(x) for x in tt):
            v = np.concatenate(vv)
            times.append(np.concatenate(tt))
            vals.append(v - np.median(v))
    if not times:
        return np.zeros(0), np.zeros(0)
    t = np.concatenate(times)
    order = np.argsort(t)
    return t[order], np.concatenate(vals)[order]


class WindowStd:
    """Desviación estándar en cualquier ventana con sumas prefijo."""

    def __init__(self, t, v):
        self.t = t
        self.c1 = np.concatenate([[0], np.cumsum(v)])
        self.c2 = np.concatenate([[0], np.cumsum(v * v)])

    def __call__(self, a, b):
        i, j = np.searchsorted(self.t, a), np.searchsorted(self.t, b)
        n = j - i
        if n < 10:
            return 0.0
        m = (self.c1[j] - self.c1[i]) / n
        return float(np.sqrt(max(0.0, (self.c2[j] - self.c2[i]) / n - m * m)))


def clean_text(text, filler_words):
    """Quita muletillas sueltas al inicio y en medio (para ganchos y títulos)."""
    toks = text.split()
    singles = {f for f in filler_words if " " not in f}
    out = [t for t in toks if norm_token(t) not in singles and not re.fullmatch(r"e+h+|m{2,}h*", norm_token(t))]
    t = " ".join(out)
    return re.sub(r"^o sea,?\s+", "", t, flags=re.I)


def title_from(hook):
    first = re.split(r"[,.;:?!]", hook.strip("¿¡ "))[0].split()
    t = " ".join(first[:8])
    return (t[:1].upper() + t[1:]) if t else hook[:60]


def run_viral(paths, cfg, analysis, arrays, audio, force=False):
    vcfg = cfg["viral"]
    sem_path = paths.out / "semantic_scores.json"
    sem = json.loads(sem_path.read_text(encoding="utf-8")) if sem_path.exists() else None
    h = cache.input_hash("viral", cache.code_hash("viral"), cache.stage_hash(paths.cache, "analyze"), vcfg, sem)
    cached = None if force else cache.load(paths.cache, "viral", h)
    if cached:
        return cached, True

    hop, t0 = analysis["hop_s"], analysis["t0"]
    sents = analysis["sentences"]
    words = analysis["words"]
    laughs = analysis["laughter"]
    lvl = mix_level(arrays.get("db_orig", arrays["db"]))
    speech_any = arrays["speech"].any(axis=0)
    blk = int(round(0.5 / hop))
    nb = len(lvl) // blk
    blocks = lvl[: nb * blk].reshape(nb, blk).mean(axis=1)
    sp_blocks = speech_any[: nb * blk].reshape(nb, blk).mean(axis=1) > 0.3
    ref = blocks[sp_blocks] if sp_blocks.any() else blocks
    spike_thr = ref.mean() + 1.5 * ref.std()
    spikes = np.concatenate([[0], np.cumsum(blocks > spike_thr)])
    w_times = np.array([w["start"] for w in words if not LAUGH_RE.match(strip_accents(norm_token(w["text"])))])
    med_rate = (len(w_times) / max(1.0, analysis["t_end"] - t0))

    # Las ventanas no empiezan en una muletilla removible: el inicio se mueve a la primera palabra real.
    rm = {(f["mic"], f["start"]): f["end"] for f in analysis["fillers"] if f["removable"]}
    by_mic = {}
    for w in words:
        by_mic.setdefault(w["mic"], []).append(w)
    clean_sents = []
    for x in sents:
        st = x["start"]
        while (x["mic"], st) in rm:
            nxt = [w for w in by_mic[x["mic"]] if w["start"] > rm[(x["mic"], st)] - 1e-6]
            if not nxt or nxt[0]["start"] >= x["end"]:
                break
            st = nxt[0]["start"]
        clean_sents.append({**x, "start": st})
    sents = clean_sents
    starts_ok = [x for x in sents if len([t for t in x["text"].split()
                                          if not LAUGH_RE.match(strip_accents(norm_token(t)))]) >= 3]
    cands = [c for c in candidates(sents, vcfg) if any(abs(c[0] - x["start"]) < 1e-6 for x in starts_ok)]
    feats = []
    for s, e in cands:
        b0, b1 = int((s - t0) / 0.5), int((e - t0) / 0.5)
        energy = (spikes[min(b1, nb)] - spikes[min(b0, nb)]) / max(1, b1 - b0)
        n_laugh = sum(1 for l in laughs if s <= l["start"] <= e)
        laugh_end = any(e - 0.25 * (e - s) <= l["start"] <= e + 3 for l in laughs)
        wt = w_times[(w_times >= s) & (w_times < e)]
        sub = np.histogram(wt, bins=max(2, int((e - s) / 5)), range=(s, e))[0] / 5.0
        rate_change = float(np.std(sub) / (med_rate + 1e-6)) + abs(len(wt) / (e - s) - med_rate) / (med_rate + 1e-6)
        in_win = [x for x in sents if x["start"] >= s - 0.01 and x["end"] <= e + 0.01]
        text = " ".join(x["text"] for x in in_win)
        first3 = " ".join(w["text"] for w in words if s <= w["start"] < s + 3)
        sem_h, parts = heuristic_semantic(first3, text, laugh_end, vcfg["hook_words"])
        fw = cfg["fillers"]["words"]
        feats.append({"start": s, "end": e, "energy": energy, "laughter": n_laugh, "rate": rate_change,
                      "semantic_h": sem_h, "semantic_parts": parts, "text": clean_text(text, fw),
                      "hook": clean_text(next((x["text"] for x in starts_ok if abs(x["start"] - s) < 1e-6),
                                              first3), fw)})
    if not feats:
        data = {"clips": [], "candidates": [], "warnings": ["Sin ventanas candidatas (episodio muy corto)."]}
        cache.save(paths.cache, "viral", h, data)
        return data, False

    # Semántico: el de Claude si existe; si no, heurística.
    warnings = []
    for f in feats:
        f["semantic"] = f["semantic_h"]
        f["semantic_source"] = "heuristic"
        if sem:
            match = [x for x in sem.get("windows", []) if abs(x["start"] - f["start"]) <= 1.0
                     and abs(x["end"] - f["end"]) <= 1.0]
            if match:
                f["semantic"] = float(match[0]["score"])
                f["semantic_source"] = "claude"
                f["title_es"] = match[0].get("title")
                f["hook"] = match[0].get("hook", f["hook"])
    if not sem:
        warnings.append("semantic_scores.json no existe: puntaje semántico heurístico. Claude debe leer "
                        "viral_candidates.json y escribir semantic_scores.json, luego re-correr --stage edit.")

    W = vcfg["weights"]
    r_en, r_la, r_ra = _rank([f["energy"] for f in feats]), _rank([f["laughter"] for f in feats]), \
        _rank([f["rate"] for f in feats])
    pre = W["energy"] * r_en + W["laughter"] * r_la + W["rate"] * r_ra + W["semantic"] * np.array(
        [f["semantic"] for f in feats])
    pt, pv = speaker_pitch([audio["tracks"][m] for m in analysis["mic_ids"]], arrays["speech"], hop, t0,
                           analysis["t_end"])
    wstd = WindowStd(pt, pv)
    pitch = np.array([wstd(f["start"], f["end"]) for f in feats])
    r_pi = _rank(pitch)
    total = pre + W["pitch"] * r_pi
    for i, f in enumerate(feats):
        f["breakdown"] = {"energy": round(W["energy"] * r_en[i], 3), "pitch": round(W["pitch"] * r_pi[i], 3),
                          "laughter": round(W["laughter"] * r_la[i], 3), "rate": round(W["rate"] * r_ra[i], 3),
                          "semantic": round(W["semantic"] * f["semantic"], 3)}
        f["raw"] = {"spike_ratio": round(f["energy"], 3), "pitch_std_st": round(float(pitch[i]), 2),
                    "laughs": f["laughter"], "rate_change": round(f["rate"], 3), "semantic_parts": f["semantic_parts"]}
        f["score"] = round(float(total[i]), 4)

    order = sorted(range(len(feats)), key=lambda i: -feats[i]["score"])
    chosen = []
    for i in order:
        f = feats[i]
        ok = all(min(f["end"], c["end"]) - max(f["start"], c["start"]) <= vcfg["max_overlap"] *
                 min(f["end"] - f["start"], c["end"] - c["start"]) for c in chosen)
        if ok:
            chosen.append(f)
        if len(chosen) == vcfg["top_n"]:
            break
    clips = [{"rank": k + 1, "start": round(f["start"], 3), "end": round(f["end"], 3),
              "duration": round(f["end"] - f["start"], 2), "hook": f["hook"],
              "title_es": f.get("title_es") or title_from(f["hook"]), "score": f["score"],
              "breakdown": f["breakdown"], "raw": f["raw"], "semantic_source": f["semantic_source"],
              "transcript": f["text"]} for k, f in enumerate(chosen)]
    cand_dump = [{"start": round(feats[i]["start"], 3), "end": round(feats[i]["end"], 3),
                  "pre_score": round(float(pre[i]), 3), "transcript": feats[i]["text"]}
                 for i in np.argsort(-pre)[:30]]
    (paths.out / "viral_candidates.json").write_text(json.dumps(
        {"instructions": "Asigna score 0-1 (gancho en 3 s, historia cerrada, polarizante, remate, citable), "
                         "hook y title en español. Guarda como semantic_scores.json: "
                         "{\"windows\": [{start, end, score, hook, title}]}",
         "windows": cand_dump}, ensure_ascii=False, indent=1), encoding="utf-8")
    (paths.out / "clips.json").write_text(json.dumps({"episode": paths.episode, "clips": clips},
                                                     ensure_ascii=False, indent=1), encoding="utf-8")
    data = {"clips": clips, "warnings": warnings, "n_candidates": len(feats)}
    cache.save(paths.cache, "viral", h, data)
    return data, False
