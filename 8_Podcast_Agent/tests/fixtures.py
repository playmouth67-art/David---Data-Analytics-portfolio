"""Generador de episodios sintéticos con ffmpeg + numpy.

Crea: 2 mics aislados (con sangrado cruzado y piso de ruido), 3 "cámaras" con
audio de referencia (offsets conocidos 0.5 s, 3.2 s y -0.8 s; 50 ppm de deriva en
cam2), silencios, muletillas sueltas y pegadas ("este libro"), una pregunta con
pausa, un remate con risas, crosstalk, backchannels, cambio de tema y menciones.

La voz es sintética (armónicos con contorno de tono y sílabas); la verdad de
terreno (palabras con tiempos exactos) se guarda en _fixture_truth.json, que el
backend de transcripción `fixture` lee en lugar de Whisper.

Uso: python -m tests.fixtures --out /ruta/EP_SYNTH [--seconds 360]
"""
import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import fftconvolve

SR = 48000
FPS = "30000/1001"
SPEAKERS = {"S1": {"mic": "mic1", "f0": 118.0, "name": "Carlos"},
            "S2": {"mic": "mic2", "f0": 205.0, "name": "Laura"}}
CAMERAS = [  # nombre, offset (s), deriva (ppm), rol, timecode
    ("cam_wide", 0.5, 0.0, "wide", "00:59:58;00"),
    ("cam_carlos", 3.2, 50.0, "closeup:S1", "00:59:55;10"),
    ("cam_laura", -0.8, 0.0, "closeup:S2", "00:59:59;12"),
]

BANK = [
    "La verdad es que nunca pensé que esto iba a crecer tanto.",
    "Empezamos grabando en la sala de mi casa con un micrófono prestado.",
    "Al principio nadie nos escuchaba, ni nuestras familias.",
    "Lo más difícil fue aprender a editar todo solos.",
    "Cada semana subíamos un episodio aunque estuviéramos cansados.",
    "Un día nos escribió una persona de Monterrey para darnos las gracias.",
    "Ahí entendimos que lo que hacíamos sí le importaba a alguien.",
    "Hay que tener paciencia porque los resultados tardan.",
    "Yo creo que la constancia vale más que el talento.",
    "Nos equivocamos muchísimas veces y aprendimos de cada error.",
    "Ahora tenemos un equipo pequeño pero muy comprometido.",
    "Lo que más me gusta es platicar con gente que admiro.",
    "A veces la mejor idea sale de una plática sin guion.",
    "El año pasado hicimos un viaje a Oaxaca para grabar en vivo.",
    "Fue una experiencia que nos cambió la forma de trabajar.",
    "Mucha gente se rinde justo antes de que las cosas funcionen.",
    "Hay días en que no tienes ganas y aun así tienes que hacerlo.",
    "Lo importante es disfrutar el proceso y no solo el resultado.",
    "Me acuerdo perfecto del primer comentario negativo que recibimos.",
    "Al final ese comentario nos ayudó a mejorar el audio.",
    "Tenemos oyentes en España, en Colombia y en Argentina.",
    "Nunca imaginé que íbamos a llegar a cien episodios.",
    "La comunidad es lo que mantiene vivo este proyecto.",
    "Cada invitado trae una historia completamente distinta.",
    "Me gusta preparar las preguntas un día antes con calma.",
    "Hay temas que dan miedo tocar pero vale la pena hablarlos.",
    "El dinero llegó mucho después de lo que esperábamos.",
    "Lo primero que compramos fue una buena cámara.",
    "Todavía nos falta muchísimo por aprender.",
]


def syllables(word):
    return max(1, len(re.findall(r"[aeiouáéíóúü]+", word.lower())))


