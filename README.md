# Zepp MCP

MCP server that gives any AI agent read access to your **Zepp / Amazfit** cloud
data: workouts, runs, daily steps, distance, calories, sleep, GPS + heart-rate
tracks, and paired devices.

No phone, root, or Bluetooth needed — it logs into the Zepp cloud (the same data
the app shows) using the 2025 encrypted `api-user.zepp.com` flow.

## Tools

| Tool | Returns |
|------|---------|
| `zepp_status` | Login state + user id |
| `get_devices` | Paired watches/bands (MAC, auth key) |
| `get_daily_summary(from_date?, to_date?)` | Per-day steps, distance(m), calories, sleep(min). ISO dates, default last 30d |
| `list_workouts(limit=50)` | Workout sessions: `trackid`, type, distance, calories, pace, avg/max HR, city, device |
| `get_workout_detail(trackid, source?)` | Full session: GPS, altitude, pace, HR series (`source` auto-resolves) |

Workout `type` codes (common): `1`=outdoor run, `6`=walk, `8`=treadmill,
`9`=outdoor cycling, `10`=indoor cycling, `49`=strength/other.

## Setup

```bash
cd /Users/fittri/Desktop/zepp-mcp
uv sync                            # install deps
cp .env.example .env               # put your Zepp email + password in .env
uv run python test_connection.py   # live connection test
```

## Connect an AI agent

Add to the agent's MCP config (Claude Desktop `claude_desktop_config.json`,
Claude Code `.mcp.json`, Cursor, etc.). Credentials can live in `.env` or inline
in the `env` block:

```json
{
  "mcpServers": {
    "zepp": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/Users/fittri/Desktop/zepp-mcp",
        "python",
        "server.py"
      ],
      "env": {
        "ZEPP_EMAIL": "you@example.com",
        "ZEPP_PASSWORD": "your-zepp-password"
      }
    }
  }
}
```

If you keep credentials in `.env`, drop the `"env"` block — `server.py` auto-loads `.env`.

## Wired integrations (this machine)

Already registered — no action needed:

- **Claude Code** — user scope (`~/.claude.json`). Verify: `claude mcp list | grep zepp`.
- **Hermes** — `~/.hermes/config.yaml` under `mcp_servers.zepp`.

Both launch via `uv run --directory /Users/fittri/Desktop/zepp-mcp python server.py`,
so credentials are read from this folder's `.env` (not stored in either config).

## Security

- `.env` is git-ignored. Never commit credentials.
- Login is over HTTPS; tokens are held in memory only.
- The underlying `huami-token` lib logs DEBUG by default; this server silences it
  to `WARNING` so credentials/tokens never print.

## Notes

- Region auto-handled (account-bound; tested SEA/Malaysia -> US2 servers).
- GPS/HR/altitude arrays in `get_workout_detail` are truncated to a sample +
  length to stay token-friendly. Remove the truncation block in
  `huami_client.py:workout_detail` for the full raw track.
