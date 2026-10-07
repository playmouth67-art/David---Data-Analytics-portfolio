from pathlib import Path


def test_audio_new_files_and_loudness(pipeline, episode_dir):
    au = pipeline["audio"]
    for p in au["tracks"].values():
        assert Path(p).exists() and "audio_processed" in p and str(episode_dir) not in p
    assert au["final"]["mix_tp_dbtp"] <= -1.0
    # La voz sintética tiene un techo de loudness a -1 dBTP; en voz real se apunta a -14 ±0.5.
    assert abs(au["final"]["mix_lufs"] + 14) <= 1.0
    assert all(abs(v) <= 1 for v in au["alignment_lag_samples_16k"].values())


def test_sources_untouched(pipeline, episode_dir, truth):
    # El generador escribe los archivos una vez; nada del pipeline vive dentro del episodio.
    names = {p.name for p in episode_dir.iterdir()}
    assert names == {"mic1.wav", "mic2.wav", "cam_wide.mov", "cam_carlos.mov", "cam_laura.mov", "_fixture_truth.json"}


def _match(a, b, tol=0.06):
    return abs(a - b) <= tol


def test_vad_threshold_adaptive(pipeline):
    for v in pipeline["analysis"]["vad"].values():
        assert not v["fallback"]
        assert abs(v["threshold_dbfs"] - (v["noise_floor_dbfs"] + 12)) < 0.11


def test_fillers_exact(pipeline, truth):
    an = pipeline["analysis"]
    got = [f for f in an["fillers"] if f["removable"]]
    want = [f for f in truth["fillers"] if f["removable"]]
    for w in want:
        assert any(_match(g["start"], w["start"]) and g["text"] == w["text"] for g in got), w
    for g in got:
        assert any(_match(g["start"], w["start"]) for w in want), f"falso positivo: {g}"
    # "este libro" y "está bueno" no se tocan
    este_libro = next(w for w in truth["words"] if w["text"] == "libro")
    assert not any(f["removable"] and abs(f["end"] - este_libro["start"]) < 0.2 for f in an["fillers"])


def test_dead_air_and_keep_pause(pipeline, truth):
    an = pipeline["analysis"]
    long_ones = [d for d in an["dead_air"] if not d["strict_only"]]
    for s, e in truth["dead_air"]:
        assert any(d["start"] <= s + 0.1 and d["end"] >= e - 0.1 for d in long_ones), (s, e)
    reasons = {k["reason"] for k in an["keep_pauses"]}
    assert reasons == {"question", "punchline"}
    for s, e, why in truth["keep_pause"]:
        assert any(_match(k["start"], s, 0.15) and k["reason"] == why for k in an["keep_pauses"])
        assert not any(d["cut_start"] < e and d["cut_end"] > s for d in an["dead_air"])


def test_crosstalk_topics_laughter_mentions(pipeline, truth):
    an = pipeline["analysis"]
    for s, e in truth["crosstalk"]:
        assert any(a < e and b > s for a, b in an["crosstalk"])
    assert any(abs(t["time"] - truth["topic_change"][0]) < 0.6 for t in an["topics"])
    assert len([l for l in an["laughter"]]) >= len(truth["laughter"])
    texts = {m["text"] for m in an["mentions"]}
    for m in ("Laura", "Guadalajara", "Netflix", "2019", "tres millones"):
        assert m in texts


def test_speaker_evidence_names_guest(pipeline):
    ev = pipeline["analysis"]["speaker_evidence"]
    assert "Laura" in ev["mic2"]["probably_named"]
