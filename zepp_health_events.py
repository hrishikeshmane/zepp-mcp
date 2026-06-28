"""
Zepp / Amazfit health-metric event functions.

Standalone functions that operate on a *logged-in* `HuamiClient` (see
`huami_client.py`). Each reuses `client._get(path, params)` which issues an
authenticated GET against api-mifit.zepp.com.

All functions share the signature `(client, from_date=None, to_date=None)`
where dates are ISO `YYYY-MM-DD` strings. Defaults: last 30 days. Dates are
converted internally to millisecond epoch (start-of-day for `from`,
end-of-day for `to`) since these endpoints require ms timestamps.

Robustness contract: a non-200 / malformed / empty response yields an empty
result (`[]` or `{"records": [], "note": "no data"}`) rather than raising.
"""

from __future__ import annotations

import json
import time as _time
from datetime import date, datetime, time, timedelta


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _date_range_ms(from_date: str | None, to_date: str | None) -> tuple[int, int]:
    """Return (from_ms, to_ms): start-of-day for from, end-of-day for to.

    Timestamps are computed in local time (the watch records local wall-clock)
    but the exact tz only shifts the window by a few hours, which is fine for a
    day-granular query. We use naive local dates -> epoch ms.
    """
    to_d = date.fromisoformat(to_date) if to_date else date.today()
    from_d = date.fromisoformat(from_date) if from_date else (date.today() - timedelta(days=30))
    start = datetime.combine(from_d, time.min)
    end = datetime.combine(to_d, time.max)
    from_ms = int(start.timestamp() * 1000)
    to_ms = int(end.timestamp() * 1000)
    return from_ms, to_ms


def _ms_to_iso(ms) -> str | None:
    """Convert an epoch-ms value to a local ISO datetime string."""
    if ms is None:
        return None
    try:
        ms = int(ms)
    except (TypeError, ValueError):
        return None
    if ms <= 0:
        return None
    # Heuristic: values that look like seconds (< ~ year 2001 in ms) -> treat as s.
    if ms < 1_000_000_000_000:
        ms = ms * 1000
    try:
        return datetime.fromtimestamp(ms / 1000).isoformat(timespec="seconds")
    except (OverflowError, OSError, ValueError):
        return None


def _maybe_json(val):
    """If `val` is a JSON-encoded string, decode it; otherwise return as-is."""
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return None
        if s[0] in "[{" or s in ("null", "true", "false") or s.lstrip("-").isdigit():
            try:
                return json.loads(s)
            except (ValueError, TypeError):
                return val
    return val


def _items(client, path: str, params: dict) -> list:
    """Call the endpoint and return its `items` list, robust to errors.

    On any failure (incl. HTTP 429 surfacing as a non-JSON HuamiError) we sleep
    10s and retry once, then give up with an empty list rather than raising.
    """
    def _parse(j):
        """Return (items_list_or_None, retryable_bool)."""
        if not isinstance(j, dict):
            return None, False
        items = j.get("items")
        if items is None and isinstance(j.get("data"), dict):
            items = j["data"].get("items")
        if isinstance(items, list):
            return items, False
        # Error envelope like {"code","message","data"} with no items.
        # Treat a non-success code as retryable (often transient throttling).
        code = j.get("code")
        retryable = code not in (None, 0, 1, "0", "1", 200, "200")
        return None, retryable

    for attempt in range(2):
        try:
            j = client._get(path, params)
        except Exception:
            j = None
            retryable = True
        else:
            items, retryable = _parse(j)
            if items is not None:
                return items
        if attempt == 0 and retryable:
            _time.sleep(10)
        else:
            return []
    return []


def _no_data():
    return {"records": [], "note": "no data"}


# 255 is the "no data" sentinel used across the readiness payload.
def _denull(v, sentinel=255):
    return None if v == sentinel else v


# ---------------------------------------------------------------------------
# 1. SpO2 / blood oxygen
# ---------------------------------------------------------------------------