class Voice:
    def __init__(self, f0, rng):
        self.f0, self.rng = f0, rng

    def word(self, text, energy=1.0, kind="word"):
        rng = self.rng
        letters = sum(c.isalpha() for c in text)
        if kind == "filler_hum":
            dur = 0.45
        elif kind == "filler_eh":
            dur = 0.32
        else:
            dur = float(np.clip(0.09 + 0.058 * letters, 0.16, 0.75)) / (0.9 + 0.1 * energy)
        n = int(dur * SR)
        t = np.arange(n) / SR
        f0 = self.f0 * (1 + 0.06 * (energy - 1)) * rng.uniform(0.95, 1.05)
        wob = 0.02 if kind.startswith("filler") else 0.05 * energy
        f0c = f0 * (1 + wob * np.sin(2 * np.pi * rng.uniform(1.5, 3.5) * t + rng.uniform(0, 6)))
        phase = 2 * np.pi * np.cumsum(f0c) / SR
        nh = 3 if kind == "filler_hum" else 10
        v = sum(np.sin(k * phase) / k for k in range(1, nh + 1))
        syl = syllables(text) if kind == "word" else 1
        am = 0.45 + 0.55 * np.sin(np.pi * syl * t / dur) ** 2
        noise = rng.normal(0, 0.06, n) * (t < 0.04) if kind == "word" else 0
        env = np.minimum(1, np.minimum(t / 0.012, (dur - t) / 0.015)).clip(0, 1)
        amp = 0.16 * energy * (0.6 if kind.startswith("filler") else 1.0)
        return ((v * am + noise) * env * amp).astype(np.float32)

    def laugh(self, dur=1.4, energy=1.2):
        out = []
        while sum(len(x) for x in out) / SR < dur:
            n = int(0.11 * SR)
            t = np.arange(n) / SR
            ph = 2 * np.pi * self.f0 * 1.4 * t
            burst = (sum(np.sin(k * ph) / k for k in range(1, 6)) + self.rng.normal(0, 0.5, n))
            burst *= np.sin(np.pi * t / t[-1]) * 0.18 * energy
            out += [burst.astype(np.float32), np.zeros(int(0.075 * SR), np.float32)]
        return np.concatenate(out)


