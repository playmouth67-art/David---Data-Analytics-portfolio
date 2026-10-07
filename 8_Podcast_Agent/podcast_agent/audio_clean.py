"""Limpieza de audio con ffmpeg ANTES de Resolve. Escribe archivos nuevos en audio_processed/.

Cadena por mic (ffmpeg): highpass 80 Hz -> denoise ligero -> de-ess -> compresión.
Normalización de la MEZCLA a -14 LUFS / -1 dBTP: una ganancia común más un
limitador ENLAZADO (una sola curva de ganancia calculada sobre la suma y aplicada
igual a todas las pistas), así las pistas siguen separadas en Resolve y su suma
cumple el true peak. La latencia que mete afftdn se mide y se compensa.
Nunca se escribe sobre los originales.
"""
import re

import numpy as np
import soundfile as sf
from scipy.ndimage import maximum_filter1d, minimum_filter1d, uniform_filter1d

from . import cache, media
from .sync import xcorr_full


def chain(acfg):
    return ",".join([f"highpass=f={acfg['highpass_hz']}", acfg["denoise"], acfg["deess"], acfg["compress"]])


def render_track(src, channel, out, filt, acfg, duration=None):
    """Etapa 1 en float32 (sin clipping intermedio)."""
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(src)]
    if duration:
        cmd += ["-t", f"{duration:.6f}"]
    pre = f"pan=mono|c0=c{int(channel)}," if channel is not None else "aformat=channel_layouts=mono,"
    cmd += ["-af", pre + filt, "-ar", str(acfg["sample_rate"]), "-c:a", "pcm_f32le", str(out)]
    media.run(cmd, "procesar audio")


def latency_samples(original, channel, processed, sr, at=(30.0, 90.0, 150.0), dur=10.0):
    """Latencia (muestras a sr) que agregó la cadena; mediana de varias ventanas."""
    found = []
    for t in at:
        a = media.decode_audio(original, sr, t, dur, channel=channel)
        b = media.decode_audio(processed, sr, t, dur)
        if len(a) < sr or len(b) < sr or np.std(a) == 0 or np.std(b) == 0:
            continue
        lags, c = xcorr_full(b, a)
        sel = np.abs(lags) <= int(0.1 * sr)
        found.append(int(lags[sel][np.argmax(c[sel])]))
    return int(np.median(found)) if found else 0


def linked_gain(tracks, gain, lim, sr):
    """Curva de ganancia común: garantiza |mezcla| y |cada pista| <= lim (muestra)."""
    la, rel = int(0.005 * sr), int(0.08 * sr)
    scaled = [x * gain for x in tracks]
    mix = np.abs(sum(scaled))
    peak = np.maximum(mix, np.max(np.abs(np.stack(scaled)), axis=0))
    peak = maximum_filter1d(peak, size=2 * la + 1)
    target = np.minimum(1.0, lim / np.maximum(peak, 1e-9))
    held = minimum_filter1d(minimum_filter1d(target, size=2 * la + 1), size=2 * rel + 1)
    return uniform_filter1d(held, size=la), 2 * la + 2 * rel + la


def render_linked(stage1, lags, outs, gain_db, lim_db, sr, subtype, block_s=30.0):
    """Aplica ganancia + limitador enlazado por bloques con contexto (exacto como si fuera de una vez)."""
    gain, lim = 10 ** (gain_db / 20), 10 ** (lim_db / 20)
    readers = [sf.SoundFile(str(p)) for p in stage1]
    n_out = min(r.frames for r in readers)
    writers = [sf.SoundFile(str(o), "w", sr, 1, subtype=subtype) for o in outs]
    _, ctx = linked_gain([np.zeros(10)], 1.0, 1.0, sr)
    block = int(block_s * sr)
    try:
        for s in range(0, n_out, block):
            e = min(n_out, s + block)
            a0, a1 = max(0, s - ctx), min(n_out, e + ctx)
            xs = []
            for r, lag in zip(readers, lags):
                lo, hi = a0 + lag, a1 + lag   # compensa la latencia de la cadena
                r.seek(max(0, min(lo, r.frames)))
                x = r.read(max(0, min(hi, r.frames) - max(0, lo)), dtype="float32")
                x = np.pad(x, (max(0, -lo), (a1 - a0) - len(x) - max(0, -lo)))
                xs.append(x)
            g, _ = linked_gain(xs, gain, lim, sr)
            for w, x in zip(writers, xs):
                w.write((x * gain * g)[s - a0: s - a0 + (e - s)])
    finally:
        for f in readers + writers:
            f.close()