def get_spo2(client, from_date=None, to_date=None) -> list:
    """Blood-oxygen events (ODI, OSA, manual spot checks).

    GET /users/{uid}/events  eventType=blood_oxygen
    Each record: time, subType (odi|osa_event|click), score/odi, decoded extra.
    """
    from_ms, to_ms = _date_range_ms(from_date, to_date)
    uid = client.user_id
    items = _items(
        client,
        f"/users/{uid}/events",
        {
            "eventType": "blood_oxygen",
            "from": from_ms,
            "to": to_ms,
            "limit": "1000",
            "userId": uid,
        },
    )
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        out.append(
            {
                "time": _ms_to_iso(it.get("timestamp") or it.get("time")),
                "subType": it.get("subType"),
                "score": it.get("score"),
                "odi": it.get("odi"),
                "extra": _maybe_json(it.get("extra")),
            }
        )
    return out


# ---------------------------------------------------------------------------
# 2. All-day stress
# ---------------------------------------------------------------------------

def get_stress(client, from_date=None, to_date=None, include_series=False) -> list:
    """All-day stress events.

    GET /users/{uid}/events  eventType=all_day_stress
    Per-day: timestamp, min/max/avg, proportion fields, intraday point count.
    Pass include_series=True to embed the decoded {time,value} series.
    """
    from_ms, to_ms = _date_range_ms(from_date, to_date)
    uid = client.user_id
    items = _items(
        client,
        f"/users/{uid}/events",
        {
            "eventType": "all_day_stress",
            "from": from_ms,
            "to": to_ms,
            "limit": "1000",
            "userId": uid,
        },
    )
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        series = _maybe_json(it.get("data"))
        if not isinstance(series, list):
            series = []
        rec = {
            "time": _ms_to_iso(it.get("timestamp") or it.get("time")),
            "minStress": it.get("minStress"),
            "maxStress": it.get("maxStress"),
            "avgStress": it.get("avgStress"),
            "relaxProportion": it.get("relaxProportion"),
            "normalProportion": it.get("normalProportion"),
            "mediumProportion": it.get("mediumProportion"),
            "highProportion": it.get("highProportion"),
            "pointCount": len(series),
        }
        # Carry through any other proportion-ish fields we did not name.
        for k, v in it.items():
            if k.lower().endswith("proportion") and k not in rec:
                rec[k] = v
        if include_series:
            rec["series"] = [
                {"time": _ms_to_iso(p.get("time")), "value": p.get("value")}
                for p in series
                if isinstance(p, dict)
            ]
        out.append(rec)
    return out


# ---------------------------------------------------------------------------
# 3. PAI (Personal Activity Intelligence)
# ---------------------------------------------------------------------------

def get_pai(client, from_date=None, to_date=None) -> list:
    """PAI health info, per day.

    GET /users/{uid}/events  eventType=PaiHealthInfo
    """
    from_ms, to_ms = _date_range_ms(from_date, to_date)
    uid = client.user_id
    items = _items(
        client,
        f"/users/{uid}/events",
        {
            "eventType": "PaiHealthInfo",
            "from": from_ms,
            "to": to_ms,
            "limit": "1000",
            "userId": uid,
        },
    )
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        rec = {
            "time": _ms_to_iso(it.get("timestamp") or it.get("time")),
            "dailyPai": it.get("dailyPai"),
            "totalPai": it.get("totalPai"),
            "restHr": it.get("restHr"),
            "maxHr": it.get("maxHr"),
            "lowZonePai": it.get("lowZonePai"),
            "mediumZonePai": it.get("mediumZonePai"),
            "highZonePai": it.get("highZonePai"),
            "lowZoneMinutes": it.get("lowZoneMinutes"),
            "mediumZoneMinutes": it.get("mediumZoneMinutes"),
            "highZoneMinutes": it.get("highZoneMinutes"),
            "lowZoneLowerLimit": it.get("lowZoneLowerLimit"),
            "mediumZoneLowerLimit": it.get("mediumZoneLowerLimit"),
            "highZoneLowerLimit": it.get("highZoneLowerLimit"),
            "activityScores": _maybe_json(it.get("activityScores")),
        }
        out.append(rec)
    return out


# ---------------------------------------------------------------------------
# 4. Body battery / energy ("Charge")
# ---------------------------------------------------------------------------

