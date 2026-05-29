"""
Zepp MCP server (stdio). Exposes Zepp/Amazfit cloud data to any MCP-capable
AI agent: workouts, daily steps/sleep/calories, workout detail, profile.

Credentials come from env: ZEPP_EMAIL, ZEPP_PASSWORD (load via .env).
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from huami_client import HuamiClient, HuamiError

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


if __name__ == "__main__":
    mcp.run()
