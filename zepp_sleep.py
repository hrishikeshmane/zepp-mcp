"""
Detailed sleep parsing for the Zepp / Amazfit cloud.

The daily `summary` blob (base64 JSON, see huami_client._maybe_b64_json) contains a
`slp` (sleep) object. The stock client only added `lt`+`dp`, which undercounts
sleep because it ignores REM and awake time. This module parses `slp` fully:
the per-night totals plus a decoded stage timeline with real clock times.

VERIFIED against live data (reverse-engineered, then confirmed numerically):
  * slp.stage[]: each {start, stop, mode}. start/stop are minute-of-day offsets
    in *device-local* time (values >1440 roll into the next day). A segment's
    duration is (stop - start + 1) minutes -- confirmed because the per-mode
    inclusive sums match lt/dp/wk exactly on every real night.
  * mode 4=light, 5=deep, 7=awake, 8=REM.
  * st = sleep start (unix epoch s), ed = sleep end (epoch s). HIGH confidence:
    (ed-st)/60 == lt+dp+rem+wk and == (last_stop - first_start + 1) on every night.
  * lt = light minutes, dp = deep minutes  -- HIGH (match stage sums).
  * There is NO `rem` field in this account's payload; REM minutes come only from
    summing mode-8 stages. We expose that as rem_minutes.
  * ss = sleep score, rhr = resting HR during sleep -- HIGH (sane values).
  * wk = awake MINUTES, wc = awake COUNT. CONFIRMED: wk always equals the summed
    minutes of mode-7 stage segments; wc is the number of awake segments (wc<=wk,
    varies independently). So the "awake pair" is wk=minutes, wc=count.
  * odd_stage[] = nap / irregular segments, same shape as stage[] -- MED (empty in
    this account's recent history, but parsed identically).
  * supRem / supNap = device supports REM / nap detection (bool) -- MED.
  * to = turn-over count -- LOW (absent in this payload; surfaced if present).
  * is / lb / obt / ebt / dt / ps / pe -- LOW / best-guess, NOT surfaced as clean
    fields to avoid mislabeling. Available under the raw blob if ever needed.
"""

from __future__ import annotations

import base64
import json
from datetime import date, datetime, timedelta, timezone

# huami_client owns the decode helper; reuse it rather than reimplementing.
from huami_client import _maybe_b64_json

MODE_MAP = {4: "light", 5: "deep", 7: "awake", 8: "rem"}


def _decode_summary(raw):
    """Base64-JSON decode a day's summary blob (same approach as huami_client)."""
    if raw is None:
        return None
    try:
        return _maybe_b64_json(raw)
    except Exception:
        # Last-ditch: never throw out of here.
        try:
            return json.loads(base64.b64decode(raw).decode("utf-8"))
        except Exception:
            return None


def _fetch_summaries(client, from_date, to_date):
    """Raw per-day summaries: list of (date_str, decoded_summary_dict).

    Fetches the band_data summary directly (client.daily_summary pre-parses and
    drops the bits we need). Retries once on a 429-shaped failure.
    """
    params = {
        "query_type": "summary",
        "device_type": "android_phone",
        "userid": client.user_id,
        "from_date": from_date,
        "to_date": to_date,
    }
    j = None
    for attempt in range(2):
        try:
            j = client._get("/v1/data/band_data.json", params)
        except Exception:
            j = None
        if isinstance(j, dict) and "data" in j:
            break
        if attempt == 0:
            import time

            time.sleep(10)  # likely HTTP 429 / transient; back off once
    out = []
    if isinstance(j, dict):
        for day in j.get("data", []) or []:
            ds = day.get("date_time") or day.get("date")
            out.append((ds, _decode_summary(day.get("summary"))))
    return out


def _decode_stages(stages, st_epoch):
    """Decode a stage[] (or odd_stage[]) list into a clean timeline.

    Returns list of {stage, start:'HH:MM', end:'HH:MM', minutes}. Clock times are
    derived by anchoring the first segment's offset to `st_epoch` (sleep start)
    and rendering each segment in the device-local timezone inferred from st.
    Minutes are inclusive (stop - start + 1), which matches the device totals.
    Day rollover (offset > 1440) is handled implicitly by the epoch arithmetic.
    """
    timeline = []
    if not isinstance(stages, list) or not stages:
        return timeline

    # Establish the anchor: first segment start offset == local clock of st_epoch.
    first_off = None
    for seg in stages:
        if isinstance(seg, dict) and isinstance(seg.get("start"), (int, float)):
            first_off = int(seg["start"])
            break

    tz = timezone.utc
    if st_epoch is not None and first_off is not None:
        # Infer the device-local tz offset: find the whole-hour offset whose
        # minute-of-day for st_epoch matches the first stage offset (mod 1440).
        target = first_off % 1440
        chosen = None
        for tzoff in range(-12, 15):
            local = datetime.fromtimestamp(st_epoch, tz=timezone(timedelta(hours=tzoff)))
            if local.hour * 60 + local.minute == target:
                chosen = tzoff
                break
        if chosen is None:
            # Try half-hour offsets (India etc.) before giving up.
            for half in range(-24, 29):
                tzoff = half / 2.0
                local = datetime.fromtimestamp(st_epoch, tz=timezone(timedelta(hours=tzoff)))
                if local.hour * 60 + local.minute == target:
                    chosen = tzoff
                    break
        if chosen is not None:
            tz = timezone(timedelta(hours=chosen))

    def clock(offset):
        if offset is None:
            return None
        if st_epoch is not None and first_off is not None:
            ep = st_epoch + (int(offset) - first_off) * 60
            return datetime.fromtimestamp(ep, tz=tz).strftime("%H:%M")
        # Fallback: pure minute-of-day with day rollover.
        m = int(offset) % 1440
        return f"{m // 60:02d}:{m % 60:02d}"

    for seg in stages:
        if not isinstance(seg, dict):
            continue
        start = seg.get("start")
        stop = seg.get("stop")
        mode = seg.get("mode")
        if start is None or stop is None:
            continue
        minutes = int(stop) - int(start) + 1
        label = MODE_MAP.get(mode, f"unknown_{mode}")
        timeline.append(
            {
                "stage": label,
                "start": clock(start),
                "end": clock(stop),
                "minutes": minutes,
            }
        )
    return timeline