def measure_mix(files):
    """Loudness integrada y true peak de la suma de las pistas (ebur128)."""
    cmd = ["ffmpeg", "-nostats", "-nostdin", "-hide_banner"]
    for f in files:
        cmd += ["-i", str(f)]
    mix = f"amix=inputs={len(files)}:normalize=0," if len(files) > 1 else ""
    cmd += ["-filter_complex", f"{mix}ebur128=peak=true", "-f", "null", "-"]
    err = media.run(cmd, "medir loudness").stderr.decode(errors="replace")
    summary = err[err.rfind("Summary:"):]
    i = float(re.search(r"I:\s+(-?[\d.]+|-inf) LUFS", summary).group(1))
    tp = re.search(r"Peak:\s+(-?[\d.]+|-inf) dBFS", summary).group(1)
    return i, float(tp)


def alignment_lag(original, channel, processed, at_s=30.0, dur=20.0):
    """Muestras de retraso del procesado vs el original (debe ser 0)."""
    sr = 16000
    a = media.decode_audio(original, sr, at_s, dur, channel=channel)
    b = media.decode_audio(processed, sr, at_s, dur)
    if len(a) < sr or np.std(a) == 0 or np.std(b) == 0:
        return 0
    lags, c = xcorr_full(b, a)
    sel = np.abs(lags) <= int(0.05 * sr)
    return int(lags[sel][np.argmax(c[sel])])


def run_audio(paths, cfg, ingest, excerpt=None, force=False):
    acfg = cfg["audio"]
    end = sum(excerpt) if excerpt else None
    h = cache.input_hash("audio", cache.code_hash("audio_clean"), cache.stage_hash(paths.cache, "ingest"), acfg, end)
    cached = None if force else cache.load(paths.cache, "audio", h)
    if cached:
        return cached, True

    filt = chain(acfg)
    sr = acfg["sample_rate"]
    mics = ingest["mics"]
    stage1, chain_lat = [], []
    for m in mics:
        out = paths.audio_processed / f"_stage1_{m['id']}.wav"
        render_track(m["path"], m["channel"], out, filt, acfg, end)
        stage1.append(out)
        chain_lat.append(latency_samples(m["path"], m["channel"], out, sr))
    pre_i, pre_tp = measure_mix(stage1)

    finals = [paths.audio_processed / f"{m['id']}_{paths.episode}_proc.wav" for m in mics]
    subtype = {16: "PCM_16", 24: "PCM_24", 32: "FLOAT"}[acfg["bit_depth"]]
    gain = acfg["target_lufs"] - pre_i
    lim = acfg["target_tp_dbtp"] - acfg["limiter_margin_db"]
    passes = []
    for _ in range(acfg["max_norm_passes"]):
        render_linked(stage1, chain_lat, finals, gain, lim, sr, subtype)
        i, tp = measure_mix(finals)
        passes.append({"gain_db": round(gain, 3), "limit_dbfs": round(lim, 2), "mix_lufs": i, "mix_tp_dbtp": tp})
        if abs(i - acfg["target_lufs"]) <= 0.5 and tp <= acfg["target_tp_dbtp"]:
            break
        if len(passes) > 1 and abs(passes[-2]["mix_lufs"] - i) < 0.1 and tp <= acfg["target_tp_dbtp"]:
            break  # la loudness ya no responde: la manda el techo de true peak
        if tp > acfg["target_tp_dbtp"]:
            lim -= (tp - acfg["target_tp_dbtp"]) + 0.1
        gain += acfg["target_lufs"] - i
    for p in stage1:
        p.unlink(missing_ok=True)
    finals = {m["id"]: f for m, f in zip(mics, finals)}

    lags = {m["id"]: alignment_lag(m["path"], m["channel"], finals[m["id"]]) for m in ingest["mics"]}
    data = {
        "chain": filt, "tracks": {k: str(v) for k, v in finals.items()},
        "pre_norm": {"mix_lufs": pre_i, "mix_tp_dbtp": pre_tp}, "passes": passes,
        "final": passes[-1], "chain_latency_compensated_samples": dict(zip([m["id"] for m in mics], chain_lat)),
        "alignment_lag_samples_16k": lags,
        "target": {"lufs": acfg["target_lufs"], "tp": acfg["target_tp_dbtp"]},
        "warnings": ([] if passes[-1]["mix_tp_dbtp"] <= acfg["target_tp_dbtp"] and
                     abs(passes[-1]["mix_lufs"] - acfg["target_lufs"]) <= 0.5 else
                     [f"Loudness final {passes[-1]['mix_lufs']:.1f} LUFS / {passes[-1]['mix_tp_dbtp']:.1f} dBTP "
                      f"fuera de objetivo tras {len(passes)} pasadas."])
        + [f"Pista {k} desfasada {v} muestras (16 kHz) tras el procesado." for k, v in lags.items() if abs(v) > 16],
    }
    cache.save(paths.cache, "audio", h, data)
    return data, False
