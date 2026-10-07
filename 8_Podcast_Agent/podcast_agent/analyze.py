"""Análisis: VAD por mic, transcripción, muletillas, aire muerto, risas, temas, menciones.

Todo se calcula en el timeline de mics (segundos); los arreglos por frame de 10 ms
se guardan en cache/analysis_arrays.npz y el resto en cache/analysis.json.
"""
import re
import unicodedata
import numpy as np
import soundfile as sf

from . import cache, media, transcribe

PUNCT = "¿?¡!.,;:…\"'()[]«»-—"
STOP = set("""a al algo ante antes así aun aunque cada como con contra cual cuando de del desde donde dos el ella
ellas ellos en entre era eran es esa esas ese eso esos esta estaba estamos estar estas este esto estos está están
fue fueron ha había han hasta hay la las le les lo los mas me mi mis mucho muy más nada ni no nos nosotros o os otra
otro para pero poco por porque que quien se ser si sin sobre son su sus también te tenemos tener tengo ti tiene tienen
todo todos tu tus un una uno unos y ya yo él sí qué cómo""".split())


# ---------------------------------------------------------------- utilidades

def norm_token(text):
    return text.strip(PUNCT).lower()


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def frames_of(t, hop):
    return int(round(t / hop))


def runs(mask):
    """[(inicio, fin)] de las corridas True (fin exclusivo)."""
    if not len(mask):
        return []
    d = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)))


# ---------------------------------------------------------------- niveles y VAD

def frame_levels(path, sr, hop, start=0.0, dur=None):
    """dBFS por frame de `hop` segundos, en streaming."""
    n = int(round(sr * hop))
    out, rest = [], np.zeros(0, np.float32)
    for block in media.stream_audio(path, sr, start=start or None, dur=dur):
        x = np.concatenate([rest, block])
        k = len(x) // n
        if k:
            frames = x[: k * n].reshape(k, n)
            out.append(10 * np.log10(np.mean(frames.astype(np.float64) ** 2, axis=1) + 1e-12))
        rest = x[k * n:]
    return np.concatenate(out).astype(np.float32) if out else np.zeros(0, np.float32)


def frame_levels_ch(mic, sr, hop, start=0.0, dur=None):
    """Como frame_levels pero sobre el archivo original (respeta el canal del mic)."""
    n = int(round(sr * hop))
    out, rest = [], np.zeros(0, np.float32)
    for block in media.stream_audio(mic["path"], sr, channel=mic["channel"], start=start or None, dur=dur):
        x = np.concatenate([rest, block])
        k = len(x) // n
        if k:
            out.append(10 * np.log10(np.mean(x[: k * n].reshape(k, n).astype(np.float64) ** 2, axis=1) + 1e-12))
        rest = x[k * n:]
    return np.concatenate(out).astype(np.float32) if out else np.zeros(0, np.float32)


def _fit(x, n):
    return x[:n] if len(x) >= n else np.pad(x, (0, n - len(x)), constant_values=-120.0)


def adaptive_threshold(db, vcfg):
    floor = float(np.percentile(db, vcfg["noise_floor_percentile"]))
    lo, hi = vcfg["floor_valid_range_dbfs"]
    if not np.isfinite(floor) or floor < lo or floor > hi:
        return float(vcfg["fallback_threshold_dbfs"]), floor, True
    return floor + vcfg["threshold_above_floor_db"], floor, False


def smooth_activity(mask, hop, vcfg):
    """Hangover, duración mínima y unión de huecos cortos."""
    m = mask.copy()
    hang = frames_of(vcfg["hangover_s"], hop)
    gap = frames_of(vcfg["merge_gap_s"], hop)
    minf = frames_of(vcfg["min_speech_s"], hop)
    segs = [(a, b) for a, b in runs(m) if b - a >= minf]
    merged = []
    for a, b in segs:
        b = min(len(m), b + hang)
        if merged and a - merged[-1][1] <= gap:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    out = np.zeros_like(m)
    for a, b in merged:
        out[a:b] = True
    return out