class Script:
    """Construye la línea de tiempo de habla con tiempos exactos."""

    def __init__(self, seed):
        self.rng = np.random.default_rng(seed)
        self.voices = {s: Voice(c["f0"], self.rng) for s, c in SPEAKERS.items()}
        self.events = []      # (speaker, start_s, audio)
        self.words = []       # verdad de terreno
        self.truth = {"dead_air": [], "keep_pause": [], "crosstalk": [], "laughter": [], "topic_change": [],
                      "mentions": [], "fillers": []}
        self.t = 0.6

    def gap(self, s):
        self.t += s

    def add_word(self, spk, text, energy=1.0, kind="word", at=None, removable=None):
        vk = {"filler_eh": "filler_eh", "filler_hum": "filler_hum"}.get(kind, "word")
        audio = self.voices[spk].word(text, energy, vk if kind.startswith("filler_") else "word")
        start = self.t if at is None else at
        self.events.append((spk, start, audio))
        w = {"speaker": spk, "mic": SPEAKERS[spk]["mic"], "text": text, "start": round(start, 4),
             "end": round(start + len(audio) / SR, 4), "kind": "filler" if kind.startswith("filler") else kind}
        if removable is not None:
            w["removable"] = removable
        self.words.append(w)
        if at is None:
            self.t = w["end"]
        return w

    def sentence(self, spk, text, energy=1.0, word_gap=(0.06, 0.12), at=None):
        if at is not None:
            self.t = at
        toks = text.split()
        for i, tok in enumerate(toks):
            self.add_word(spk, tok, energy)
            if i < len(toks) - 1:
                self.t += self.rng.uniform(*word_gap)
        return self.words[-1]["end"]

    def filler(self, spk, text, removable=True, gap_before=0.25, gap_after=0.3):
        self.t += gap_before
        kind = {"eh": "filler_eh", "ehh": "filler_eh", "mmm": "filler_hum"}.get(text.strip(".,").lower(), "filler_word")
        if text == "o sea":
            w1 = self.add_word(spk, "o", kind="filler_word", removable=removable)
            self.t += 0.05
            w2 = self.add_word(spk, "sea,", kind="filler_word", removable=removable)
            self.truth["fillers"].append({"text": "o sea", "start": w1["start"], "end": w2["end"],
                                          "removable": removable, "speaker": spk})
        else:
            w = self.add_word(spk, text, kind=kind, removable=removable)
            self.truth["fillers"].append({"text": text.strip(".,"), "start": w["start"], "end": w["end"],
                                          "removable": removable, "speaker": spk})
        self.t += gap_after

    def laugh(self, spk, at=None, dur=1.4):
        audio = self.voices[spk].laugh(dur)
        start = self.t if at is None else at
        self.events.append((spk, start, audio))
        self.words.append({"speaker": spk, "mic": SPEAKERS[spk]["mic"], "text": "jaja", "start": round(start, 4),
                           "end": round(start + len(audio) / SR, 4), "kind": "laugh"})
        self.truth["laughter"].append([round(start, 3), round(start + len(audio) / SR, 3), spk])
        return start + len(audio) / SR

    def dead_air(self, s):
        self.truth["dead_air"].append([round(self.t, 3), round(self.t + s, 3)])
        self.t += s

    def build(self, seconds):
        rng = self.rng
        S1, S2 = "S1", "S2"
        self.sentence(S1, "Bienvenidos a otro episodio del podcast.")
        self.gap(0.35)
        self.sentence(S1, "Hoy estoy con mi amiga Laura que viene desde Guadalajara.")
        self.truth["mentions"] += ["Laura", "Guadalajara"]
        self.gap(0.4)
        self.sentence(S2, "Gracias por invitarme, de verdad.")
        self.filler(S2, "eh")
        self.sentence(S2, "Estoy muy contenta de estar aquí.")
        self.gap(0.5)
        self.sentence(S1, "¿Cómo empezaste en todo esto?")
        q_end = self.t
        self.gap(1.6)
        self.truth["keep_pause"].append([round(q_end, 3), round(self.t, 3), "question"])
        # Monólogo largo de S2 con muletillas, "este libro" (no muletilla) y backchannel de S1.
        self.sentence(S2, "Mira, todo empezó cuando leí este libro sobre radio comunitaria.",
                      word_gap=(0.05, 0.07))
        self.gap(0.3)
        self.filler(S2, "este", gap_before=0.2, gap_after=0.4)
        self.sentence(S2, "Me di cuenta de que cualquiera podía contar historias.")
        self.gap(0.25)
        bc_at = self.t + 0.05
        self.add_word(S1, "ajá", energy=0.7, at=bc_at)
        self.gap(0.45)
        self.sentence(S2, "En dos años juntamos tres millones de descargas.")
        self.truth["mentions"] += ["tres millones"]
        self.gap(0.3)
        self.filler(S2, "mmm", gap_before=0.15, gap_after=0.35)
        self.sentence(S2, BANK[0])
        self.gap(0.3)
        self.sentence(S2, BANK[1])
        self.gap(0.3)
        self.sentence(S2, BANK[2])
        self.dead_air(1.5)
        self.filler(S1, "o sea", gap_before=0.0, gap_after=0.35)
        self.sentence(S1, "Eso es muchísimo para empezar desde cero.")
        self.gap(0.4)
        # Crosstalk: S2 entra mientras S1 sigue hablando.
        x0 = self.t
        end1 = self.sentence(S1, "Yo me acuerdo que en ese tiempo todo era mucho más difícil para todos.")
        self.sentence(S2, "No, no, espérate, déjame contarte lo que pasó ese día.", at=x0 + 0.9)
        self.truth["crosstalk"].append([round(x0 + 0.9, 3), round(min(end1, self.t), 3)])
        self.t = max(self.t, end1)
        self.gap(0.4)
        # Remate: pausa antes del punchline y risas.
        self.sentence(S2, "Llegamos a grabar al parque y un perro se robó el micrófono.")
        p0 = self.t
        self.gap(1.3)
        self.truth["keep_pause"].append([round(p0, 3), round(self.t, 3), "punchline"])
        end = self.sentence(S2, "Y resulta que el perro era del vecino.")
        self.gap(0.15)
        self.laugh(S1, dur=1.5)
        self.laugh(S2, at=end + 0.3, dur=1.2)
        self.gap(0.4)
        self.sentence(S1, "Está bueno eso, está muy bueno.")
        self.gap(0.3)
        self.filler(S1, "pues", gap_before=0.1, gap_after=0.35)
        self.sentence(S1, BANK[8])
        self.dead_air(1.2)
        # Momento "viral": alta energía.
        for txt in ["Nadie te dice esto, pero el secreto es que nunca vas a estar lista.",
                    "Yo perdí todo mi dinero en el primer año y aun así seguí.",
                    "Imagínate, tres veces nos cerraron el canal por error."]:
            self.sentence(S2, txt, energy=1.6, word_gap=(0.04, 0.08))
            self.gap(0.25)
        self.laugh(S1, dur=1.0)
        self.gap(0.3)
        self.sentence(S1, "No puede ser, eso es increíble.", energy=1.3)
        self.dead_air(1.8)
        # Cambio de tema.
        self.truth["topic_change"].append(round(self.t, 3))
        self.sentence(S1, "Cambiando de tema, hablemos de Netflix y de lo que pasó en 2019.")
        self.truth["mentions"] += ["Netflix", "2019"]
        self.gap(0.4)
        self.sentence(S2, "Bueno, ese año todo cambió para la industria del audio.")
        self.gap(0.3)
        self.filler(S2, "bueno", gap_before=0.1, gap_after=0.35)
        # Relleno aleatorio hasta la duración objetivo.
        spk = S1
        fillers = ["eh", "este", "mmm", "pues", "o sea", "bueno"]
        while self.t < seconds - 8:
            n = int(rng.integers(1, 7)) if rng.random() < 0.3 else int(rng.integers(1, 3))
            for k in range(n):
                if rng.random() < 0.18:
                    self.filler(spk, fillers[int(rng.integers(len(fillers)))])
                self.sentence(spk, BANK[int(rng.integers(len(BANK)))], energy=float(rng.uniform(0.85, 1.25)))
                if k < n - 1:
                    self.gap(float(rng.uniform(0.3, 0.55)))
                    if n > 3 and rng.random() < 0.3:
                        other = S2 if spk == S1 else S1
                        self.add_word(other, "sí", energy=0.7, at=self.t - 0.15)
            if rng.random() < 0.25:
                self.dead_air(float(rng.uniform(1.0, 2.2)))
            else:
                self.gap(float(rng.uniform(0.35, 0.6)))
            spk = S2 if spk == S1 else S1
        self.t += 1.0
        return self.t


