"""
Zepp MCP server (stdio). Exposes Zepp/Amazfit cloud data to any MCP-capable
AI agent: workouts, daily steps/sleep/calories, detailed sleep stages, workout
detail with decoded GPS/HR tracks, and health metrics (SpO2, stress, PAI, body
battery, readiness, HRV).

Credentials come from env: ZEPP_EMAIL, ZEPP_PASSWORD (load via .env).
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from huami_client import HuamiClient, HuamiError
from zepp_health_events import (
    get_body_battery as _get_body_battery,
    get_hrv as _get_hrv,
    get_pai as _get_pai,
    get_readiness as _get_readiness,
    get_spo2 as _get_spo2,
    get_stress as _get_stress,
)
from zepp_sleep import get_sleep_detail as _get_sleep_detail
from zepp_sports import decode_workout_series as _decode_workout_series, enrich_workouts as _enrich_workouts

load_dotenv()

mcp = FastMCP("zepp")

_client: HuamiClient | None = None


def client() -> HuamiClient:
    global _client
    if _client is None:
        email = os.environ.get("ZEPP_EMAIL")
        password = os.environ.get("ZEPP_PASSWORD")
        if not email or not password:
            raise HuamiError("Set ZEPP_EMAIL and ZEPP_PASSWORD (in .env or env).")
        _client = HuamiClient(email=email, password=password)
        _client.login()
    return _client


@mcp.tool()
def zepp_status() -> dict:
    """Check Zepp cloud login and which region host is in use."""
    c = client()
    return {
        "logged_in": bool(c.app_token),
        "user_id": c.user_id,
        "data_host": c.data_host,
    }


@mcp.tool()
def list_workouts(limit: int = 50) -> list[dict]:
    """List recent workout/sport sessions (runs, walks, cycling, etc).
    Each item includes a `trackid` usable with get_workout_detail."""
    return client().workouts(limit=limit)


@mcp.tool()
def get_workout_detail(trackid: str, source: str = "run.mi.com") -> dict:
    """Full detail for one workout: GPS track, pace, heart-rate series, etc.
    Pass a trackid from list_workouts."""
    return client().workout_detail(trackid, source=source)


@mcp.tool()
def get_daily_summary(from_date: str | None = None, to_date: str | None = None) -> list[dict]:
    """Per-day steps, distance, calories, and sleep summary.
    Dates are ISO YYYY-MM-DD. Defaults to the last 30 days."""
    return client().daily_summary(from_date=from_date, to_date=to_date)


@mcp.tool()
def get_devices() -> list[dict]:
    """List paired Zepp/Amazfit devices (watch/band) on the account."""
    return client().devices()


@mcp.tool()
def list_workouts_named(limit: int = 50) -> list[dict]:
    """List recent workouts with human-readable sport names (type_name) plus
    distance, calories, avg HR, duration and date. Cleaner than list_workouts."""
    return _enrich_workouts(client(), limit=limit)


@mcp.tool()
def get_workout_track(trackid: str, source: str | None = None,
                      include_full: bool = False, max_points: int = 50) -> dict:
    """Decoded workout track: GPS coordinates, heart-rate series, altitude, pace,
    distance and summary stats for one workout. Pass a trackid from a list tool.
    Long series are downsampled to max_points unless include_full=True."""
    return _decode_workout_series(client(), trackid, source=source,
                                  include_full=include_full, max_points=max_points)


@mcp.tool()
def get_sleep_detail(from_date: str | None = None, to_date: str | None = None) -> list[dict]:
    """Detailed per-night sleep: deep/light/REM/awake minutes, sleep score,
    resting HR, and a decoded stage timeline. Dates ISO YYYY-MM-DD, default last 14 days."""
    return _get_sleep_detail(client(), from_date=from_date, to_date=to_date)


@mcp.tool()
def get_spo2(from_date: str | None = None, to_date: str | None = None) -> list[dict]:
    """Blood oxygen (SpO2) readings/events. Dates ISO YYYY-MM-DD, default last 30 days."""
    return _get_spo2(client(), from_date=from_date, to_date=to_date)


@mcp.tool()
def get_stress(from_date: str | None = None, to_date: str | None = None,
               include_series: bool = False) -> list[dict]:
    """All-day stress: per-day min/max/avg and zone proportions. Set include_series
    for the intraday points. Dates ISO YYYY-MM-DD, default last 30 days."""
    return _get_stress(client(), from_date=from_date, to_date=to_date,
                       include_series=include_series)


@mcp.tool()
def get_pai(from_date: str | None = None, to_date: str | None = None) -> list[dict]:
    """PAI (Personal Activity Intelligence): daily/total PAI, resting & max HR,
    HR-zone breakdown. Dates ISO YYYY-MM-DD, default last 30 days."""
    return _get_pai(client(), from_date=from_date, to_date=to_date)


@mcp.tool()
def get_body_battery(from_date: str | None = None, to_date: str | None = None) -> list[dict]:
    """Body battery / energy (physical & mental) levels per day. Dates ISO
    YYYY-MM-DD, default last 30 days."""
    return _get_body_battery(client(), from_date=from_date, to_date=to_date)


@mcp.tool()
def get_readiness(from_date: str | None = None, to_date: str | None = None) -> list[dict]:
    """Daily readiness score with sleep HRV, sleep resting HR, skin temperature
    and component scores. Dates ISO YYYY-MM-DD, default last 30 days."""
    return _get_readiness(client(), from_date=from_date, to_date=to_date)


@mcp.tool()
def get_hrv(from_date: str | None = None, to_date: str | None = None) -> list[dict]:
    """Heart-rate variability (SDNN): per-record min/max/avg. Dates ISO
    YYYY-MM-DD, default last 30 days."""
    return _get_hrv(client(), from_date=from_date, to_date=to_date)


if __name__ == "__main__":
    mcp.run()
