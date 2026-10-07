"""Carga de config.yaml y rutas de salida."""
from pathlib import Path
import copy
import re

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PROJECT_ROOT / "config.yaml"


def load_config(path=None, overrides=None):
    with open(path or DEFAULT_CONFIG, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if overrides:
        cfg = deep_merge(cfg, overrides)
    return cfg


def deep_merge(base, extra):
    out = copy.deepcopy(base)
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def parse_excerpt(spec):
    """'10m' | '90s' | '45m+10m' -> (inicio_s, duración_s) o None."""
    if not spec:
        return None

    def dur(s):
        m = re.fullmatch(r"(\d+(?:\.\d+)?)([hms]?)", s.strip())
        if not m:
            raise ValueError(f"--excerpt inválido: {spec!r} (usa 10m, 90s o 45m+10m)")
        return float(m.group(1)) * {"h": 3600, "m": 60, "s": 1, "": 1}[m.group(2)]

    if "+" in spec:
        a, b = spec.split("+", 1)
        return dur(a), dur(b)
    return 0.0, dur(spec)


class Paths:
    def __init__(self, cfg, episode_dir, excerpt=None):
        self.episode_dir = Path(episode_dir).expanduser().resolve()
        self.episode = self.episode_dir.name
        root = Path(cfg["output_root"])
        if not root.is_absolute():
            root = PROJECT_ROOT / root
        tag = self.episode if not excerpt else f"{self.episode}__excerpt_{excerpt.replace('+', '_')}"
        self.out = root / tag
        self.cache = self.out / "cache"
        self.frames = self.out / "frames"
        self.audio_processed = self.out / "audio_processed"
        for p in (self.out, self.cache, self.frames, self.audio_processed):
            p.mkdir(parents=True, exist_ok=True)

    @property
    def mapping(self):
        return self.out / "mapping.yaml"