def render(script, total_s, seed):
    rng = np.random.default_rng(seed + 1)
    n = int(total_s * SR)
    clean = {s: np.zeros(n, np.float32) for s in SPEAKERS}
    for spk, start, audio in script.events:
        i = int(round(start * SR))
        clean[spk][i: i + len(audio)] += audio[: max(0, n - i)]
    mics = {}
    for s, c in SPEAKERS.items():
        other = [o for o in SPEAKERS if o != s][0]
        bleed = np.roll(clean[other], int(0.004 * SR)) * 0.1  # -20 dB, 4 ms
        floor = rng.normal(0, 10 ** (-62 / 20), n).astype(np.float32)
        mics[c["mic"]] = clean[s] + bleed + floor
    return mics, clean


def camera_audio(mix, offset, drift_ppm, cam_dur, rng):
    """audio de cámara en t_cam = mezcla en t_mic = offset + t_cam·(1+deriva)."""
    ir = rng.normal(0, 1, int(0.12 * SR)) * np.exp(-np.arange(int(0.12 * SR)) / (0.03 * SR))
    ir *= np.sqrt(0.1 / np.sum(ir ** 2))   # reverb 10 dB por debajo del directo
    ir[0] += 1.0
    room = fftconvolve(mix, ir)[: len(mix)].astype(np.float32)
    t_cam = np.arange(int(cam_dur * SR)) / SR
    t_mic = offset + t_cam * (1 + drift_ppm * 1e-6)
    out = np.interp(t_mic * SR, np.arange(len(room)), room, left=0.0, right=0.0)
    out += rng.normal(0, 10 ** (-50 / 20), len(out))
    return (out * 0.8).astype(np.float32)


