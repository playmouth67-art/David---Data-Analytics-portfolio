"""Criterios de aceptación verificados de forma independiente contra la verdad de terreno."""
import json
import xml.dom.minidom
from pathlib import Path

import opentimelineio as otio
import yaml

from podcast_agent import cli, edit_engine
from podcast_agent.errors import MappingError
from podcast_agent.timecode import parse_rate, sec_to_frame

FPS = parse_rate("30000/1001")


def test_zero_cuts_inside_words(pipeline, truth):
    """Contra las palabras de la verdad (no las del análisis): ninguna remoción toca una palabra que se queda."""
    edl = pipeline["edl"]
    for r in edl["removals"]:
        for w in truth["words"]:
            a, b = sec_to_frame(w["start"], FPS, "floor"), sec_to_frame(w["end"], FPS, "ceil")
            overlaps = a < r["src_end_f"] and b > r["src_start_f"]
            removed_filler = w["kind"] == "filler" and w.get("removable") and \
                a >= r["src_start_f"] - 1 and b <= r["src_end_f"] + 1
            assert not overlaps or removed_filler, (r, w)
    assert edl["qc"]["cuts_inside_words"] == []


def test_every_removable_filler_removed_or_reported(pipeline):
    edl, an = pipeline["edl"], pipeline["analysis"]
    rej = edl["rejected_removals"]
    for f in (f for f in an["fillers"] if f["removable"]):
        a, b = sec_to_frame(f["start"], FPS, "floor"), sec_to_frame(f["end"], FPS, "ceil")
        removed = any(r["src_start_f"] <= a and r["src_end_f"] >= b for r in edl["removals"])
        reported = any(r["src_start_f"] <= a + 1 and r["src_end_f"] >= b - 1 and r["why"] for r in rej)
        assert removed or reported, f
    assert edl["qc"]["fillers_removed"] == edl["qc"]["fillers_removable"]  # en el fixture todas caben


def test_shot_lengths(pipeline):
    edl = pipeline["edl"]
    for s in edl["video_track"]["shots"]:
        L = (s["rec_end_f"] - s["rec_start_f"]) / float(FPS)
        if s["exception"] == "reaction_laugh":
            assert L >= 0.6 - 1e-9
            continue
        assert 1.2 - 1e-9 <= L <= 6.0 + 1e-9, s
        if s["rec_start_f"] < sec_to_frame(60, FPS):
            assert L <= 4.0 + 1e-9, s


def test_every_join_hidden(pipeline):
    edl = pipeline["edl"]
    shots = edl["video_track"]["shots"]
    starts = {s["rec_start_f"]: i for i, s in enumerate(shots)}
    assert edl["joins"], "el fixture debe generar uniones"
    for j in edl["joins"]:
        i = starts[j]
        a, b = shots[i - 1], shots[i]
        assert a["camera"] != b["camera"] or a["zoom"] != b["zoom"], j
        if a["camera"] == b["camera"]:
            assert 1.10 <= max(a["zoom"], b["zoom"]) <= 1.15


def test_shots_never_cross_a_join_and_cover_timeline(pipeline):
    edl = pipeline["edl"]
    shots = edl["video_track"]["shots"]
    joins = set(edl["joins"])
    cur = 0
    for s in shots:
        if edl["sting"] and cur == edl["sting"]["rec_start_f"]:
            cur = edl["sting"]["rec_end_f"]
        assert s["rec_start_f"] == cur
        assert not any(s["rec_start_f"] < j < s["rec_end_f"] for j in joins)
        cur = s["rec_end_f"]
    assert cur == edl["record_duration_f"]


def test_audio_tracks_continuous_and_global(pipeline):
    tracks = pipeline["edl"]["audio_tracks"]
    assert len(tracks) == 2
    ref = [(c["src_start_f"], c["src_end_f"], c["rec_start_f"]) for c in tracks[0]["clips"]]
    for t in tracks[1:]:
        assert [(c["src_start_f"], c["src_end_f"], c["rec_start_f"]) for c in t["clips"]] == ref
    main = [c for c in ref if c[2] >= (pipeline["edl"]["sting"] or {"rec_end_f": 0})["rec_end_f"]]
    for (a0, b0, r0), (a1, b1, r1) in zip(main, main[1:]):
        assert r1 == r0 + (b0 - a0)  # sin huecos entre piezas


def test_reasons_and_jl(pipeline):
    shots = pipeline["edl"]["video_track"]["shots"]
    for s in shots[1:]:
        assert s["reason"] in edit_engine.REASONS
    offs = [s["offset"]["frames"] for s in shots if s.get("offset") and s["offset"]["type"] in ("J", "L")]
    assert offs, "debe haber J/L cuts"
    assert all(a != b for a, b in zip(offs, offs[1:]))
    for o in offs:
        assert 6 <= o <= 12 or -15 <= o <= -8


