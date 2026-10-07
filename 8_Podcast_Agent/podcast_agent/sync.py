"""Sync: audio de referencia de cada cámara contra la mezcla de mics.

Modelo: mic_t = cam_t + offset(cam_t). Lineal: offset = a + b·cam_t (b = deriva).
Si el residuo lineal supera 1 frame se densifican ventanas y se usa un modelo
por tramos (equivale a "partir en segmentos"); como cada plano del timeline se
mapea por separado con este modelo, la deriva queda corregida plano a plano.
"""
import numpy as np
from scipy.signal import butter, sosfilt, sosfiltfilt

from . import cache, media
from .errors import SyncError, DriftError
from .timecode import parse_rate


def _sources(mics):
    return [(m["path"], m["channel"]) for m in mics]


def envelope(x, sr, band, lp):
    if len(x) < sr // 10:
        return np.zeros_like(x)
    sos = butter(4, band, btype="band", fs=sr, output="sos")
    env = np.abs(sosfiltfilt(sos, x))
    env = sosfiltfilt(butter(2, lp, fs=sr, output="sos"), env)
    return env - env.mean()


def coarse_envelope(path, channel, sr, band, env_hz):
    """Envolvente de todo el archivo a env_hz, en streaming (no carga horas en RAM)."""
    sos = butter(4, band, btype="band", fs=sr, output="sos")
    zi = np.zeros((sos.shape[0], 2))
    step = sr // env_hz
    out, rest = [], np.zeros(0, dtype=np.float32)
    for block in media.stream_audio(path, sr, channel=channel):
        y, zi = sosfilt(sos, block, zi=zi)
        y = np.concatenate([rest, np.abs(y)])
        n = len(y) // step
        out.append(y[: n * step].reshape(n, step).mean(axis=1))
        rest = y[n * step:]
    return np.concatenate(out) if out else np.zeros(0)


def sum_padded(arrays):
    n = max(len(a) for a in arrays)
    return sum(np.pad(a, (0, n - len(a))) for a in arrays)


def _norm(x):
    x = x - x.mean()
    s = x.std()
    return x / s if s > 0 else x


def xcorr_full(ref, sig):
    """corr[k] = Σ ref[n+k]·sig[n] para k en [-(len(sig)-1), len(ref)-1]. Devuelve (lags, corr)."""
    n = len(ref) + len(sig)
    nfft = 1 << (n - 1).bit_length()
    c = np.fft.irfft(np.fft.rfft(ref, nfft) * np.conj(np.fft.rfft(sig, nfft)), nfft)
    corr = np.concatenate([c[-(len(sig) - 1):], c[: len(ref)]]) if len(sig) > 1 else c[: len(ref)]
    lags = np.arange(-(len(sig) - 1), len(ref))
    return lags, corr


def _parabolic(y, i):
    if 0 < i < len(y) - 1:
        a, b, c = y[i - 1], y[i], y[i + 1]
        d = a - 2 * b + c
        if d != 0:
            return i + 0.5 * (a - c) / d
    return float(i)


def measure_window(cam, cam_ch, mics, cam_t, wlen, coarse_off, scfg, mic_dur):
    """Offset fino en una ventana. Devuelve dict con offset, corr de Pearson y relación de picos."""
    sr = scfg["analysis_sr"]
    band, lp, margin = scfg["bandpass_hz"], scfg["envelope_lowpass_hz"], scfg["search_margin_s"]
    m0 = max(0.0, cam_t + coarse_off - margin)
    m1 = min(mic_dur, cam_t + coarse_off + wlen + margin)
    c_env = envelope(media.decode_audio(cam, sr, cam_t, wlen, channel=cam_ch), sr, band, lp)
    m_env = envelope(media.decode_mix(_sources(mics), sr, m0, m1 - m0), sr, band, lp)
    if len(m_env) <= len(c_env) or c_env.std() == 0 or m_env.std() == 0:
        return {"cam_t": cam_t + wlen / 2, "offset": None, "corr": 0.0, "ratio": 0.0, "ok": False}
    lags, corr = xcorr_full(m_env, c_env)
    valid = (lags >= 0) & (lags <= len(m_env) - len(c_env))
    lags, corr = lags[valid], corr[valid]
    i = int(np.argmax(corr))
    k = _parabolic(corr, i)
    seg = m_env[lags[i]: lags[i] + len(c_env)]
    pearson = float(np.corrcoef(seg, c_env)[0, 1])
    guard = int(0.05 * sr)
    side = np.concatenate([corr[: max(0, i - guard)], corr[i + guard:]])
    ratio = float(corr[i] / side.max()) if len(side) and side.max() > 0 else float("inf")
    offset = m0 + (lags[0] + k) / sr - cam_t
    return {"cam_t": cam_t + wlen / 2, "offset": float(offset), "corr": pearson, "ratio": ratio}


def window_starts(valid0, valid1, wlen, n):
    span = valid1 - valid0 - wlen
    if span <= 0:
        return [valid0]
    edge = min(5.0, span / 10)
    return list(np.linspace(valid0 + edge, valid1 - wlen - edge, n))


def fit_linear(points):
    t = np.array([p["cam_t"] for p in points])
    o = np.array([p["offset"] for p in points])
    if len(t) >= 2 and np.ptp(t) > 0:
        b, a = np.polyfit(t, o, 1)
    else:
        a, b = float(o.mean()), 0.0
    resid = o - (a + b * t)
    return float(a), float(b), resid