def _vcodec():
    enc = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    return ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "35"] if "libx264" in enc else ["-c:v", "mpeg4", "-q:v", "12"]


def make_video(out, audio_wav, dur, role, timecode, color):
    boxes = {
        "wide": "drawbox=x=120:y=150:w=110:h=170:color=0xd9a066:t=fill,drawbox=x=410:y=150:w=110:h=170:color=0xc98a5a:t=fill,"
                "drawbox=x=60:y=300:w=520:h=40:color=0x5a3d2b:t=fill",
        "closeup:S1": "drawbox=x=190:y=40:w=260:h=320:color=0xd9a066:t=fill",
        "closeup:S2": "drawbox=x=190:y=40:w=260:h=320:color=0xc98a5a:t=fill,drawbox=x=170:y=20:w=300:h=90:color=0x2b1a10:t=fill",
    }[role]
    vf = boxes + ",drawbox=x='mod(t*40,600)':y=10:w=30:h=8:color=white:t=fill"
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={color}:s=640x360:r={FPS}:d={dur:.3f}",
           "-i", str(audio_wav), "-vf", vf, *_vcodec(), "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le",
           "-timecode", timecode, "-shortest", str(out)]
    subprocess.run(cmd, check=True)


def make_episode(out_dir, seconds=360, seed=1, cameras=CAMERAS):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    script = Script(seed)
    total = script.build(seconds)
    mics, clean = render(script, total, seed)
    for mic, x in mics.items():
        sf.write(out_dir / f"{mic}.wav", x, SR, subtype="PCM_24")
    mix = sum(mics.values()) * 0.5
    rng = np.random.default_rng(seed + 2)
    colors = ["0x203040", "0x302020", "0x203020"]
    tmp = out_dir / "_tmp_cam"
    tmp.mkdir(exist_ok=True)
    cams_truth = []
    for (name, off, drift, role, tc), color in zip(cameras, colors):
        cam_dur = total - off + 1.0  # la cámara sigue grabando ~1 s después
        a = camera_audio(mix, off, drift, cam_dur, rng)
        wav = tmp / f"{name}.wav"
        sf.write(wav, a, SR, subtype="PCM_16")
        make_video(out_dir / f"{name}.mov", wav, cam_dur, role, tc, color)
        cams_truth.append({"file": f"{name}.mov", "offset_s": off, "drift_ppm": drift, "role": role})
    shutil.rmtree(tmp)
    truth = {"duration_s": total, "fps": FPS, "speakers": SPEAKERS, "cameras": cams_truth,
             "words": sorted(script.words, key=lambda w: w["start"]), **script.truth}
    (out_dir / "_fixture_truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=1), encoding="utf-8")
    return truth


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--seconds", type=float, default=360)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    t = make_episode(a.out, a.seconds, a.seed)
    print(f"Episodio sintético: {a.out} ({t['duration_s']:.1f} s, {len(t['words'])} palabras)")


if __name__ == "__main__":
    main()


def mapping_from_truth(truth, ingest):
    """mapping.yaml confirmado a partir de la verdad del fixture (en un episodio real lo confirma el usuario)."""
    by_file = {Path(c["path"]).name: c["id"] for c in ingest["cameras"]}
    mic_by_stem = {Path(m["path"]).stem: m["id"] for m in ingest["mics"]}
    speakers, wide = [], []
    for c in truth["cameras"]:
        if c["role"] == "wide":
            wide.append(by_file[c["file"]])
    for sid, s in truth["speakers"].items():
        cam = next(by_file[c["file"]] for c in truth["cameras"] if c["role"] == f"closeup:{sid}")
        speakers.append({"id": sid, "name": s["name"], "mic": mic_by_stem[s["mic"]], "camera": cam})
    return {"confirmed": True, "speakers": speakers, "wide": wide, "exclude_cameras": [], "ignore_mics": []}
