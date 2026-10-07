"""Helpers de ffmpeg/ffprobe. Nada escribe sobre los archivos de origen."""
import json
import shutil
import subprocess

import numpy as np

from .errors import FfmpegMissing, AgentError


def require_ffmpeg():
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise FfmpegMissing(f"No encuentro `{tool}` en el PATH.")


def run(cmd, what="ffmpeg"):
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        tail = proc.stderr.decode(errors="replace").strip().splitlines()[-6:]
        raise AgentError(f"{what} falló: {' '.join(map(str, cmd[:6]))}…\n" + "\n".join(tail),
                         "Revisa que el archivo no esté dañado y que ffmpeg tenga el filtro necesario.")
    return proc


def ffprobe(path):
    proc = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
               "ffprobe")
    return json.loads(proc.stdout)


def _input_args(path, start=None, dur=None):
    args = []
    if start:
        args += ["-ss", f"{start:.6f}"]
    if dur:
        args += ["-t", f"{dur:.6f}"]
    return args + ["-i", str(path)]


def decode_audio(path, sr, start=None, dur=None, channel=None, mono=True):
    """Decodifica a float32 [-1, 1]. channel=N extrae un canal; mono=True suma a mono."""
    cmd = ["ffmpeg", "-v", "error", "-nostdin"] + _input_args(path, start, dur)
    if channel is not None:
        cmd += ["-af", f"pan=mono|c0=c{int(channel)}"]
    elif mono:
        cmd += ["-ac", "1"]
    cmd += ["-ar", str(sr), "-f", "f32le", "-"]
    proc = run(cmd, "decodificar audio")
    return np.frombuffer(proc.stdout, dtype=np.float32).copy()


def decode_mix(sources, sr, start=None, dur=None):
    """Mezcla mono (suma) de varias fuentes [(path, channel|None)], recortada a [start, start+dur]."""
    if len(sources) == 1:
        p, ch = sources[0]
        return decode_audio(p, sr, start, dur, channel=ch)
    out = None
    for p, ch in sources:
        x = decode_audio(p, sr, start, dur, channel=ch)
        if out is None:
            out = x
        else:
            n = max(len(out), len(x))
            out = np.pad(out, (0, n - len(out))) + np.pad(x, (0, n - len(x)))
    return out


def stream_audio(path, sr, channel=None, block_s=60.0, start=None, dur=None):
    """Generador de bloques float32 para archivos largos (no carga 3 h en RAM)."""
    cmd = ["ffmpeg", "-v", "error", "-nostdin"] + _input_args(path, start, dur)
    cmd += (["-af", f"pan=mono|c0=c{int(channel)}"] if channel is not None else ["-ac", "1"])
    cmd += ["-ar", str(sr), "-f", "f32le", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    nbytes = int(block_s * sr) * 4
    try:
        while True:
            buf = proc.stdout.read(nbytes)
            if not buf:
                break
            yield np.frombuffer(buf[: len(buf) - len(buf) % 4], dtype=np.float32)
    finally:
        proc.stdout.close()
        proc.wait()


def extract_frame(video, out_png, at_s):
    run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-ss", f"{at_s:.3f}", "-i", str(video),
         "-frames:v", "1", str(out_png)], "exportar frame")
