"""Backends de transcripción verbatim con timestamps por palabra.

- mlx:     mlx-whisper (Apple Silicon, Metal).
- faster:  faster-whisper (Intel / CUDA / CPU). Sin GPU usa un modelo más chico y avisa.
- fixture: lee la verdad de terreno del generador sintético (_fixture_truth.json).
Cada backend devuelve [{text, start, end, prob}] en segundos del timeline de mics.
"""
import importlib.util
import json
import platform
from pathlib import Path

from .errors import TranscriptionUnavailable


def _has(mod):
    return importlib.util.find_spec(mod) is not None


def _faster_choice():
    """(clave de modelo, aviso) para faster-whisper según haya GPU CUDA o no."""
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            return "faster_model", None
    except Exception:  # noqa: BLE001 - sin CUDA es el caso normal en Mac
        pass
    return "faster_model_no_gpu", "Sin GPU: se usa un modelo de Whisper más chico (más lento y menos preciso)."


def detect_device():
    """(backend, clave de modelo, aviso)."""
    if platform.system() == "Darwin" and platform.machine() == "arm64" and _has("mlx_whisper"):
        return "mlx", "mlx_model", None
    if _has("faster_whisper"):
        key, warn = _faster_choice()
        if platform.system() == "Darwin" and platform.machine() == "arm64":
            warn = "Apple Silicon sin mlx-whisper: faster-whisper en CPU con modelo chico. Instala mlx-whisper para Metal."
        return "faster", key, warn
    raise TranscriptionUnavailable("No hay backend de transcripción instalado (mlx-whisper / faster-whisper).")


def transcribe_fixture(episode_dir, mic, offset_s, window):
    truth = json.loads((Path(episode_dir) / "_fixture_truth.json").read_text(encoding="utf-8"))
    stem = Path(mic["path"]).stem
    t0, t1 = window
    return [{"text": w["text"], "start": w["start"], "end": w["end"], "prob": 1.0}
            for w in truth["words"] if w["mic"] == stem and t0 <= w["start"] < t1]


def transcribe_mlx(wav, model, prompt, offset_s):
    import mlx_whisper
    res = mlx_whisper.transcribe(str(wav), path_or_hf_repo=model, language="es", word_timestamps=True,
                                 initial_prompt=prompt, condition_on_previous_text=False)
    return [{"text": w["word"].strip(), "start": w["start"] + offset_s, "end": w["end"] + offset_s,
             "prob": w.get("probability", 1.0)} for seg in res["segments"] for w in seg.get("words", [])]


def transcribe_faster(wav, model, prompt, offset_s):
    from faster_whisper import WhisperModel
    m = WhisperModel(model, device="auto", compute_type="int8")
    segments, _ = m.transcribe(str(wav), language="es", word_timestamps=True, initial_prompt=prompt,
                               condition_on_previous_text=False, vad_filter=False)
    return [{"text": w.word.strip(), "start": w.start + offset_s, "end": w.end + offset_s, "prob": w.probability}
            for seg in segments for w in (seg.words or [])]


def transcribe(backend, tcfg, wav, mic, episode_dir, offset_s, window):
    if backend == "fixture":
        return transcribe_fixture(episode_dir, mic, offset_s, window)
    if backend == "mlx":
        return transcribe_mlx(wav, tcfg["mlx_model"], tcfg["initial_prompt"], offset_s)
    if backend == "faster":
        return transcribe_faster(wav, tcfg["_faster_model"], tcfg["initial_prompt"], offset_s)
    raise TranscriptionUnavailable(f"Backend desconocido: {backend}")


def resolve_backend(tcfg):
    """Devuelve (backend, aviso) y deja el modelo de faster-whisper en tcfg['_faster_model']."""
    b = tcfg["backend"]
    if b == "fixture":
        return "fixture", None
    if b == "auto":
        b, key, warn = detect_device()
    elif b == "mlx":
        if not _has("mlx_whisper"):
            raise TranscriptionUnavailable("Pediste mlx pero mlx-whisper no está instalado.")
        return "mlx", None
    elif b == "faster":
        if not _has("faster_whisper"):
            raise TranscriptionUnavailable("Pediste faster pero faster-whisper no está instalado.")
        key, warn = _faster_choice()
    else:
        raise TranscriptionUnavailable(f"Backend desconocido: {b}")
    if b == "faster":
        tcfg["_faster_model"] = tcfg[key]
    return b, warn