def _iso(epoch_seconds):
    if epoch_seconds is None:
        return None
    try:
        return datetime.fromtimestamp(int(epoch_seconds), tz=timezone.utc).astimezone().isoformat()
    except Exception:
        return None


def _num(v):
    return v if isinstance(v, (int, float)) else None


def _parse_night(date_str, slp):
    """Turn one slp object into a clean night dict. Never throws."""
    if not isinstance(slp, dict):
        return None
    st = _num(slp.get("st"))
    ed = _num(slp.get("ed"))
    stages_raw = slp.get("stage") if isinstance(slp.get("stage"), list) else []
    odd_raw = slp.get("odd_stage") if isinstance(slp.get("odd_stage"), list) else []

    timeline = _decode_stages(stages_raw, st)
    naps = _decode_stages(odd_raw, st) if odd_raw else []

    # Per-mode minutes from the decoded timeline (source of truth for REM, which
    # has no dedicated field). Device fields lt/dp/wk match these inclusive sums.
    mode_minutes = {"light": 0, "deep": 0, "awake": 0, "rem": 0}
    for seg in timeline:
        if seg["stage"] in mode_minutes:
            mode_minutes[seg["stage"]] += seg["minutes"]

    # Prefer device fields where present, fall back to stage sums.
    light = _num(slp.get("lt"))
    deep = _num(slp.get("dp"))
    rem = _num(slp.get("rem"))
    awake = _num(slp.get("wk"))
    if light is None:
        light = mode_minutes["light"] or None
    if deep is None:
        deep = mode_minutes["deep"] or None
    if rem is None:
        rem = mode_minutes["rem"] or None
    if awake is None:
        awake = mode_minutes["awake"] or None

    # time in bed: epoch span is authoritative; else sum of stage minutes.
    time_in_bed = None
    if st is not None and ed is not None and ed > st:
        time_in_bed = int(round((ed - st) / 60))
    elif timeline:
        time_in_bed = sum(s["minutes"] for s in timeline)

    total_sleep = None
    parts = [p for p in (light, deep, rem) if p is not None]
    if parts:
        total_sleep = int(sum(parts))

    return {
        "date": date_str,
        "sleep_start": _iso(st),
        "sleep_end": _iso(ed),
        "time_in_bed_minutes": time_in_bed,
        "deep_minutes": int(deep) if deep is not None else None,
        "light_minutes": int(light) if light is not None else None,
        "rem_minutes": int(rem) if rem is not None else None,
        "awake_minutes": int(awake) if awake is not None else None,
        "total_sleep_minutes": total_sleep,
        "sleep_score": _num(slp.get("ss")),
        "resting_hr": _num(slp.get("rhr")),
        "awake_count": _num(slp.get("wc")),
        "turn_over_count": _num(slp.get("to")),
        "supports_rem": slp.get("supRem") if isinstance(slp.get("supRem"), bool) else None,
        "supports_nap": slp.get("supNap") if isinstance(slp.get("supNap"), bool) else None,
        "stages": timeline,
        "naps": naps,
    }


def get_sleep_detail(client, from_date=None, to_date=None):
    """Detailed per-night sleep for a Zepp account.

    Args:
        client: a logged-in HuamiClient (call .login() first).
        from_date, to_date: ISO 'YYYY-MM-DD'. Default = last 14 days.

    Returns:
        list[dict], one entry per night that has real sleep data, sorted by date.
        Each dict has: date, sleep_start, sleep_end, time_in_bed_minutes,
        deep_minutes, light_minutes, rem_minutes, awake_minutes,
        total_sleep_minutes, sleep_score, resting_hr, awake_count,
        turn_over_count, supports_rem, supports_nap, stages[], naps[].

    A night is filed under the date the user FELL ASLEEP, not woke up. So to make
    sure "last night" relative to to_date is captured, we fetch one extra day on
    the leading edge (from_date - 1) and let the date field reflect the fall-asleep
    day. Robust to missing fields; never raises.
    """
    today = date.today()
    to_d = to_date or today.isoformat()
    from_d = from_date or (today - timedelta(days=14)).isoformat()

    # Pull one extra leading day so a sleep filed under (from_d - 1) but spanning
    # into from_d is still available to callers asking about that range.
    try:
        fetch_from = (date.fromisoformat(from_d) - timedelta(days=1)).isoformat()
    except Exception:
        fetch_from = from_d

    nights = []
    seen = set()
    for date_str, summary in _fetch_summaries(client, fetch_from, to_d):
        slp = summary.get("slp") if isinstance(summary, dict) else None
        if not isinstance(slp, dict):
            continue
        # Skip empty/placeholder nights (no stages and no sleep start).
        has_stages = isinstance(slp.get("stage"), list) and len(slp.get("stage")) > 0
        has_window = _num(slp.get("st")) and _num(slp.get("ed")) and slp["ed"] > slp["st"]
        if not has_stages and not has_window:
            continue
        night = _parse_night(date_str, slp)
        if night is None:
            continue
        key = night["date"]
        if key in seen:
            continue
        seen.add(key)
        nights.append(night)

    nights.sort(key=lambda n: n["date"] or "")
    return nights