def sync_camera(cam, mics, mic_dur, fps, scfg):
    sr = scfg["analysis_sr"]
    if not cam["scratch_audio"]:
        raise SyncError(f"La cámara {cam['id']} ({cam['name']}) no tiene audio de referencia.")
    band = scfg["bandpass_hz"]
    env_hz = scfg["coarse_env_hz"]

    # 1) Búsqueda gruesa sobre todo el archivo.
    c_env = _norm(coarse_envelope(cam["path"], None, sr, band, env_hz))
    m_env = _norm(sum_padded([coarse_envelope(p, ch, sr, band, env_hz) for p, ch in _sources(mics)]))
    lags, corr = xcorr_full(m_env, c_env)
    coarse_off = float(lags[int(np.argmax(corr))]) / env_hz

    # 2) Ventanas finas sobre el tramo que comparten cámara y mics.
    cam_dur = cam["duration_s"]
    valid0, valid1 = max(0.0, -coarse_off), min(cam_dur, mic_dur - coarse_off)
    if valid1 - valid0 < scfg["window_len_s"]:
        raise SyncError(f"{cam['id']}: la cámara y los mics casi no se solapan "
                        f"(offset grueso {coarse_off:+.2f} s).")
    wlen = scfg["window_len_s"]
    n = max(scfg["min_windows"], int((valid1 - valid0) // scfg["window_every_s"]) + 1)
    points = [measure_window(cam["path"], None, mics, t, wlen, coarse_off, scfg, mic_dur)
              for t in window_starts(valid0, valid1, wlen, n)]
    for p in points:
        p["ok"] = p.get("offset") is not None and p["corr"] >= scfg["min_peak_corr"] \
            and p["ratio"] >= scfg["min_peak_ratio"]
    good = [p for p in points if p["ok"]]
    if len(good) < scfg["min_windows"]:
        detail = ", ".join(f"t={p['cam_t']:.0f}s corr={p['corr']:.2f} ratio={p['ratio']:.2f}" for p in points)
        raise SyncError(f"Confianza de sync baja en {cam['id']} ({cam['name']}): "
                        f"{len(good)}/{len(points)} ventanas válidas. {detail}")

    tol = scfg["max_residual_frames"]
    a, b, resid = fit_linear(good)
    resid_frames = float(np.max(np.abs(resid)) * float(fps))
    model, warnings = "linear", []
    if resid_frames > tol:
        # 3) Deriva no lineal: densificar y usar tramos, validando con leave-one-out.
        n2 = max(n * 3, int((valid1 - valid0) // 120) + 1)
        extra = [measure_window(cam["path"], None, mics, t, wlen, coarse_off, scfg, mic_dur)
                 for t in window_starts(valid0, valid1, wlen, n2)]
        for p in extra:
            p["ok"] = p.get("offset") is not None and p["corr"] >= scfg["min_peak_corr"] \
                and p["ratio"] >= scfg["min_peak_ratio"]
        good = sorted([p for p in points + extra if p["ok"]], key=lambda p: p["cam_t"])
        t = np.array([p["cam_t"] for p in good])
        o = np.array([p["offset"] for p in good])
        loo = [abs(o[i] - np.interp(t[i], np.delete(t, i), np.delete(o, i))) * float(fps)
               for i in range(1, len(t) - 1)]
        if not loo or max(loo) > 2 * tol:
            raise DriftError(f"{cam['id']}: deriva no corregible (residuo lineal {resid_frames:.2f} frames, "
                             f"error por tramos {max(loo) if loo else float('nan'):.2f} frames).")
        model = "piecewise"
        points = points + extra
        resid_frames = float(max(loo))
        warnings.append(f"Deriva no lineal en {cam['id']}: modelo por tramos con {len(good)} puntos.")

    drift_total_frames = abs(b) * cam_dur * float(fps)
    return {
        "id": cam["id"], "model": model, "offset_s": a, "drift_ppm": b * 1e6, "coarse_offset_s": coarse_off,
        "residual_frames": resid_frames, "drift_over_file_frames": drift_total_frames,
        "drift_corrected": drift_total_frames > tol,  # corrección por plano en edit_engine
        "points": sorted(points, key=lambda p: p["cam_t"]),
        "mic_coverage_s": [max(0.0, a), min(mic_dur, a + cam_dur * (1 + b))],
        "warnings": warnings,
    }


class CameraClock:
    """Convierte tiempo de mic <-> tiempo de cámara con el modelo medido."""

    def __init__(self, s):
        self.model = s["model"]
        self.a, self.b = s["offset_s"], s["drift_ppm"] / 1e6
        pts = [p for p in s["points"] if p.get("ok")]
        self.t = np.array([p["cam_t"] for p in pts])
        self.o = np.array([p["offset"] for p in pts])

    def offset_at_cam(self, cam_t):
        if self.model == "piecewise":
            return float(np.interp(cam_t, self.t, self.o))
        return self.a + self.b * cam_t

    def cam_time(self, mic_t):
        if self.model == "piecewise":
            mic_pts = self.t + self.o
            return float(mic_t - np.interp(mic_t, mic_pts, self.o))
        return (mic_t - self.a) / (1 + self.b)


def run_sync(paths, cfg, ingest, force=False):
    scfg = cfg["sync"]
    h = cache.input_hash("sync", cache.code_hash("sync", "media"), cache.stage_hash(paths.cache, "ingest"), scfg)
    cached = None if force else cache.load(paths.cache, "sync", h)
    if cached:
        return cached, True
    fps = parse_rate(ingest["delivery"]["fps"])
    res = {"cameras": {}, "warnings": []}
    for cam in ingest["cameras"]:
        r = sync_camera(cam, ingest["mics"], ingest["mic_duration_s"], fps, scfg)
        res["cameras"][cam["id"]] = r
        res["warnings"] += r["warnings"]
    cache.save(paths.cache, "sync", h, res)
    return res, False
