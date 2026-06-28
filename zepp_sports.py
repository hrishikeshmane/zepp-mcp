"""
Workout / sport decoding helpers for the Zepp MCP server.

Two concerns:
  1. Sport-type code -> human name  (decode_sport_type / enrich_workouts)
  2. Decoding the delta/absolute-encoded track series in workout detail
     (decode_workout_series)

This module never modifies huami_client.py / server.py. It fetches RAW
workout detail itself (via client._get) so the encoded series strings are
not truncated by HuamiClient.workout_detail.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Task 1: sport-type decode
# ---------------------------------------------------------------------------

# VERIFIED cloud `type` map (rolandsz/Mi-Fit-and-Zepp-workout-exporter).
# Anchors: 1=running, 6=walking. Codes NOT in any public source (e.g. the
# account's observed 223 / 241) intentionally fall through to "unknown_<code>".
SPORT_TYPES: dict[int, str] = {
    1: "running",
    6: "walking",
    8: "treadmill_running",
    9: "cycling",
    10: "indoor_cycling",
    16: "other",
    23: "indoor_rowing",
    92: "badminton",
}


def decode_sport_type(code: Any) -> str:
    """Map a cloud sport `type` code to a human name.

    Unknown / unmapped codes return ``f"unknown_{code}"`` (never guessed)."""
    try:
        c = int(code)
    except (TypeError, ValueError):
        return f"unknown_{code}"
    return SPORT_TYPES.get(c, f"unknown_{c}")


def _to_num(v: Any) -> Any:
    """Best-effort numeric coercion for summary fields."""
    if v is None:
        return None
    try:
        f = float(v)
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return v


def _epoch_to_iso(ts: Any) -> Any:
    """Convert an epoch-seconds value to an ISO-8601 UTC string."""
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return ts


def enrich_workouts(client, limit: int = 50) -> list[dict]:
    """Fetch the workout list and add a ``type_name`` to every item.

    Returns a compact summary list (one dict per workout) with:
    trackid, type, type_name, date (from end_time), distance, calories,
    avg_hr, duration. The original list items are mutated in place to also
    carry ``type_name`` (callers that want the full items can re-read them).
    """
    items = client.workouts(limit)
    summary: list[dict] = []
    for w in items:
        if not isinstance(w, dict):
            continue
        code = w.get("type")
        name = decode_sport_type(code)
        w["type_name"] = name  # annotate the raw item in place

        end_time = w.get("end_time")
        # duration: prefer explicit, else end-start.
        duration = w.get("run_time") or w.get("duration")
        if duration is None and w.get("start_time") and end_time:
            try:
                duration = int(end_time) - int(w["start_time"])
            except (TypeError, ValueError):
                duration = None

        summary.append(
            {
                "trackid": w.get("trackid"),
                "type": code,
                "type_name": name,
                "date": _epoch_to_iso(end_time),
                "distance": _to_num(w.get("dis")),
                "calories": _to_num(w.get("calorie")),
                "avg_hr": _to_num(w.get("avg_heart_rate")),
                "duration": _to_num(duration),
            }
        )
    return summary


# ---------------------------------------------------------------------------
# Task 2: series decoder
# ---------------------------------------------------------------------------

_ALT_MISSING = -2000000  # altitude sentinel for "no fix" -> carry last valid


def _split_points(raw: Any) -> list[str]:
    """Split an encoded series string into per-point token strings."""
    if not isinstance(raw, str):
        return []
    raw = raw.strip()
    if not raw:
        return []
    return [p for p in raw.split(";") if p != ""]


def _to_int(tok: str, default: int = 0) -> int:
    tok = tok.strip()
    if tok == "":
        return default
    try:
        return int(tok)
    except ValueError:
        try:
            return int(float(tok))
        except ValueError:
            return default


def _to_float(tok: str, default: float = 0.0) -> float:
    tok = tok.strip()
    if tok == "":
        return default
    try:
        return float(tok)
    except ValueError:
        return default


def _decode_time(raw: Any) -> list[int]:
    """time: delta-encoded seconds -> cumulative seconds since start."""
    pts = _split_points(raw)
    out: list[int] = []
    acc = 0
    for p in pts:
        acc += _to_int(p.split(",")[0])
        out.append(acc)
    return out


def _decode_gps(raw: Any) -> list[list[float]]:
    """longitude_latitude: 'lat,lon;dlat,dlon;...' LAT FIRST, per-axis delta,
    /1e8 -> degrees. Accumulate lat and lon separately."""
    pts = _split_points(raw)
    out: list[list[float]] = []
    lat = 0
    lon = 0
    for p in pts:
        parts = p.split(",")
        if len(parts) < 2:
            continue
        lat += _to_int(parts[0])
        lon += _to_int(parts[1])
        out.append([lat / 1e8, lon / 1e8])
    return out


def _decode_altitude(raw: Any) -> list[float]:
    """altitude: ABSOLUTE /100 -> meters. Sentinel -2000000 = missing
    (carry last valid)."""
    pts = _split_points(raw)
    out: list[float] = []
    last = None
    for p in pts:
        v = _to_int(p.split(",")[0])
        if v == _ALT_MISSING:
            if last is not None:
                out.append(last)
            continue
        last = v / 100.0
        out.append(last)
    return out


def _decode_air_pressure_altitude(raw: Any) -> list[float]:
    """air_pressure_altitude: 'dt,pressure_pa;...' time delta, ABSOLUTE
    pressure in pascals. Convert to approx altitude (m) via the international
    barometric formula. Used as a fallback when the plain `altitude` series is
    empty (common on this account's records, which lack `altitude`)."""
    pts = _split_points(raw)
    out: list[float] = []
    for p in pts:
        parts = p.split(",")
        pa = _to_float(parts[1]) if len(parts) >= 2 else 0.0
        if pa <= 0:
            continue
        # h = 44330 * (1 - (P/P0)^(1/5.255)), P0 = 101325 Pa
        alt = 44330.0 * (1.0 - (pa / 101325.0) ** (1.0 / 5.255))
        out.append(round(alt, 2))
    return out


def _decode_heart_rate(raw: Any) -> list[dict]:
    """heart_rate: 'dt,dhr;...' both delta. hr=cumsum(dhr);
    time=cumsum(dt where empty dt -> 1). dhr can be negative."""
    pts = _split_points(raw)
    out: list[dict] = []
    t = 0
    hr = 0
    for p in pts:
        parts = p.split(",")
        dt_tok = parts[0] if len(parts) >= 1 else ""
        dhr_tok = parts[1] if len(parts) >= 2 else ""
        dt = _to_int(dt_tok, default=1) if dt_tok.strip() != "" else 1
        t += dt
        hr += _to_int(dhr_tok)
        out.append({"t_sec": t, "bpm": hr})
    return out


def _decode_pace(raw: Any) -> list[float]:
    """pace: ABSOLUTE sec/meter, aligned to time index."""
    pts = _split_points(raw)
    out: list[float] = []
    for p in pts:
        out.append(_to_float(p.split(",")[0]))
    return out


def _decode_distance(raw: Any) -> list[float]:
    """distance: 'dt,dd;...' both delta -> cumsum(dd) = cumulative meters."""
    pts = _split_points(raw)
    out: list[float] = []
    dist = 0.0
    for p in pts:
        parts = p.split(",")
        dd_tok = parts[1] if len(parts) >= 2 else parts[0]
        dist += _to_float(dd_tok)
        out.append(dist)
    return out


def _decode_gait(raw: Any) -> list[dict]:
    """gait: 'dt,dsteps,stride,cadence;...'
    idx0 time-delta (cumsum), stride(cm, absolute), cadence(absolute, may 0).
    dsteps treated as a delta -> cumulative step count."""
    pts = _split_points(raw)
    out: list[dict] = []
    t = 0
    steps = 0
    for p in pts:
        parts = p.split(",")
        t += _to_int(parts[0]) if len(parts) >= 1 else 0
        steps += _to_int(parts[1]) if len(parts) >= 2 else 0
        stride = _to_int(parts[2]) if len(parts) >= 3 else 0
        cadence = _to_int(parts[3]) if len(parts) >= 4 else 0
        out.append(
            {"t_sec": t, "steps": steps, "stride_cm": stride, "cadence": cadence}
        )
    return out


def _decode_speed(raw: Any) -> list[dict]:
    """speed: 'dt,speed;...' time delta, speed absolute (m/s)."""
    pts = _split_points(raw)
    out: list[dict] = []
    t = 0
    for p in pts:
        parts = p.split(",")
        t += _to_int(parts[0]) if len(parts) >= 1 else 0
        spd = _to_float(parts[1]) if len(parts) >= 2 else 0.0
        out.append({"t_sec": t, "speed_mps": spd})
    return out


def _stats(values: list[float]) -> dict:
    if not values:
        return {"count": 0, "min": None, "max": None, "avg": None}
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "avg": round(sum(values) / len(values), 3),
    }


