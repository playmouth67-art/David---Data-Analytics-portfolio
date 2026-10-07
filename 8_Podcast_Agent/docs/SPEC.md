# Especificación original (texto del usuario, sin cambios)

> Este es el encargo completo tal como lo escribió el usuario. Es la referencia de reglas, umbrales,
> criterios de aceptación y condiciones de STOP. El estado actual está en `docs/HANDOFF.md`.

## Objective
Build `podcast_agent`, a local Python tool that turns raw multicam video and isolated mic tracks from long-form podcasts (60–180 min) into an edited, retention-optimized timeline in DaVinci Resolve Studio. The result must feel cut by a human editor with cinematic judgment. It must not feel like an automatic switcher: no dead air, no static shots, a strong hook, invisible cuts.

## Context
- Machine: macOS (verify Apple Silicon vs Intel in Phase 0).
- Media root (READ-ONLY): /Users/davicho/Downloads/podcasts/
  - Each episode lives in its own subfolder (e.g. podcasts/EP01/) with all camera files and mic tracks together.
  - The CLI takes the episode folder: `--episode /Users/davicho/Downloads/podcasts/EP01`
  - The folder is EMPTY right now. Build and test everything on synthetic fixtures, then stop and tell me to drop in an episode.
- Auto-detect, don't ask me: number of cameras and mics, fps, resolution, timecode, channels, Resolve version (and whether it's Studio), GPU.
- Camera roles and speaker map:
  - Export one frame per camera to output/frames/ and look at them. Propose which camera is the wide and which close-up belongs to whom.
  - Propose which mic belongs to which person by matching each mic's speech activity to the transcript.
  - Show me the proposal and WAIT for my OK.
- Language: Mexican Spanish. Fillers to detect, standalone only: "eh", "ehh", "este", "mmm", "o sea", "pues", "bueno".
- Working dir: ~/podcast_agent. Outputs: ~/podcast_agent/output/<episode>/.
- Resolve project: create a new one called "PODCAST_AUTO".
- Delivery: same fps and resolution as the source cameras. Loudness: -14 LUFS integrated, -1 dBTP.

## Resolve API reality (design around this, verify in Phase 0)
- Before writing ANY API call, read:
  /Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/README.txt
  Use only methods documented there for the installed version. NEVER invent methods.
- External scripting requires Studio and Preferences > System > General > External scripting = Local.
- Environment setup, following the README:
  - RESOLVE_SCRIPT_API="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
  - RESOLVE_SCRIPT_LIB="/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
  - PYTHONPATH="$PYTHONPATH:$RESOLVE_SCRIPT_API/Modules/"
  - Use a Python version the installed Resolve supports.
- The API cannot create multicam clips, add video transitions or control Fairlight FX. Build the edit as data and pick ONE integration path that Phase 0 proves works:
  (a) Export OTIO or FCPXML, then `MediaPool.ImportTimelineFromFile`, or
  (b) `MediaPool.AppendToTimeline` with clipInfo dicts (startFrame, endFrame, trackIndex, recordFrame, mediaType).
- Markers: `Timeline.AddMarker`. Punch-ins: `TimelineItem.SetProperty` (ZoomX/ZoomY/Pan/Tilt), only if the README confirms them.
- If Resolve is the free version or the API is unreachable: still export OTIO/FCPXML for manual import (File → Import → Timeline) and tell me.
- Audio cleanup happens BEFORE Resolve, with ffmpeg, into new files in output/<episode>/audio_processed/. Never write in place.

## Timeline architecture
- Each mic on its own audio track, continuous. Audio is cut only by GLOBAL removals (dead air, fillers) that apply to every track at once.
- Video V1 switches independently of the audio. J-cuts and L-cuts come from offsetting video against continuous audio.
- `edl.json` is the single source of truth. Every cut has a reason: speaker_change, monologue_break, reaction, filler_hide, silence_cut, topic_change, crosstalk_wide, cold_open.

## Edit rules
Sync and audio:
1. Sync each camera's scratch audio to the mic mix with FFT cross-correlation on band-passed envelopes resampled to ~8 kHz.
   - Measure the offset in ≥3 windows (start, middle, end) and fit linear drift.
   - Accept if the residual is ≤1 frame. If drift is >1 frame, correct it with aresample or by splitting into segments.
   - If peak confidence is low, STOP and report.
2. Per-mic VAD: adaptive threshold = noise floor + 12 dB, with -40 dBFS as fallback.
   - Reject bleed: a mic is "active" only if it beats every other mic by ≥6 dB in that window.
   - Use pyannote only if two speakers share one mic.
3. Transcribe each mic in verbatim mode with word-level timestamps.
   - On Apple Silicon, prefer mlx-whisper or whisper.cpp (Metal). Otherwise use faster-whisper.
   - Use WhisperX alignment if the timestamps are loose.
   - Include the fillers in initial_prompt so they don't get dropped.
4. Dead air: cut only when ALL mics are below threshold for >0.8 s.
   - Leave 0.25 s of natural pause.
   - NEVER cut inside a word.
   - Do NOT cut pauses after a question or before a punchline; mark them KEEP_PAUSE.
5. Fillers: remove only standalone fillers, with ≥0.1 s clearance on both sides and the other mics silent. Never remove a word that belongs to the sentence ("este libro").
6. EVERY silence or filler cut on screen MUST be hidden by an angle change or a 110–115% punch-in. A visible jump cut is a defect.
7. Place audio edit points at zero crossings or inside pauses (no clicks).
8. Chain per mic: highpass 80 Hz → light denoise → de-ess → compression → mix normalization to -14 LUFS / -1 dBTP.

