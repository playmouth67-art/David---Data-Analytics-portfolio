"""Exporta edl.json a OTIO y FCPXML (importables en Resolve: File > Import > Timeline).

Tiempos FCPXML como fracciones exactas (frames · 1001/30000 s): sin floats.
V1 = planos de cámara (solo video, con escala para punch-ins); audio = una
pista por mic (clips conectados en carriles negativos); hueco para el sting.
"""
from fractions import Fraction
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import quoteattr

from .timecode import parse_rate


def _t(frames, fps):
    x = Fraction(int(frames)) / fps
    return f"{x.numerator}s" if x.denominator == 1 else f"{x.numerator}/{x.denominator}s"


def _url(path):
    return "file://" + quote(str(Path(path).resolve()))


def _assets(edl, ingest):
    cams = {c["id"]: c for c in ingest["cameras"]}
    assets = {}
    for s in edl["video_track"]["shots"]:
        c = cams[s["camera"]]
        assets.setdefault(c["path"], {"id": f"a{len(assets) + 1}", "name": c["name"], "video": True,
                                      "tc": c["tc_start_frames"], "dur_s": c["duration_s"],
                                      "channels": (c["scratch_audio"] or {}).get("channels", 0)})
    for t in edl["audio_tracks"]:
        assets.setdefault(t["file"], {"id": f"a{len(assets) + 1}", "name": Path(t["file"]).stem, "video": False,
                                      "tc": 0, "dur_s": None, "channels": 1})
    return assets


