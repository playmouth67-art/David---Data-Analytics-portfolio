"""Matemática de tiempo en frames enteros. Nunca se acumulan floats.

Las tasas se guardan como fracción exacta (30000/1001, 24000/1001, 25/1, ...).
Los segundos solo aparecen en la frontera (audio, transcripción) y se convierten
una sola vez a frames con redondeo explícito.
"""
from fractions import Fraction
import math

KNOWN_RATES = {
    "23.976": Fraction(24000, 1001), "24": Fraction(24), "25": Fraction(25),
    "29.97": Fraction(30000, 1001), "30": Fraction(30), "50": Fraction(50),
    "59.94": Fraction(60000, 1001), "60": Fraction(60),
}


def parse_rate(s):
    """'30000/1001' | '29.97' | Fraction -> Fraction exacta, ajustando a tasas NTSC conocidas."""
    if isinstance(s, Fraction):
        r = s
    elif isinstance(s, str) and "/" in s:
        n, d = s.split("/")
        r = Fraction(int(n), int(d)) if int(d) else Fraction(0)
    else:
        r = Fraction(str(s))
    for known in KNOWN_RATES.values():
        if abs(float(r) - float(known)) < 0.002:
            return known
    return r


def rate_str(rate):
    return f"{rate.numerator}/{rate.denominator}"


def sec_to_frame(sec, rate, mode="round"):
    """Segundos -> frame entero. mode: round | floor | ceil."""
    x = Fraction(sec).limit_denominator(10**9) * rate
    if mode == "floor":
        return math.floor(x)
    if mode == "ceil":
        return math.ceil(x)
    return math.floor(x + Fraction(1, 2))


def frame_to_sec(frame, rate):
    return float(Fraction(int(frame)) / rate)


def frame_to_fraction_sec(frame, rate):
    """Segundos exactos como Fraction (para FCPXML)."""
    return Fraction(int(frame)) / rate


def nominal_fps(rate):
    return int(round(float(rate)))


def is_drop_frame_rate(rate):
    return rate.denominator == 1001 and nominal_fps(rate) in (30, 60)


def frames_to_tc(frame, rate, drop_frame=False):
    """Frame -> 'HH:MM:SS:FF' (o ';' en drop-frame). Algoritmo DF estándar SMPTE."""
    fps = nominal_fps(rate)
    frame = int(frame)
    if drop_frame and is_drop_frame_rate(rate):
        drop = 2 if fps == 30 else 4
        per_10min = fps * 600 - drop * 9
        per_min = fps * 60 - drop
        d, m = divmod(frame, per_10min)
        if m < drop:
            m = drop  # los primeros frames de un bloque de 10 min no se saltan
        frame = frame + drop * 9 * d + drop * ((m - drop) // per_min)
        sep = ";"
    else:
        sep = ":"
    ff = frame % fps
    ss = (frame // fps) % 60
    mm = (frame // (fps * 60)) % 60
    hh = frame // (fps * 3600)
    return f"{hh:02d}:{mm:02d}:{ss:02d}{sep}{ff:02d}"


def tc_to_frames(tc, rate):
    """'HH:MM:SS:FF' o 'HH:MM:SS;FF' -> frame. ';' o '.' implica drop-frame."""
    drop_frame = (";" in tc or "." in tc) and is_drop_frame_rate(rate)
    parts = tc.replace(";", ":").replace(".", ":").split(":")
    hh, mm, ss, ff = (int(p) for p in parts)
    fps = nominal_fps(rate)
    total = ((hh * 60 + mm) * 60 + ss) * fps + ff
    if drop_frame:
        drop = 2 if fps == 30 else 4
        total_minutes = hh * 60 + mm
        total -= drop * (total_minutes - total_minutes // 10)
    return total