Retention and cinematography:
9. Show the active speaker. Vary J-cuts (audio leads, video follows 6–12 frames later) and L-cuts (hold on the previous speaker 8–15 frames for a reaction). Never use the same offset twice in a row.
10. Monologues: max shot length 3–6 s, scaled to energy (more energy = shorter shots). Break them with a listener reaction (laughter, "ajá", nods), the wide, or a punch-in/out.
11. Crosstalk >1 s → wide. Topic change (detected from the transcript) → re-establish with the wide.
12. Minimum shot length is 1.2 s, except reactions to laughter.
13. Cold open: the first 15–45 s is the episode's best moment, then a sting, then the actual start. The moment also stays in its original place.
14. First 60 s: zero dead air, shots ≤4 s.
15. Pattern interrupts every 45–90 s: put a green marker as a B-roll or lower-third placeholder wherever the transcript mentions a person, place, number or product.

Viral clips:
16. Score windows of 20–90 s by combining:
    - audio energy: RMS spikes, pitch variance (librosa pyin), laughter;
    - changes in speech rate;
    - a semantic score YOU assign by reading the transcript: hook in the first 3 s, self-contained story, surprising or polarizing claim, punchline, quotable line.
17. Output the top 10 in clips.json: start/end snapped to sentence boundaries, hook, suggested title in Spanish, score breakdown.
18. Markers: red = viral (name = hook, note = score), yellow = KEEP_PAUSE / review, blue = topic change, purple = sync warning, green = B-roll.

## Deliverables (in ~/podcast_agent)
podcast_agent/
  config.yaml (every threshold above lives here, editable)
  cli.py → `python -m podcast_agent run --episode <path> --stage ingest|sync|audio|analyze|edit|resolve|all [--dry-run] [--excerpt 10m]`
  ingest.py, sync.py, audio_clean.py, analyze.py, viral.py, edit_engine.py, resolve_bridge.py
  tests/ (pytest + synthetic fixture generator)
requirements.txt (pinned), README.md (setup and usage, in Spanish)

- Every stage writes JSON to output/<episode>/cache/ and skips its work if the input hash hasn't changed.
- `--dry-run` produces edl.json, OTIO/FCPXML and clips.json without Resolve open.
- Time math in integer frames, never accumulated floats. Handle 23.976/29.97 (DF/NDF) correctly.
- Handled errors, each with a clear message and next step:
  - Resolve not open, not Studio, or API unreachable;
  - mic or camera with no mapping;
  - drift that can't be corrected;
  - ffmpeg missing (suggest `brew install ffmpeg`);
  - no GPU → smaller model, with a warning;
  - empty episode folder.

## Scope
- Work only in ~/podcast_agent. /Users/davicho/Downloads/podcasts/ is read-only.
- In Resolve: create ONLY the project PODCAST_AUTO, timelines named `AUTO_EDIT_<episode>_v{n}`, and their bins. Never modify or delete existing projects, timelines, bins or media.
- Only make changes directly requested: no GUI, no dashboards, no uploads, no vertical exports, no extra features.
- Secrets only via env vars (HF_TOKEN). Never in code.

## Phases (STOP = wait for my approval)
0. Discovery (no code): check macOS and chip, Python, ffmpeg, Homebrew, GPU/Metal, Resolve version and Studio, external scripting enabled, and the API methods available per the README. Deliver a report and the chosen integration path. STOP.
1. Scaffold, plus a synthetic fixture generator with ffmpeg: 3 "cameras" with scratch audio, 2 mics, known offsets of 0.5 s and 3.2 s, drift of 50 ppm, inserted silences and fillers. Then build ingest and sync and pass the tests.
2. Audio cleanup and analysis on the fixtures (VAD, transcription, fillers, dead air). Report the metrics.
3. Edit engine and viral scoring on the fixtures. Report: shot count, average and max shot length, cuts by reason, runtime before/after. STOP.
4. Resolve bridge: build a test timeline from the fixtures in PODCAST_AUTO. STOP and tell me to drop a real episode into /Users/davicho/Downloads/podcasts/EP01/.
5. Real episode: ffprobe report + camera frames + proposed speaker map. STOP for my OK. Then run on a 10-min excerpt (STOP for review), then the full episode.
6. Final report: files, how to run, known limitations.

## Acceptance criteria
- [ ] Synthetic offsets and drift recovered within ±1 frame.
- [ ] 0 cuts inside a word (verified against the word timestamps).
- [ ] 0 shots >6 s or <1.2 s outside tagged exceptions.
- [ ] 100% of silence/filler removals on screen hidden by an angle change or punch-in.
- [ ] Resolve timeline matches edl.json (clip count, positions ±0 frames) and has all markers.
- [ ] `--dry-run` works without Resolve open. pytest green.

## Stop conditions
Stop and ask before:
- installing Homebrew packages, or torch/pyannote/whisperx, or any dependency >500 MB;
- using HF_TOKEN;
- continuing when the speaker/camera mapping is ambiguous;
- continuing when sync confidence is low;
- calling a method that isn't in the README;
- writing to Resolve beyond the PODCAST_AUTO project, its timelines and its bins;
- continuing after an error you couldn't resolve in 2 attempts.

## Progress
After each phase: ✅ what was done, files touched, metrics. Never claim progress without tool output to back it up. Talk to me in Spanish.
