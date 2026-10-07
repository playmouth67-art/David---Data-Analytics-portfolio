import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from podcast_agent import analyze, audio_clean, edit_engine, export, ingest, sync, viral  # noqa: E402
from podcast_agent.config import Paths, load_config  # noqa: E402
from tests.fixtures import make_episode, mapping_from_truth  # noqa: E402

CACHE = ROOT / "tests" / ".fixture_cache"


@pytest.fixture(scope="session")
def episode_dir():
    """Episodio sintético; se regenera solo si cambia el generador."""
    key = hashlib.sha256((ROOT / "tests" / "fixtures.py").read_bytes()).hexdigest()[:12]
    ep = CACHE / key / "EP_SYNTH"
    if not (ep / "_fixture_truth.json").exists():
        if CACHE.exists():
            shutil.rmtree(CACHE)
        make_episode(ep)
    return ep


@pytest.fixture(scope="session")
def truth(episode_dir):
    return json.loads((episode_dir / "_fixture_truth.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def out_root(tmp_path_factory):
    return tmp_path_factory.mktemp("output")


@pytest.fixture(scope="session")
def cfg(out_root):
    return load_config(overrides={"output_root": str(out_root), "transcription": {"backend": "fixture"}})


@pytest.fixture(scope="session")
def pipeline(episode_dir, cfg, truth):
    paths = Paths(cfg, episode_dir)
    ing, _ = ingest.run_ingest(paths, cfg)
    sy, _ = sync.run_sync(paths, cfg, ing)
    au, _ = audio_clean.run_audio(paths, cfg, ing)
    an, _ = analyze.run_analyze(paths, cfg, ing, au)
    arrays = analyze.load_arrays(paths)
    vi, _ = viral.run_viral(paths, cfg, an, arrays, au)
    paths.mapping.write_text(yaml.safe_dump(mapping_from_truth(truth, ing)), encoding="utf-8")
    edl, _ = edit_engine.run_edit(paths, cfg, ing, sy, au, an, arrays, vi)
    files = export.export_all(edl, ing, paths.out, f"AUTO_EDIT_{paths.episode}_v1")
    return {"paths": paths, "ingest": ing, "sync": sy, "audio": au, "analysis": an, "arrays": arrays,
            "viral": vi, "edl": edl, "files": files}