def test_video_mapping_corrects_drift(pipeline, truth):
    """Cada plano apunta al frame de cámara correcto según el offset/deriva reales (±1 frame)."""
    edl, ing = pipeline["edl"], pipeline["ingest"]
    cams = {c["id"]: c for c in ing["cameras"]}
    for s in edl["video_track"]["shots"]:
        ct = next(c for c in truth["cameras"] if c["file"] == Path(cams[s["camera"]]["path"]).name)
        mic_t = s["mic_src_f"] / float(FPS)
        true_cam_t = (mic_t - ct["offset_s"]) / (1 + ct["drift_ppm"] * 1e-6)
        assert abs(s["src_in_f"] - true_cam_t * float(FPS)) <= 1.0, s


def test_first_minute_and_cold_open(pipeline):
    edl = pipeline["edl"]
    assert edl["qc"]["first_minute_dead_air"] == 0
    co = edl["cold_open"]["src"]
    assert co and 15 <= (co[1] - co[0]) / float(FPS) <= 45
    assert edl["sting"]["rec_end_f"] - edl["sting"]["rec_start_f"] == sec_to_frame(1.0, FPS)
    # el momento también queda en su lugar original
    assert any(p["segment"] == "main" and p["src_a"] <= co[0] < p["src_b"] for p in edl["pieces"])


def test_markers(pipeline):
    m = pipeline["edl"]["markers"]
    colors = {x["color"] for x in m}
    assert {"Red", "Yellow", "Blue", "Green"} <= colors
    green = sorted(x["rec_f"] for x in m if x["color"] == "Green")
    gaps = [(b - a) / float(FPS) for a, b in zip(green, green[1:])]
    assert all(45 - 1e-6 <= g <= 90 + 1e-6 for g in gaps), gaps
    assert len({x["rec_f"] for x in m}) == len(m)  # Resolve no admite dos marcadores en el mismo frame


def test_viral_clips(pipeline):
    clips = json.loads((pipeline["paths"].out / "clips.json").read_text(encoding="utf-8"))["clips"]
    an = pipeline["analysis"]
    starts = {round(s["start"], 3) for s in an["sentences"]} | {round(w["start"], 3) for w in an["words"]}
    ends = {round(s["end"], 3) for s in an["sentences"]}
    assert 1 <= len(clips) <= 10
    for c in clips:
        assert 20 <= c["duration"] <= 90
        assert c["start"] in starts and c["end"] in ends
        assert set(c["breakdown"]) == {"energy", "pitch", "laughter", "rate", "semantic"}
        assert c["title_es"] and c["hook"]


def test_exports_match_edl(pipeline):
    edl, files = pipeline["edl"], pipeline["files"]
    n_shots = len(edl["video_track"]["shots"])
    n_audio = sum(len(t["clips"]) for t in edl["audio_tracks"])
    doc = xml.dom.minidom.parse(files["fcpxml"])
    clips = doc.getElementsByTagName("asset-clip")
    assert sum(1 for c in clips if c.getAttribute("srcEnable") == "video") == n_shots
    assert sum(1 for c in clips if c.getAttribute("srcEnable") == "audio") == n_audio
    assert len(doc.getElementsByTagName("marker")) == len(edl["markers"])
    tl = otio.adapters.read_from_file(files["otio"])
    v1 = [c for c in tl.tracks[0] if isinstance(c, otio.schema.Clip)]
    assert len(v1) == n_shots
    for c, s in zip(v1, edl["video_track"]["shots"]):
        assert c.range_in_parent().start_time.to_frames() == s["rec_start_f"]
        assert c.duration().to_frames() == s["rec_end_f"] - s["rec_start_f"]
    assert tl.duration().to_frames() == edl["record_duration_f"]


def test_mapping_required(pipeline):
    paths = pipeline["paths"]
    saved = paths.mapping.read_text(encoding="utf-8")
    try:
        m = yaml.safe_load(saved)
        m["confirmed"] = False
        paths.mapping.write_text(yaml.safe_dump(m), encoding="utf-8")
        try:
            edit_engine.load_mapping(paths, pipeline["ingest"], pipeline["analysis"])
            raise AssertionError("debió fallar")
        except MappingError as e:
            assert "confirmed" in str(e)
        m["confirmed"] = True
        m["ignore_mics"] = []
        m["speakers"] = m["speakers"][:1]
        paths.mapping.write_text(yaml.safe_dump(m), encoding="utf-8")
        try:
            edit_engine.load_mapping(paths, pipeline["ingest"], pipeline["analysis"])
            raise AssertionError("debió fallar")
        except MappingError as e:
            assert "Mics sin mapeo" in str(e)
    finally:
        paths.mapping.write_text(saved, encoding="utf-8")


def test_cli_dry_run_without_resolve(pipeline, episode_dir, out_root, capsys):
    rc = cli.main(["run", "--episode", str(episode_dir), "--dry-run", "--set", f"output_root={out_root}",
                   "--set", "transcription.backend=fixture"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "(caché)" in out  # todas las etapas se saltan si el hash no cambió
    assert (pipeline["paths"].out / "edl.json").exists()


def test_cli_resolve_stage_reports_clearly(pipeline, episode_dir, out_root, capsys):
    rc = cli.main(["run", "--episode", str(episode_dir), "--stage", "resolve", "--set", f"output_root={out_root}",
                   "--set", "transcription.backend=fixture"])
    err = capsys.readouterr().err
    assert rc == 2 and "Siguiente paso" in err