def vad(levels, vcfg, hop):
    ids = list(levels)
    n = min(len(v) for v in levels.values())
    db = np.stack([levels[i][:n] for i in ids])
    thr, info = {}, {}
    for k, i in enumerate(ids):
        thr[i], floor, fb = adaptive_threshold(db[k], vcfg)
        info[i] = {"noise_floor_dbfs": round(floor, 1), "threshold_dbfs": round(thr[i], 1), "fallback": fb}
    raw = np.stack([db[k] > thr[i] for k, i in enumerate(ids)])
    dominant = np.zeros_like(raw)
    for k in range(len(ids)):
        others = np.delete(db, k, axis=0)
        beats = (db[k] - others.max(axis=0) >= vcfg["bleed_margin_db"]) if len(ids) > 1 else np.ones(n, bool)
        dominant[k] = raw[k] & beats
    speech = np.stack([smooth_activity(dominant[k], hop, vcfg) for k in range(len(ids))])
    return ids, db, raw, dominant, speech, info


def own_voice(db, raw, dominant, vcfg):
    """Presencia de voz propia compensando el sangrado medido por par de mics.

    atten[k][j] = mediana(db_k - db_j) cuando solo k habla (sangrado de k en j).
    j tiene voz propia si supera por ≥ bleed_margin lo que le llegaría de cada k.
    """
    n = db.shape[0]
    pres = raw.copy()
    for j in range(n):
        for k in range(n):
            if k == j:
                continue
            solo = dominant[k] & ~dominant[j]
            atten = float(np.median(db[k, solo] - db[j, solo])) if solo.sum() > 50 else vcfg["bleed_margin_db"]
            pres[j] &= db[j] - (db[k] - atten) >= vcfg["bleed_margin_db"]
    return pres


def crosstalk_regions(presence, hop, vcfg):
    if presence.shape[0] < 2:
        return []
    w = max(1, frames_of(vcfg["crosstalk_window_s"], hop))
    kernel = np.ones(w) / w
    share = np.stack([np.convolve(d.astype(float), kernel, mode="same") for d in presence])
    both = (share >= vcfg["crosstalk_min_share"]).sum(axis=0) >= 2
    return [(round(a * hop, 3), round(b * hop, 3)) for a, b in runs(both) if (b - a) * hop >= vcfg["crosstalk_min_s"]]


# ---------------------------------------------------------------- transcripción

def gated_wav(path, speech_row, hop, out, tcfg, start, dur):
    """Atenúa el mic fuera de su habla dominante (evita transcribir el sangrado del otro)."""
    sr = 16000
    x = media.decode_audio(path, sr, start or None, dur)
    pad = frames_of(tcfg["gate_pad_s"], hop)
    keep = np.convolve(speech_row.astype(float), np.ones(2 * pad + 1), mode="same") > 0
    gain = np.where(keep, 1.0, 10 ** (tcfg["gate_attenuation_db"] / 20))
    per = int(sr * hop)
    g = np.repeat(gain, per)[: len(x)]
    g = np.pad(g, (0, len(x) - len(g)), constant_values=g[-1] if len(g) else 1.0)
    sf.write(out, (x * g).astype(np.float32), sr)
    return out


def refine_words(words, raw_row, hop, t0, max_shift=0.15):
    """Ajusta inicio/fin de cada palabra a la energía real del mic (timestamps de Whisper suelen quedar flojos)."""
    n = len(raw_row)
    ms = frames_of(max_shift, hop)
    for i, w in enumerate(words):
        a, b = frames_of(w["start"] - t0, hop), frames_of(w["end"] - t0, hop)
        a, b = max(0, min(a, n - 1)), max(1, min(b, n))
        prev_b = frames_of(words[i - 1]["end"] - t0, hop) if i else 0
        next_a = frames_of(words[i + 1]["start"] - t0, hop) if i + 1 < len(words) else n
        # extender hacia afuera mientras haya energía (sin invadir palabras vecinas)
        k = 0
        while a > prev_b and a > 0 and raw_row[a - 1] and k < ms:
            a -= 1
            k += 1
        k = 0
        while b < next_a and b < n and raw_row[b] and k < ms:
            b += 1
            k += 1
        w["start_raw"], w["end_raw"] = w["start"], w["end"]
        w["start"] = round(min(w["start"], t0 + a * hop), 3)
        w["end"] = round(max(w["end"], t0 + b * hop), 3)
    return words