def to_fcpxml(edl, ingest, out_path, timeline_name):
    fps = parse_rate(edl["fps"]["rate"])
    w, h = edl["resolution"]
    assets = _assets(edl, ingest)
    mic_dur = ingest["mic_duration_s"]
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<!DOCTYPE fcpxml>", '<fcpxml version="1.9">', "  <resources>",
             f'    <format id="r1" name="podcast_agent" frameDuration="{_t(1, fps)}" width="{w}" height="{h}"/>']
    for path, a in assets.items():
        dur = round((a["dur_s"] or mic_dur) * float(fps))
        attrs = (f'id="{a["id"]}" name={quoteattr(a["name"])} start="{_t(a["tc"], fps)}" duration="{_t(dur, fps)}" '
                 f'hasVideo="{1 if a["video"] else 0}" hasAudio="{1 if a["channels"] else 0}" '
                 + ('format="r1" ' if a["video"] else "")
                 + f'audioSources="1" audioChannels="{max(1, a["channels"])}" audioRate="48000"')
        lines += [f"    <asset {attrs}>", f'      <media-rep kind="original-media" src={quoteattr(_url(path))}/>',
                  "    </asset>"]
    lines += ["  </resources>", "  <library>", '    <event name="PODCAST_AUTO">',
              f"      <project name={quoteattr(timeline_name)}>",
              f'        <sequence format="r1" duration="{_t(edl["record_duration_f"], fps)}" tcStart="0s" '
              f'tcFormat="{"DF" if edl["fps"]["drop_frame"] else "NDF"}" audioLayout="stereo" audioRate="48k">',
              "          <spine>"]

    # Elementos del spine: planos y huecos, en orden.
    spine = []
    cur = 0
    for s in edl["video_track"]["shots"]:
        if s["rec_start_f"] > cur:
            spine.append({"gap": True, "offset": cur, "dur": s["rec_start_f"] - cur, "start": 0})
        a = assets[s["file"]]
        spine.append({"gap": False, "offset": s["rec_start_f"], "dur": s["rec_end_f"] - s["rec_start_f"],
                      "start": a["tc"] + s["src_in_f"], "shot": s, "asset": a})
        cur = s["rec_end_f"]
    if cur < edl["record_duration_f"]:
        spine.append({"gap": True, "offset": cur, "dur": edl["record_duration_f"] - cur, "start": 0})
    for el in spine:
        el["children"] = []

    def parent_of(rec):
        for el in spine:
            if el["offset"] <= rec < el["offset"] + el["dur"]:
                return el
        return spine[-1]

    for lane, t in enumerate(edl["audio_tracks"], 1):
        a = assets[t["file"]]
        for c in t["clips"]:
            p = parent_of(c["rec_start_f"])
            local = p["start"] + c["rec_start_f"] - p["offset"]
            p["children"].append(
                f'<asset-clip ref="{a["id"]}" lane="-{lane}" offset="{_t(local, fps)}" name={quoteattr(t["speaker"])} '
                f'start="{_t(c["src_start_f"], fps)}" duration="{_t(c["src_end_f"] - c["src_start_f"], fps)}" '
                f'srcEnable="audio"/>')
    for m in edl["markers"]:
        p = parent_of(m["rec_f"])
        local = p["start"] + m["rec_f"] - p["offset"]
        p["children"].append(f'<marker start="{_t(local, fps)}" duration="{_t(m["duration_f"], fps)}" '
                             f'value={quoteattr("[" + m["color"].upper() + "] " + m["name"])} note={quoteattr(m["note"])}/>')

    for el in spine:
        if el["gap"]:
            head = f'<gap name="Gap" offset="{_t(el["offset"], fps)}" start="{_t(el["start"], fps)}" duration="{_t(el["dur"], fps)}"'
            inner = []
        else:
            s = el["shot"]
            head = (f'<asset-clip ref="{el["asset"]["id"]}" offset="{_t(el["offset"], fps)}" '
                    f'name={quoteattr(s["view"])} start="{_t(el["start"], fps)}" duration="{_t(el["dur"], fps)}" '
                    f'srcEnable="video" tcFormat="{"DF" if edl["fps"]["drop_frame"] else "NDF"}"')
            inner = [f'<adjust-transform scale="{s["zoom"]:.4f} {s["zoom"]:.4f}"/>'] if s["zoom"] != 1.0 else []
        body = inner + el["children"]
        if body:
            lines.append("            " + head + ">")
            lines += ["              " + b for b in body]
            lines.append("            " + ("</gap>" if el["gap"] else "</asset-clip>"))
        else:
            lines.append("            " + head + "/>")
    lines += ["          </spine>", "        </sequence>", "      </project>", "    </event>", "  </library>",
              "</fcpxml>"]
    Path(out_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def to_otio(edl, ingest, out_path, timeline_name):
    import opentimelineio as otio
    fps = parse_rate(edl["fps"]["rate"])
    rate = float(fps)
    RT = lambda f: otio.opentime.RationalTime(int(f), rate)
    TR = lambda a, d: otio.opentime.TimeRange(RT(a), RT(d))
    cams = {c["id"]: c for c in ingest["cameras"]}
    tl = otio.schema.Timeline(name=timeline_name, global_start_time=RT(0))
    tl.metadata["podcast_agent"] = {"episode": edl["episode"], "fps": edl["fps"]}
    v1 = otio.schema.Track(name="V1", kind=otio.schema.TrackKind.Video)
    cur = 0
    for s in edl["video_track"]["shots"]:
        if s["rec_start_f"] > cur:
            v1.append(otio.schema.Gap(source_range=TR(0, s["rec_start_f"] - cur)))
        c = cams[s["camera"]]
        ref = otio.schema.ExternalReference(target_url=_url(c["path"]),
                                            available_range=TR(c["tc_start_frames"], c["duration_frames"]))
        clip = otio.schema.Clip(name=s["view"], media_reference=ref,
                                source_range=TR(c["tc_start_frames"] + s["src_in_f"], s["rec_end_f"] - s["rec_start_f"]))
        clip.metadata["podcast_agent"] = {k: s[k] for k in ("id", "reason", "zoom", "pan", "tilt", "exception")}
        v1.append(clip)
        cur = s["rec_end_f"]
    tl.tracks.append(v1)
    for t in edl["audio_tracks"]:
        tr = otio.schema.Track(name=f"A{t['track']} {t['speaker']}", kind=otio.schema.TrackKind.Audio)
        cur = 0
        for c in t["clips"]:
            if c["rec_start_f"] > cur:
                tr.append(otio.schema.Gap(source_range=TR(0, c["rec_start_f"] - cur)))
            ref = otio.schema.ExternalReference(target_url=_url(t["file"]))
            tr.append(otio.schema.Clip(name=t["speaker"], media_reference=ref,
                                       source_range=TR(c["src_start_f"], c["src_end_f"] - c["src_start_f"])))
            cur = c["rec_start_f"] + c["src_end_f"] - c["src_start_f"]
        tl.tracks.append(tr)
    colors = {"Red": "RED", "Yellow": "YELLOW", "Blue": "BLUE", "Purple": "PURPLE", "Green": "GREEN"}
    for m in edl["markers"]:
        tl.tracks.markers.append(otio.schema.Marker(
            name=m["name"], marked_range=TR(m["rec_f"], m["duration_f"]),
            color=getattr(otio.schema.MarkerColor, colors.get(m["color"], "RED")), metadata={"note": m["note"]}))
    otio.adapters.write_to_file(tl, str(out_path))
    return out_path


def export_all(edl, ingest, out_dir, timeline_name):
    out_dir = Path(out_dir)
    return {"fcpxml": str(to_fcpxml(edl, ingest, out_dir / f"{timeline_name}.fcpxml", timeline_name)),
            "otio": str(to_otio(edl, ingest, out_dir / f"{timeline_name}.otio", timeline_name))}
