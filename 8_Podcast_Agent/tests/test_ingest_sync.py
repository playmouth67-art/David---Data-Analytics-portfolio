from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from podcast_agent import ingest, media, sync
from podcast_agent.config import Paths
from podcast_agent.errors import EmptyEpisode, FfmpegMissing, SyncError
from podcast_agent.timecode import parse_rate

FPS = float(parse_rate("30000/1001"))


def test_ingest_detects_everything(pipeline):
    ing = pipeline["ingest"]
    assert len(ing["cameras"]) == 3 and len(ing["mics"]) == 2
    assert ing["delivery"] == {"fps": "30000/1001", "width": 640, "height": 360, "drop_frame": True, "nominal_fps": 29.97}
    assert all(c["timecode"] and c["drop_frame"] for c in ing["cameras"])
    assert all(Path(p).exists() for p in ing["frames"].values())


def test_empty_episode(tmp_path, cfg):
    ep = tmp_path / "EP_EMPTY"
    ep.mkdir()
    with pytest.raises(EmptyEpisode):
        ingest.run_ingest(Paths(cfg, ep), cfg)


def test_ffmpeg_missing(monkeypatch):
    monkeypatch.setattr(media.shutil, "which", lambda name: None)
    with pytest.raises(FfmpegMissing) as e:
        media.require_ffmpeg()
    assert "brew install ffmpeg" in e.value.render()


def _true_offset(cam_truth, cam_t):
    return cam_truth["offset_s"] + cam_truth["drift_ppm"] * 1e-6 * cam_t


def test_sync_offsets_and_drift_within_one_frame(pipeline, truth):
    ing, sy = pipeline["ingest"], pipeline["sync"]
    for cam in ing["cameras"]:
        ct = next(c for c in truth["cameras"] if c["file"] == Path(cam["path"]).name)
        clock = sync.CameraClock(sy["cameras"][cam["id"]])
        for cam_t in np.linspace(1, cam["duration_s"] - 1, 25):
            err = abs(clock.offset_at_cam(cam_t) - _true_offset(ct, cam_t)) * FPS
            assert err <= 1.0, (cam["id"], cam_t, err)
        assert abs(sy["cameras"][cam["id"]]["drift_ppm"] - ct["drift_ppm"]) < 5


def _fake_cam(tmp_path, mix, sr, offset, drift_ppm, dur, name):
    t_cam = np.arange(int(dur * sr)) / sr
    x = np.interp((offset + t_cam * (1 + drift_ppm * 1e-6)) * sr, np.arange(len(mix)), mix, left=0, right=0)
    x = x + np.random.default_rng(0).normal(0, 0.003, len(x))
    p = tmp_path / f"{name}.wav"
    sf.write(p, x.astype(np.float32), sr)
    return {"id": name, "name": name, "path": str(p), "duration_s": dur, "scratch_audio": {"channels": 1}}


def test_large_drift_corrected_per_shot(pipeline, tmp_path, cfg):
    """400 ppm (≈5 frames en 6 min): el modelo lineal la absorbe y cada plano queda a ≤1 frame."""
    mics = pipeline["ingest"]["mics"]
    sr = 16000
    mix = media.decode_mix([(m["path"], m["channel"]) for m in mics], sr)
    dur = len(mix) / sr - 3
    cam = _fake_cam(tmp_path, mix, sr, 1.3, 400.0, dur, "cam_drift")
    r = sync.sync_camera(cam, mics, len(mix) / sr, parse_rate("30000/1001"), cfg["sync"])
    assert r["drift_over_file_frames"] > 1.0 and r["drift_corrected"]
    clock = sync.CameraClock(r)
    for mic_t in np.linspace(5, dur - 5, 30):
        true_cam_t = (mic_t - 1.3) / (1 + 400e-6)
        assert abs(clock.cam_time(mic_t) - true_cam_t) * FPS <= 1.0


def test_low_confidence_stops(pipeline, tmp_path, cfg):
    mics = pipeline["ingest"]["mics"]
    p = tmp_path / "noise.wav"
    sf.write(p, np.random.default_rng(3).normal(0, 0.1, 16000 * 200).astype(np.float32), 16000)
    cam = {"id": "camX", "name": "noise", "path": str(p), "duration_s": 200.0, "scratch_audio": {"channels": 1}}
    with pytest.raises(SyncError) as e:
        sync.sync_camera(cam, mics, pipeline["ingest"]["mic_duration_s"], parse_rate("30000/1001"), cfg["sync"])
    assert "Confianza de sync baja" in str(e.value) or "solapan" in str(e.value)