# ---------------------------------------------------------------- muletillas

def _is_filler_token(tok, single):
    t = strip_accents(tok)
    if re.fullmatch(r"e+h+", t) or re.fullmatch(r"m{2,}h*|hm+", t):
        return True
    return tok in single


def detect_fillers(words_by_mic, dominant, ids, hop, t0, fcfg):
    clear = fcfg["clearance_s"]
    single = {f for f in fcfg["words"] if " " not in f}
    ambiguous = set(fcfg["ambiguous"])
    out = []

    def others_silent(mic, s, e):
        k = ids.index(mic)
        a, b = max(0, frames_of(s - clear - t0, hop)), frames_of(e + clear - t0, hop)
        rows = np.delete(dominant, k, axis=0)
        return rows.shape[0] == 0 or not rows[:, a:b].any()

    for mic, words in words_by_mic.items():
        i = 0
        while i < len(words):
            w = words[i]
            tok = norm_token(w["text"])
            span = 1
            text = tok
            if tok == "o" and i + 1 < len(words) and norm_token(words[i + 1]["text"]) == "sea" \
                    and words[i + 1]["start"] - w["end"] < 0.15:
                span, text = 2, "o sea"
            elif not _is_filler_token(tok, single):
                i += 1
                continue
            start, end = w["start"], words[i + span - 1]["end"]
            prev_w = words[i - 1] if i > 0 else None
            next_w = words[i + span] if i + span < len(words) else None
            gap_b = start - prev_w["end"] if prev_w else 99.0
            gap_a = next_w["start"] - end if next_w else 99.0
            reasons = []
            if gap_b < clear or gap_a < clear:
                reasons.append("sin holgura de 0.1 s")
            if not others_silent(mic, start, end):
                reasons.append("otro mic hablando")
            last_txt = words[i + span - 1]["text"]
            if last_txt.rstrip().endswith("?"):
                reasons.append("es pregunta")
            if text in ambiguous:
                if gap_a < fcfg["ambiguous_min_gap_after_s"]:
                    reasons.append("pegada a la siguiente palabra (parte de la frase)")
                if text == "bueno" and prev_w and gap_b < 0.5 and \
                        norm_token(prev_w["text"]) in set(fcfg["bueno_adjective_prev"]):
                    reasons.append("'bueno' como adjetivo")
                ctx = fcfg["ambiguous_needs_turn_context_s"]
                if gap_b > ctx and gap_a > ctx:
                    reasons.append("respuesta completa, no muletilla")
            out.append({"mic": mic, "text": text, "start": start, "end": end,
                        "gap_before": round(gap_b, 3), "gap_after": round(gap_a, 3),
                        "prev_end": prev_w["end"] if prev_w else None,
                        "next_start": next_w["start"] if next_w else None,
                        "removable": not reasons, "reasons": reasons})
            i += span
    return sorted(out, key=lambda f: f["start"])


# ---------------------------------------------------------------- frases, risas, temas, menciones

def sentences(words_by_mic, max_gap=0.7):
    out = []
    for mic, words in words_by_mic.items():
        cur = []
        for w in words:
            if cur and (w["start"] - cur[-1]["end"] > max_gap):
                out.append(cur)
                cur = []
            cur.append(w)
            if w["text"].rstrip().endswith((".", "?", "!", "…")):
                out.append(cur)
                cur = []
        if cur:
            out.append(cur)
    res = [{"mic": s[0]["mic"], "start": s[0]["start"], "end": s[-1]["end"],
            "text": " ".join(w["text"] for w in s)} for s in out]
    return sorted(res, key=lambda s: s["start"])


def is_question(sentence, qwords):
    t = sentence["text"].strip()
    if t.endswith("?") or t.startswith("¿"):
        return True
    first = strip_accents(norm_token(t.split()[0])) if t.split() else ""
    return first in {strip_accents(q.split()[0]) for q in qwords} and len(t.split()) > 2


LAUGH_RE = re.compile(r"^(ja|je|ji|ha){2,}h?$|^risas?$")


