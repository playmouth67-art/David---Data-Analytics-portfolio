"""CLI: python -m podcast_agent run --episode <ruta> --stage ingest|sync|audio|analyze|edit|resolve|all
[--dry-run] [--excerpt 10m] [--set clave.sub=valor] [--force]"""
import argparse
import json
import re
import sys
import time

import yaml

from . import analyze, audio_clean, cache, edit_engine, export, ingest, sync, viral
from .config import Paths, load_config, parse_excerpt
from .errors import AgentError

STAGES = ["ingest", "sync", "audio", "analyze", "edit", "resolve"]


def parse_sets(items):
    out = {}
    for it in items or []:
        key, _, val = it.partition("=")
        d = out
        parts = key.split(".")
        for p in parts[:-1]:
            d = d.setdefault(p, {})
        d[parts[-1]] = yaml.safe_load(val)
    return out


def timeline_name(paths, cfg, reuse):
    prefix = f"{cfg['resolve']['timeline_prefix']}{paths.episode}_v"
    found = [int(m.group(1)) for p in paths.out.glob(f"{prefix}*.fcpxml")
             if (m := re.search(r"_v(\d+)\.fcpxml$", p.name))]
    n = max(found, default=0)
    return f"{prefix}{n if (reuse and n) else n + 1}"


def log(stage, cached, extra=""):
    print(f"  ✓ {stage:<8} {'(caché)' if cached else ''} {extra}".rstrip())


def run(args):
    cfg = load_config(args.config, parse_sets(args.set))
    excerpt = parse_excerpt(args.excerpt)
    paths = Paths(cfg, args.episode, args.excerpt)
    target = "edit" if (args.dry_run and args.stage in ("all", "resolve")) else args.stage
    last = STAGES.index("resolve" if target == "all" else target)
    force = set(STAGES) if args.force else set()
    print(f"podcast_agent · episodio {paths.episode} · salida {paths.out}")
    t_start = time.time()

    ing, c = ingest.run_ingest(paths, cfg, "ingest" in force)
    d = ing["delivery"]
    log("ingest", c, f"{len(ing['cameras'])} cámaras, {len(ing['mics'])} mics, {d['width']}x{d['height']} "
                     f"@ {d['nominal_fps']} {'DF' if d['drop_frame'] else 'NDF'}")
    for w in ing["warnings"]:
        print(f"    ! {w}")
    if last == 0:
        return 0
    sy, c = sync.run_sync(paths, cfg, ing, "sync" in force)
    log("sync", c, " · ".join(f"{k}: {v['offset_s']:+.3f}s {v['drift_ppm']:+.1f}ppm res {v['residual_frames']:.2f}f"
                              for k, v in sy["cameras"].items()))
    if last == 1:
        return 0
    au, c = audio_clean.run_audio(paths, cfg, ing, excerpt, "audio" in force)
    log("audio", c, f"mezcla {au['final']['mix_lufs']} LUFS / {au['final']['mix_tp_dbtp']} dBTP")
    for w in au["warnings"]:
        print(f"    ! {w}")
    if last == 2:
        return 0
    an, c = analyze.run_analyze(paths, cfg, ing, au, excerpt, "analyze" in force)
    n_rm = sum(1 for f in an["fillers"] if f["removable"])
    log("analyze", c, f"{len(an['words'])} palabras, {n_rm} muletillas, {len(an['dead_air'])} silencios, "
                      f"{len(an['keep_pauses'])} KEEP_PAUSE, {len(an['topics'])} temas [{an['backend']}]")
    for w in an["warnings"]:
        print(f"    ! {w}")
    if not paths.mapping.exists():
        edit_engine.write_mapping_template(paths, ing, an)
        print(f"    → Propuesta de mapeo escrita en {paths.mapping} (frames en {paths.frames}).")
    if last == 3:
        return 0
    arrays = analyze.load_arrays(paths)
    vi, c = viral.run_viral(paths, cfg, an, arrays, au, "edit" in force)
    log("viral", c, f"{len(vi['clips'])} clips → clips.json")
    for w in vi["warnings"]:
        print(f"    ! {w}")
    edl, c = edit_engine.run_edit(paths, cfg, ing, sy, au, an, arrays, vi, "edit" in force)
    name = timeline_name(paths, cfg, reuse=c)
    files = export.export_all(edl, ing, paths.out, name)
    q = edl["qc"]
    log("edit", c, f"{q['shot_count']} planos, prom {q['avg_shot_s']} s, máx {q['max_shot_s']} s, "
                   f"{q['runtime_source_s']} s → {q['runtime_record_s']} s")
    print(f"    edl.json, clips.json, {name}.fcpxml, {name}.otio en {paths.out}")
    print("    QC: " + json.dumps({k: q[k] for k in ("shots_too_long", "shots_too_short", "joins_unhidden",
                                                     "cuts_inside_words", "jl_consecutive_repeats",
                                                     "first_minute_dead_air")}, ensure_ascii=False))
    for w in edl["warnings"]:
        print(f"    ! {w}")
    (paths.out / "report.json").write_text(json.dumps({"qc": q, "timeline": name, "files": files,
                                                       "seconds": round(time.time() - t_start, 1)},
                                                      ensure_ascii=False, indent=1, default=cache._default),
                                           encoding="utf-8")
    if last == 4:
        return 0
    from . import resolve_bridge
    resolve_bridge.run_resolve(paths, cfg, edl, ing, name, files)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m podcast_agent")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="Corre el pipeline sobre un episodio")
    r.add_argument("--episode", required=True, help="Carpeta del episodio (solo lectura)")
    r.add_argument("--stage", default="all", choices=STAGES + ["all"])
    r.add_argument("--dry-run", action="store_true", help="edl.json + OTIO/FCPXML + clips.json sin abrir Resolve")
    r.add_argument("--excerpt", help="Solo un tramo: 10m, 90s o 45m+10m (inicio+duración)")
    r.add_argument("--config", help="Ruta a config.yaml alternativo")
    r.add_argument("--set", action="append", help="Sobrescribe config: transcription.backend=fixture")
    r.add_argument("--force", action="store_true", help="Ignora la caché")
    args = ap.parse_args(argv)
    try:
        return run(args)
    except AgentError as e:
        print(e.render(), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