def get_body_battery(client, from_date=None, to_date=None) -> list:
    """Body-battery / energy events.

    GET /v2/users/me/events  eventType=Charge subType=real_data
    value.samples[] each {total, s(ms offset), physical, mental, jsonExtra}.
    Per record: time, min/max/last total (and physical/mental), sample count.
    """
    from_ms, to_ms = _date_range_ms(from_date, to_date)
    items = _items(
        client,
        "/v2/users/me/events",
        {
            "eventType": "Charge",
            "subType": "real_data",
            "from": from_ms,
            "to": to_ms,
            "limit": "200",
            "reverse": "false",
        },
    )
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        ts = it.get("timestamp") or it.get("time")
        value = _maybe_json(it.get("value"))
        samples = value.get("samples") if isinstance(value, dict) else None
        if not isinstance(samples, list):
            samples = []
        # 255 is the no-data sentinel for `total`; drop those samples.
        totals = [s["total"] for s in samples
                  if isinstance(s, dict) and isinstance(s.get("total"), (int, float)) and s["total"] != 255]
        phys = [s["physical"] for s in samples if isinstance(s, dict) and isinstance(s.get("physical"), (int, float))]
        ment = [s["mental"] for s in samples if isinstance(s, dict) and isinstance(s.get("mental"), (int, float))]
        rec = {
            "time": _ms_to_iso(ts),
            "sampleCount": len(samples),
            "minTotal": min(totals) if totals else None,
            "maxTotal": max(totals) if totals else None,
            "lastTotal": totals[-1] if totals else None,
            "lastPhysical": phys[-1] if phys else None,
            "lastMental": ment[-1] if ment else None,
        }
        out.append(rec)
    return out


# ---------------------------------------------------------------------------
# 5. Readiness
# ---------------------------------------------------------------------------

def get_readiness(client, from_date=None, to_date=None) -> list:
    """Daily readiness score and components.

    GET /v2/users/me/events  eventType=readiness subType=watch_score
    255 is mapped to None (no-data sentinel).
    """
    from_ms, to_ms = _date_range_ms(from_date, to_date)
    items = _items(
        client,
        "/v2/users/me/events",
        {
            "eventType": "readiness",
            "subType": "watch_score",
            "from": from_ms,
            "to": to_ms,
            "limit": "200",
            "reverse": "false",
        },
    )
    fields = [
        "rdnsScore", "sleepHRV", "sleepRHR", "hrvBaseline",
        "skinTempCalibrated", "ahiScore", "mentScore",
        "sleepScore", "activityScore", "rhrScore", "hrvScore",
    ]
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        ts = it.get("timestamp") or it.get("time")
        value = _maybe_json(it.get("value"))
        if not isinstance(value, dict):
            value = {}
        rec = {"time": _ms_to_iso(ts)}
        for f in fields:
            if f in value:
                rec[f] = _denull(value.get(f))
        # Include any remaining scalar fields (sentinel-mapped) we did not name.
        for k, v in value.items():
            if k not in rec and isinstance(v, (int, float, str)) and k != "time":
                rec.setdefault(k, _denull(v))
        out.append(rec)
    return out


# ---------------------------------------------------------------------------
# 6. HRV (SDNN)
# ---------------------------------------------------------------------------

def get_hrv(client, from_date=None, to_date=None) -> list:
    """HRV (SDNN) events.

    GET /v2/users/me/events  eventType=hrv_sdnn subType=real_data
    value.samples[] each {s(ms offset), sdnn, u}.
    Per record: startTime, sample count, min/max/avg sdnn.
    """
    from_ms, to_ms = _date_range_ms(from_date, to_date)
    items = _items(
        client,
        "/v2/users/me/events",
        {
            "eventType": "hrv_sdnn",
            "subType": "real_data",
            "from": from_ms,
            "to": to_ms,
            "limit": "200",
            "reverse": "false",
        },
    )
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        value = _maybe_json(it.get("value"))
        samples = value.get("samples") if isinstance(value, dict) else None
        if not isinstance(samples, list):
            samples = []
        # Prefer the inner measurement start; fall back to the event timestamp.
        ts = (value.get("startTime") if isinstance(value, dict) else None) \
            or it.get("timestamp") or it.get("time")
        sdnns = [s["sdnn"] for s in samples if isinstance(s, dict) and isinstance(s.get("sdnn"), (int, float))]
        rec = {
            "startTime": _ms_to_iso(ts),
            "sampleCount": len(samples),
            "minSdnn": min(sdnns) if sdnns else None,
            "maxSdnn": max(sdnns) if sdnns else None,
            "avgSdnn": round(sum(sdnns) / len(sdnns), 1) if sdnns else None,
        }
        out.append(rec)
    return out