def laughter(words_by_mic, db, speech, ids, hop, t0):
    """Risas por transcripción (jaja, (risas)) + acústica (envolvente periódica 3.5–7 Hz sin palabras)."""
    out = []
    word_mask = {i: np.zeros(db.shape[1], bool) for i in ids}
    for mic, words in words_by_mic.items():
        for w in words:
            a, b = frames_of(w["start"] - t0, hop), frames_of(w["end"] - t0, hop)
            if LAUGH_RE.match(strip_accents(norm_token(w["text"]))):
                out.append({"mic": mic, "start": w["start"], "end": w["end"], "source": "transcript"})
            else:
                word_mask[mic][a:b] = True
    win = frames_of(1.5, hop)
    for k, mic in enumerate(ids):
        for a, b in runs(speech[k] & ~word_mask[mic]):
            if b - a < win:
                continue
            env = db[k, a:b] - db[k, a:b].mean()
            ac = np.correlate(env, env, "full")[len(env) - 1:]
            if ac[0] <= 0:
                continue
            ac /= ac[0]
            lo, hi = int(1 / (7 * hop)), int(1 / (3.5 * hop)) + 1
            if hi < len(ac) and ac[lo:hi].max() > 0.4:
                out.append({"mic": mic, "start": round(t0 + a * hop, 3), "end": round(t0 + b * hop, 3),
                            "source": "acoustic"})
    return sorted(out, key=lambda x: x["start"])


def _bag(text):
    toks = [strip_accents(norm_token(t)) for t in text.split()]
    return [t for t in toks if len(t) > 3 and t not in STOP]


