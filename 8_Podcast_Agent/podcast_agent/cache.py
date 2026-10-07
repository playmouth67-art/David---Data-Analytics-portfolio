"""Caché por etapa: cada etapa escribe cache/<etapa>.json y se salta si el hash de entrada no cambió."""
import hashlib
import json
from pathlib import Path

import numpy as np


def _default(o):
    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


def file_signature(path):
    p = Path(path)
    st = p.stat()
    return [str(p), st.st_size, int(st.st_mtime)]


def code_hash(*modules):
    """Hash del código de los módulos de una etapa: cambiar el código invalida solo esa etapa."""
    here = Path(__file__).resolve().parent
    h = hashlib.sha256()
    for m in modules:
        h.update((here / f"{m}.py").read_bytes())
    return h.hexdigest()[:12]


def input_hash(*parts):
    h = hashlib.sha256()
    for part in parts:
        h.update(json.dumps(part, sort_keys=True, default=_default).encode())
    return h.hexdigest()[:16]


def load(cache_dir, stage, expected_hash):
    p = Path(cache_dir) / f"{stage}.json"
    if not p.exists():
        return None
    try:
        blob = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if blob.get("input_hash") != expected_hash:
        return None
    return blob["data"]


def save(cache_dir, stage, h, data):
    p = Path(cache_dir) / f"{stage}.json"
    p.write_text(json.dumps({"input_hash": h, "data": data}, ensure_ascii=False, indent=1, default=_default), encoding="utf-8")
    return p


def read_data(cache_dir, stage):
    p = Path(cache_dir) / f"{stage}.json"
    return json.loads(p.read_text(encoding="utf-8"))["data"]


def stage_hash(cache_dir, stage):
    p = Path(cache_dir) / f"{stage}.json"
    return json.loads(p.read_text(encoding="utf-8"))["input_hash"]
