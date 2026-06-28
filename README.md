# Zepp MCP

A [Model Context Protocol](https://modelcontextprotocol.io) server that gives any
MCP-capable AI agent read access to your **Zepp / Amazfit** fitness data:
workouts, runs, daily steps, distance, calories, detailed sleep stages,
GPS + heart-rate tracks, and health metrics (SpO2, stress, PAI, body battery,
readiness, HRV) — plus paired devices.

It authenticates against the Zepp cloud (the same data the mobile app shows)
using the 2025 encrypted `api-user.zepp.com` flow — no phone, root, or Bluetooth
required.

## Tools

### Core

| Tool | Returns |
|------|---------|
| `zepp_status` | Login state, user id, and the resolved data host |
| `get_devices` | Paired watches/bands (MAC, auth key) |
| `get_daily_summary(from_date?, to_date?)` | Per-day steps, distance (m), calories, sleep (min). ISO dates; defaults to the last 30 days |
| `list_workouts(limit=50)` | Raw workout sessions: `trackid`, type, distance, calories, pace, avg/max HR, city, device |
| `list_workouts_named(limit=50)` | Workouts enriched with a human-readable `type_name`, plus distance, calories, avg HR, duration, and date |
| `get_workout_detail(trackid, source?)` | Full raw session: GPS, altitude, pace, and HR series (`source` auto-resolves; long arrays truncated) |
| `get_workout_track(trackid, source?, include_full=False, max_points=50)` | Decoded track: GPS coordinates, HR series, altitude, pace, distance + summary stats. Long series downsampled unless `include_full=True` |

### Sleep

| Tool | Returns |
|------|---------|
| `get_sleep_detail(from_date?, to_date?)` | Per-night deep/light/REM/awake minutes, sleep score, resting HR, awake count, and a decoded stage timeline. Defaults to the last 14 days |

### Health metrics

| Tool | Returns |
|------|---------|
| `get_spo2(from_date?, to_date?)` | Blood-oxygen (SpO2) readings and events |
| `get_stress(from_date?, to_date?, include_series=False)` | All-day stress: per-day min/max/avg and zone proportions; optional intraday series |
| `get_pai(from_date?, to_date?)` | PAI (Personal Activity Intelligence): daily/total PAI, resting & max HR, HR-zone breakdown |
| `get_body_battery(from_date?, to_date?)` | Body-battery / energy (physical & mental) levels |
| `get_readiness(from_date?, to_date?)` | Daily readiness score with sleep HRV, sleep resting HR, skin temperature, and component scores |
| `get_hrv(from_date?, to_date?)` | Heart-rate variability (SDNN): per-record min/max/avg |

All date arguments are ISO `YYYY-MM-DD` and default to a recent window (30 days,
or 14 for sleep). Data is available back to the account's creation date; requests
for earlier dates simply return nothing.

Common workout `type` codes: `1` running, `6` walking, `8` treadmill,
`9` outdoor cycling, `10` indoor cycling, `16` other, `23` indoor rowing,
`92` badminton. Unknown codes are surfaced as `unknown_<n>`.

> **Availability note:** health metrics (SpO2, stress, PAI, body battery,
> readiness, HRV) and detailed sleep depend on your device's sensors and the
> features you have enabled. Tools return an empty list when no data exists.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- A Zepp / Amazfit account (email + password login)

## Setup

```bash
git clone https://github.com/hrishikeshmane/zepp-mcp.git
cd zepp-mcp
uv sync                            # install dependencies
cp .env.example .env               # then add your Zepp credentials to .env
uv run python test_connection.py   # verify the live connection
```

## Configuration

Credentials are read from environment variables, loaded from a local `.env`
file:

```ini
ZEPP_EMAIL=you@example.com
ZEPP_PASSWORD=your-zepp-password
```

`.env` is listed in `.gitignore` and is never committed.

## Connecting an AI agent

Add the server to your agent's MCP configuration — for example Claude Desktop
(`claude_desktop_config.json`), Claude Code (`.mcp.json`), or Cursor. Replace
`/path/to/zepp-mcp` with the absolute path to your clone:

```json
{
  "mcpServers": {
    "zepp": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/path/to/zepp-mcp",
        "python",
        "server.py"
      ]
    }
  }
}
```

`uv run --directory` sets the working directory so the server loads credentials
from that folder's `.env`. If you prefer to pass credentials inline instead, add
an `"env"` block (not recommended for shared or committed config files):

```json
"env": {
  "ZEPP_EMAIL": "you@example.com",
  "ZEPP_PASSWORD": "your-zepp-password"
}
```

## Security

- Credentials live only in your local `.env`, which is git-ignored. Never commit
  real credentials, and avoid inlining them in MCP config files that may be
  shared or version-controlled.
- All traffic is over HTTPS; session tokens are held in memory only.
- The upstream `huami-token` library logs at DEBUG by default; this server raises
  its log level to `WARNING` so credentials and tokens are never printed.

## Notes

- The region is resolved automatically from the account at login.
- GPS, heart-rate, and altitude arrays returned by `get_workout_detail` are
  truncated to a short sample plus a length count to stay token-efficient for
  agents. Use `get_workout_track` for decoded series, or remove the truncation
  block in `huami_client.py` (`workout_detail`) for the full raw track data.
- A cached `app_token` can go stale during a long-lived server process. The
  client detects Zepp's "invalid token" rejection and transparently re-logs in
  once before retrying, so results never silently contain an error body.
- The Zepp cloud rate-limits aggressively (HTTP 429), including the login
  endpoint. The server logs in once and reuses the session; if you issue many
  health-metric calls in quick succession, space them out.

## Project layout

- `server.py` — FastMCP server; registers every tool.
- `huami_client.py` — authenticated Zepp cloud client (login, daily summary,
  workouts, devices) with stale-token self-healing.
- `zepp_sleep.py` — detailed sleep-stage parsing (`get_sleep_detail`).
- `zepp_sports.py` — sport-type decoding and workout track decoding
  (`list_workouts_named`-style enrichment, `get_workout_track`).
- `zepp_health_events.py` — health-metric event readers (SpO2, stress, PAI,
  body battery, readiness, HRV).

## About this fork

This is a fork of [`drfittri/zepp-mcp`](https://github.com/drfittri/zepp-mcp),
which provided the original server and the core tools (`zepp_status`,
`get_devices`, `get_daily_summary`, `list_workouts`, `get_workout_detail`).

This fork adds:

- **Health metrics** — `get_spo2`, `get_stress`, `get_pai`, `get_body_battery`,
  `get_readiness`, `get_hrv` (via the `/users/{uid}/events` and
  `/v2/users/me/events` endpoints).
- **Detailed sleep** — `get_sleep_detail` (decoded stage timeline with
  deep/light/REM/awake minutes, sleep score, and resting HR).
- **Decoded workouts** — `list_workouts_named` (human-readable sport types) and
  `get_workout_track` (decoded GPS / heart-rate / altitude / pace series).
- **Stale-token self-healing** — the client detects Zepp's "invalid token"
  rejection and transparently re-authenticates once before retrying.

## Credits

- Original MCP server: [`drfittri/zepp-mcp`](https://github.com/drfittri/zepp-mcp).
- Login handshake powered by the [`huami-token`](https://codeberg.org/argrento/huami-token)
  project.

## Disclaimer

This is an unofficial client that uses a reverse-engineered Zepp cloud API. It is
not affiliated with or endorsed by Zepp Health / Huami. Use it with your own
account and at your own risk.