def topic_changes(sents, tcfg, t_end):
    out = []
    cues = [strip_accents(c) for c in tcfg["cue_phrases"]]
    for s in sents:
        low = strip_accents(s["text"].lower())
        if any(low.lstrip("¿¡ ").startswith(c) for c in cues):
            out.append({"time": s["start"], "source": "cue", "text": s["text"][:80]})
    # TextTiling simple: similitud léxica entre bloques vecinos.
    W = tcfg["window_s"]
    nb = int(np.ceil(t_end / W))
    if nb >= 4:
        vocab = {}
        mats = [dict() for _ in range(nb)]
        for s in sents:
            b = min(nb - 1, int(s["start"] // W))
            for t in _bag(s["text"]):
                vocab.setdefault(t, len(vocab))
                mats[b][t] = mats[b].get(t, 0) + 1

        def cos(i, j):
            a, b = mats[i], mats[j]
            num = sum(v * b.get(k, 0) for k, v in a.items())
            den = np.sqrt(sum(v * v for v in a.values()) * sum(v * v for v in b.values()))
            return num / den if den else 0.0

        sims = [cos(i, i + 1) for i in range(nb - 1)]
        for i in range(1, len(sims) - 1):
            depth = (sims[i - 1] - sims[i]) + (sims[i + 1] - sims[i])
            if depth >= tcfg["depth_threshold"]:
                t = (i + 1) * W
                near = min(sents, key=lambda s: abs(s["start"] - t)) if sents else None
                if near:
                    out.append({"time": near["start"], "source": "lexical", "depth": round(depth, 3),
                                "text": near["text"][:80]})
    out.sort(key=lambda x: (x["time"], x["source"] != "cue"))
    kept = []
    for o in out:
        if not kept or o["time"] - kept[-1]["time"] >= tcfg["min_spacing_s"]:
            kept.append(o)
        elif o["source"] == "cue" and kept[-1]["source"] != "cue":
            kept[-1] = o
    return kept


NUM_WORDS = {"mil", "millón", "millones", "cien", "ciento", "cientos", "billones", "porciento", "%"}
PLACE_PREP = {"en", "de", "desde", "a", "hacia", "para"}


def mentions(words_by_mic, fillers=()):
    """Personas / lugares / números / productos (heurística sin modelo NER)."""
    filler_starts = {(f["mic"], f["start"]) for f in fillers}
    out = []
    for mic, words in words_by_mic.items():
        content = [w for w in words if (mic, w["start"]) not in filler_starts
                   and not LAUGH_RE.match(strip_accents(norm_token(w["text"])))]
        for i, w in enumerate(content):
            raw = w["text"].strip(PUNCT)
            if not raw:
                continue
            prev = content[i - 1] if i else None
            sent_start = (prev is None or prev["text"].rstrip().endswith((".", "?", "!", "…"))
                          or w["start"] - prev["end"] > 1.0 or w["text"].startswith(("¿", "¡")))
            low = raw.lower()
            if re.fullmatch(r"\d[\d.,]*%?", raw) or low in NUM_WORDS:
                num = f"{prev['text'].strip(PUNCT)} {raw}" if low in NUM_WORDS and prev else raw
                out.append({"mic": mic, "time": w["start"], "text": num, "kind": "número"})
            elif raw[0].isupper() and not sent_start and low not in STOP and len(raw) > 2:
                kind = "lugar" if prev and norm_token(prev["text"]) in PLACE_PREP else "persona/producto"
                out.append({"mic": mic, "time": w["start"], "text": raw, "kind": kind})
    return sorted(out, key=lambda m: m["time"])


# ---------------------------------------------------------------- aire muerto

def dead_air(raw, hop, t0, words_all, sents, laughs, dcfg, crosstalk):
    silent = ~raw.any(axis=0)
    min_f = frames_of(dcfg["first_minute_min_silence_s"], hop)
    ks, kn = dcfg["keep_split"]
    guard = dcfg["word_guard_s"]
    w_starts = np.array(sorted(w["start"] for w in words_all)) if words_all else np.zeros(0)
    w_ends = np.array(sorted(w["end"] for w in words_all)) if words_all else np.zeros(0)
    removals, keeps = [], []
    for a, b in runs(silent):
        if b - a < min_f:
            continue
        s, e = t0 + a * hop, t0 + b * hop
        if a == 0 or b == len(silent):
            continue  # extremos del archivo: los maneja el recorte del timeline
        prev_s = [x for x in sents if x["end"] <= s + 0.05]
        reason = None
        if prev_s and is_question(prev_s[-1], dcfg["question_words"]) and s - prev_s[-1]["end"] < 0.6:
            reason = "question"
        elif any(e <= l["start"] <= e + dcfg["punchline_laugh_window_s"] for l in laughs):
            next_s = [x for x in sents if x["start"] >= e - 0.05]
            if next_s and next_s[0]["end"] < e + dcfg["punchline_laugh_window_s"] + 2:
                reason = "punchline"
        # Nunca cortar dentro de una palabra: recorta el rango a las palabras vecinas + guarda.
        lo = s + ks
        hi = e - kn
        before = w_ends[w_ends <= (s + e) / 2]
        after = w_starts[w_starts >= (s + e) / 2]
        if len(before):
            lo = max(lo, before[-1] + guard)
        if len(after):
            hi = min(hi, after[0] - guard)
        inside = ((w_starts < hi) & (w_ends > lo)).any() if len(w_starts) else False
        item = {"start": round(s, 3), "end": round(e, 3), "silence_s": round(e - s, 3),
                "cut_start": round(lo, 3), "cut_end": round(hi, 3), "strict_only": (e - s) <= dcfg["min_silence_s"]}
        if reason:
            keeps.append({**item, "reason": reason})
        elif hi - lo >= 0.1 and not inside:
            removals.append(item)
    return removals, keeps


# ---------------------------------------------------------------- propuesta de mapeo

INTRO_RE = re.compile(r"\b(?:soy|me llamo|mi nombre es)\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)")
ADDR_RE = re.compile(r"\b(?:con|gracias|bienvenid[oa]s?|mi amig[oa]|querid[oa])\s+(?:mi amig[oa]\s+)?"
                     r"([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)")


def speaker_evidence(words_by_mic, speech, ids, hop, sents):
    total = speech.sum()
    ev = {}
    for k, mic in enumerate(ids):
        mine = [s for s in sents if s["mic"] == mic]
        text = " ".join(s["text"] for s in mine[:60])
        ev[mic] = {"speech_share": round(float(speech[k].sum() / total) if total else 0, 3),
                   "first_lines": [s["text"] for s in mine[:3]],
                   "self_intro": sorted(set(INTRO_RE.findall(text))),
                   "names_said": sorted(set(ADDR_RE.findall(text)))}
    for mic in ids:
        others = set()
        for o in ids:
            if o != mic:
                others |= set(ev[o]["names_said"])
        ev[mic]["probably_named"] = sorted((set(ev[mic]["self_intro"]) | others) - set(ev[mic]["names_said"]))
    return ev


# ---------------------------------------------------------------- etapa

def run_analyze(paths, cfg, ingest, audio, excerpt=None, force=False):
    vcfg, tcfg = cfg["vad"], dict(cfg["transcription"])
    backend, warn = transcribe.resolve_backend(tcfg)
    h = cache.input_hash("analyze", cache.code_hash("analyze", "transcribe"), cache.stage_hash(paths.cache, "audio"),
                         {k: cfg[k] for k in ("vad", "transcription", "fillers", "dead_air", "topics")},
                         excerpt, backend)
    cached = None if force else cache.load(paths.cache, "analyze", h)
    if cached and (paths.cache / "analysis_arrays.npz").exists():
        return cached, True

    hop = vcfg["frame_s"]
    t0, dur = (excerpt if excerpt else (0.0, None))
    levels = {m: frame_levels(p, vcfg["analysis_sr"], hop, t0, dur) for m, p in audio["tracks"].items()}
    ids, db, raw, dominant, speech, vinfo = vad(levels, vcfg, hop)
    # Energía para retención/viral: del audio ORIGINAL (la compresión aplana la dinámica).
    mic_by_id = {m["id"]: m for m in ingest["mics"]}
    db_orig = np.stack([_fit(frame_levels_ch(mic_by_id[m], vcfg["analysis_sr"], hop, t0, dur), db.shape[1])
                        for m in ids])
    t_end = t0 + db.shape[1] * hop
    presence = own_voice(db, raw, dominant, vcfg)
    xtalk = [(a + t0, b + t0) for a, b in crosstalk_regions(presence, hop, vcfg)]

    words_by_mic = {}
    mics = {m["id"]: m for m in ingest["mics"]}
    for k, mic in enumerate(ids):
        wav = paths.cache / f"gated_{mic}.wav"
        if backend != "fixture":
            gated_wav(audio["tracks"][mic], speech[k], hop, wav, tcfg, t0, dur)
        words = transcribe.transcribe(backend, tcfg, wav, mics[mic], paths.episode_dir, t0, (t0, t_end))
        # Solo palabras propias: deben caer (en ≥50%) sobre habla dominante del mic.
        kept = []
        for w in words:
            a, b = frames_of(w["start"] - t0, hop), max(frames_of(w["end"] - t0, hop), frames_of(w["start"] - t0, hop) + 1)
            pad = frames_of(0.15, hop)
            if speech[k, max(0, a - pad): b + pad].mean() >= 0.5 or backend == "fixture":
                kept.append({**w, "mic": mic})
        words_by_mic[mic] = refine_words(sorted(kept, key=lambda w: w["start"]), raw[k], hop, t0)
    words_all = sorted((w for ws in words_by_mic.values() for w in ws), key=lambda w: w["start"])

    sents = sentences(words_by_mic)
    laughs = laughter(words_by_mic, db, speech, ids, hop, t0)
    fillers = detect_fillers(words_by_mic, dominant, ids, hop, t0, cfg["fillers"])
    removals, keeps = dead_air(raw, hop, t0, words_all, sents, laughs, cfg["dead_air"], xtalk)
    topics = topic_changes(sents, cfg["topics"], t_end)
    ments = mentions(words_by_mic, fillers)
    evidence = speaker_evidence(words_by_mic, speech, ids, hop, sents)

    np.savez_compressed(paths.cache / "analysis_arrays.npz", db=db, raw=raw, dominant=dominant, speech=speech,
                        presence=presence, db_orig=db_orig)
    data = {
        "backend": backend, "warnings": [warn] if warn else [], "mic_ids": ids, "hop_s": hop,
        "t0": t0, "t_end": t_end, "vad": vinfo, "words": words_all, "sentences": sents,
        "fillers": fillers, "dead_air": removals, "keep_pauses": keeps, "crosstalk": xtalk,
        "laughter": laughs, "topics": topics, "mentions": ments, "speaker_evidence": evidence,
    }
    cache.save(paths.cache, "analyze", h, data)
    return data, False


def load_arrays(paths):
    z = np.load(paths.cache / "analysis_arrays.npz")
    return {k: z[k] for k in z.files}