def _raw_detail(client, trackid: str, source: str | None) -> dict:
    """Fetch RAW (untruncated) workout detail via client._get."""
    trackid = str(trackid)
    if source is None:
        source = client._source_cache.get(trackid)
        if source is None:
            client.workouts(limit=200)  # populate the source cache
            source = client._source_cache.get(trackid, "run.mi.com")
    j = client._get(
        "/v1/sport/run/detail.json",
        {"trackid": trackid, "source": source, "userid": client.user_id},
    )
    data = j.get("data", j)
    return data if isinstance(data, dict) else {}


def decode_workout_series(
    client,
    trackid: str,
    source: str | None = None,
    include_full: bool = False,
    max_points: int = 50,
) -> dict:
    """Decode the encoded track series for one workout.

    Fetches RAW detail (untruncated) and decodes every series robustly --
    empty / missing series are skipped, never raises.

    Returns a dict with decoded series + a compact ``summary``. By default
    long arrays are downsampled to ``max_points`` (first/last preserved);
    pass ``include_full=True`` to get full arrays.
    """
    data = _raw_detail(client, trackid, source)

    gps = _decode_gps(data.get("longitude_latitude"))
    hr = _decode_heart_rate(data.get("heart_rate"))
    altitude = _decode_altitude(data.get("altitude"))
    altitude_source = "altitude"
    if not altitude:
        # Fallback: this account's records carry barometric pressure under
        # `air_pressure_altitude` instead of a plain `altitude` series.
        altitude = _decode_air_pressure_altitude(data.get("air_pressure_altitude"))
        if altitude:
            altitude_source = "air_pressure_altitude"
    pace = _decode_pace(data.get("pace"))
    distance = _decode_distance(data.get("distance"))
    gait = _decode_gait(data.get("gait"))
    speed = _decode_speed(data.get("speed"))
    times = _decode_time(data.get("time"))

    # ---- summary stats -----------------------------------------------------
    hr_vals = [h["bpm"] for h in hr if isinstance(h.get("bpm"), (int, float))]
    # filter to plausible bpm for the stat (keep raw series intact)
    hr_plausible = [v for v in hr_vals if 20 <= v <= 240]

    ascent = 0.0
    if len(altitude) >= 2:
        for a, b in zip(altitude, altitude[1:]):
            if b > a:
                ascent += b - a

    total_distance = distance[-1] if distance else None

    summary = {
        "gps_points": len(gps),
        "hr_points": len(hr),
        "altitude_points": len(altitude),
        "pace_points": len(pace),
        "distance_points": len(distance),
        "gait_points": len(gait),
        "speed_points": len(speed),
        "time_points": len(times),
        "hr": _stats(hr_plausible or hr_vals),
        "altitude_source": altitude_source,
        "altitude_m": _stats(altitude),
        "pace_sec_per_m": _stats(pace),
        "speed_mps": _stats([s["speed_mps"] for s in speed]),
        "total_distance_m": round(total_distance, 2) if total_distance is not None else None,
        "total_ascent_m": round(ascent, 2),
        "duration_sec": times[-1] if times else (hr[-1]["t_sec"] if hr else None),
    }
    if gps:
        summary["gps_first"] = gps[0]
        summary["gps_last"] = gps[-1]

    def _maybe_downsample(arr: list) -> Any:
        if include_full or len(arr) <= max_points:
            return arr
        # keep first/last + evenly spaced interior samples
        step = max(1, len(arr) // max_points)
        ds = arr[::step]
        if ds[-1] is not arr[-1]:
            ds = ds + [arr[-1]]
        return {
            "_downsampled": True,
            "_total": len(arr),
            "_returned": len(ds),
            "samples": ds,
        }

    return {
        "trackid": str(trackid),
        "summary": summary,
        "gps": _maybe_downsample(gps),
        "heart_rate": _maybe_downsample(hr),
        "altitude": _maybe_downsample(altitude),
        "pace": _maybe_downsample(pace),
        "distance": _maybe_downsample(distance),
        "gait": _maybe_downsample(gait),
        "speed": _maybe_downsample(speed),
        "time": _maybe_downsample(times),
    }
