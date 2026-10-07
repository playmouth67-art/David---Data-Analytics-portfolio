from fractions import Fraction

import pytest

from podcast_agent.timecode import (frames_to_tc, parse_rate, sec_to_frame, frame_to_sec, tc_to_frames,
                                    frame_to_fraction_sec)

NTSC = Fraction(30000, 1001)


@pytest.mark.parametrize("s,expected", [("30000/1001", NTSC), ("29.97", NTSC), ("24000/1001", Fraction(24000, 1001)),
                                        ("23.976", Fraction(24000, 1001)), ("25/1", Fraction(25)), ("59.94", Fraction(60000, 1001))])
def test_parse_rate(s, expected):
    assert parse_rate(s) == expected


@pytest.mark.parametrize("tc,frames", [("00:00:59;29", 1799), ("00:01:00;02", 1800), ("00:10:00;00", 17982),
                                       ("01:00:00;00", 107892), ("00:59:55;10", 107752)])
def test_drop_frame_known_values(tc, frames):
    assert tc_to_frames(tc, NTSC) == frames
    assert frames_to_tc(frames, NTSC, drop_frame=True) == tc


def test_drop_frame_roundtrip_every_frame_for_11_minutes():
    for f in range(0, 11 * 60 * 30, 7):
        assert tc_to_frames(frames_to_tc(f, NTSC, True), NTSC) == f


def test_ndf_and_23976():
    r = Fraction(24000, 1001)
    assert tc_to_frames("01:00:00:00", r) == 86400
    assert frames_to_tc(86400, r) == "01:00:00:00"
    assert tc_to_frames("01:00:00:00", NTSC) == 108000  # NDF a 29.97 cuenta 30 por segundo


def test_no_float_accumulation():
    # 3 h a 29.97: sumar 1 frame 323,676 veces debe dar exactamente el mismo número que convertir una vez.
    total = sum(1 for _ in range(323676))
    assert sec_to_frame(frame_to_sec(total, NTSC), NTSC) == total
    assert frame_to_fraction_sec(323676, NTSC) == Fraction(323676 * 1001, 30000)


def test_rounding_modes():
    t = 1.0  # 29.97002997 frames
    assert sec_to_frame(t, NTSC, "floor") == 29
    assert sec_to_frame(t, NTSC, "ceil") == 30
    assert sec_to_frame(t, NTSC) == 30
