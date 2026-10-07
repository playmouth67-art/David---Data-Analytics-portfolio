"""Ingest: detecta cámaras, mics, fps, resolución, timecode y canales. Exporta un frame por cámara."""
from collections import Counter
from pathlib import Path

import numpy as np

from . import cache, media
from .errors import EmptyEpisode
from .timecode import parse_rate, rate_str, is_drop_frame_rate, tc_to_frames, sec_to_frame


def _tc_tag(probe):
    for s in [probe.get("format", {})] + probe.get("streams", []):
        tc = (s.get("tags") or {}).get("timecode")
        if tc:
            return tc
    return None


def probe_camera(path, probe):
    v = next(s for s in probe["streams"] if s["codec_type"] == "video")
    a = next((s for s in probe["streams"] if s["codec_type"] == "audio"), None)
    rate = parse_rate(v.get("r_frame_rate") or v.get("avg_frame_rate"))
    duration = float(v.get("duration") or probe["format"]["duration"])
    tc = _tc_tag(probe)
    drop = bool(tc and (";" in tc or "." in tc)) or False
    return {
        "path": str(path), "name": path.stem,
        "fps": rate_str(rate), "width": int(v["width"]), "height": int(v["height"]),
        "codec": v.get("codec_name"), "duration_s": duration,
        "duration_frames": int(v["nb_frames"]) if v.get("nb_frames", "0").isdigit() and int(v["nb_frames"]) > 0
        else sec_to_frame(duration, rate),
        "timecode": tc, "drop_frame": drop and is_drop_frame_rate(rate),
        "tc_start_frames": tc_to_frames(tc, rate) if tc else 0,
        "scratch_audio": None if a is None else {
            "channels": int(a.get("channels", 1)), "sample_rate": int(a.get("sample_rate", 48000)),
            "codec": a.get("codec_name")},
    }


def _identical_channels(path, channels, threshold):
    """Detecta archivos estéreo con el mismo mic duplicado en ambos canales (muestra 60 s del medio)."""
    if channels < 2:
        return False
    info = media.ffprobe(path)
    dur = float(info["format"]["duration"])
    start = max(0.0, dur / 2 - 30)
    chans = [media.decode_audio(path, 8000, start, 60, channel=c) for c in range(channels)]
    ref = chans[0]
    for c in chans[1:]:
        n = min(len(ref), len(c))
        if n < 100 or np.std(ref[:n]) == 0 or np.std(c[:n]) == 0:
            return False
        if np.corrcoef(ref[:n], c[:n])[0, 1] < threshold:
            return False
    return True


def probe_audio(path, probe, cfg):
    a = next(s for s in probe["streams"] if s["codec_type"] == "audio")
    channels = int(a.get("channels", 1))
    dur = float(a.get("duration") or probe["format"]["duration"])
    dup = _identical_channels(path, channels, cfg["media"]["identical_channel_corr"])
    chans = [0] if dup else list(range(channels))
    return [{
        "path": str(path), "file": path.name, "channel": (None if channels == 1 or dup else c),
        "sample_rate": int(a.get("sample_rate", 48000)), "duration_s": dur,
        "timecode": _tc_tag(probe), "source_channels": channels,
    } for c in chans]


def scan(episode_dir, cfg):
    ep = Path(episode_dir)
    if not ep.is_dir():
        raise EmptyEpisode(f"La carpeta del episodio no existe: {ep}")
    vext, aext = set(cfg["media"]["video_ext"]), set(cfg["media"]["audio_ext"])
    files = sorted(p for p in ep.iterdir() if p.is_file() and not p.name.startswith("."))
    videos = [p for p in files if p.suffix.lower() in vext]
    audios = [p for p in files if p.suffix.lower() in aext]
    if not videos and not audios:
        raise EmptyEpisode(f"La carpeta {ep} no tiene video ni audio reconocible "
                           f"({', '.join(sorted(vext | aext))}).")
    if not videos:
        raise EmptyEpisode(f"No hay archivos de cámara en {ep}.")
    if not audios:
        raise EmptyEpisode(f"No hay pistas de mic aisladas en {ep}.")
    return videos, audios


def run_ingest(paths, cfg, force=False):
    media.require_ffmpeg()
    videos, audios = scan(paths.episode_dir, cfg)
    h = cache.input_hash("ingest", cache.code_hash("ingest", "media"), [cache.file_signature(p) for p in videos + audios], cfg["media"])
    cached = None if force else cache.load(paths.cache, "ingest", h)
    if cached:
        return cached, True

    cams = []
    for i, p in enumerate(videos, 1):
        c = probe_camera(p, media.ffprobe(p))
        c["id"] = f"cam{i}"
        cams.append(c)
    mics = []
    for p in audios:
        for m in probe_audio(p, media.ffprobe(p), cfg):
            m["id"] = f"mic{len(mics) + 1}"
            mics.append(m)

    # Entrega: mismo fps y resolución que la mayoría de las cámaras.
    fps_counts = Counter(c["fps"] for c in cams)
    res_counts = Counter((c["width"], c["height"]) for c in cams)
    delivery_fps = fps_counts.most_common(1)[0][0]
    w, hgt = res_counts.most_common(1)[0][0]
    warnings = []
    if len(fps_counts) > 1:
        warnings.append(f"Cámaras con fps distintos {dict(fps_counts)}; se entrega a {delivery_fps}.")
    if len(res_counts) > 1:
        warnings.append(f"Cámaras con resoluciones distintas {dict(res_counts)}; se entrega a {w}x{hgt}.")
    no_scratch = [c["id"] for c in cams if not c["scratch_audio"]]
    if no_scratch:
        warnings.append(f"Sin audio de referencia en {no_scratch}: no se pueden sincronizar por audio.")
    mic_durs = [m["duration_s"] for m in mics]
    if max(mic_durs) - min(mic_durs) > 1.0:
        warnings.append("Los mics no duran lo mismo (>1 s): se asume que arrancan juntos (misma grabadora).")
    rate = parse_rate(delivery_fps)
    drop = any(c["drop_frame"] for c in cams if c["fps"] == delivery_fps)

    frames = {}
    for c in cams:
        out = paths.frames / f"{c['id']}_{c['name']}.png"
        media.extract_frame(c["path"], out, min(c["duration_s"] * 0.33, c["duration_s"] - 0.5))
        frames[c["id"]] = str(out)

    data = {
        "episode": paths.episode, "episode_dir": str(paths.episode_dir),
        "cameras": cams, "mics": mics, "frames": frames,
        "delivery": {"fps": delivery_fps, "width": w, "height": hgt, "drop_frame": drop,
                     "nominal_fps": round(float(rate), 3)},
        "mic_duration_s": max(mic_durs), "warnings": warnings,
    }
    cache.save(paths.cache, "ingest", h, data)
    return data, False
