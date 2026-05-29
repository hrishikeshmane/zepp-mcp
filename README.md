# Zepp MCP

A [Model Context Protocol](https://modelcontextprotocol.io) server that gives any
MCP-capable AI agent read access to your **Zepp / Amazfit** fitness data:
workouts, runs, daily steps, distance, calories, sleep, GPS + heart-rate tracks,
and paired devices.

It authenticates against the Zepp cloud (the same data the mobile app shows)
using the 2025 encrypted `api-user.zepp.com` flow — no phone, root, or Bluetooth
required.

## Tools

| Tool | Returns |
|------|---------|
| `zepp_status` | Login state and user id |
| `get_devices` | Paired watches/bands (MAC, auth key) |
| `get_daily_summary(from_date?, to_date?)` | Per-day steps, distance (m), calories, sleep (min). ISO dates; defaults to the last 30 days |
| `list_workouts(limit=50)` | Workout sessions: `trackid`, type, distance, calories, pace, avg/max HR, city, device |
| `get_workout_detail(trackid, source?)` | Full session: GPS, altitude, pace, and HR series (`source` auto-resolves) |

Common workout `type` codes: `1` outdoor run, `6` walk, `8` treadmill,
`9` outdoor cycling, `10` indoor cycling, `49` strength/other.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- A Zepp / Amazfit account (email + password login)

## Setup

```bash
git clone https://github.com/drfittri/zepp-mcp.git
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
  agents. Remove the truncation block in `huami_client.py` (`workout_detail`) if
  you need the full raw track data.

## Credits

Login handshake powered by the [`huami-token`](https://codeberg.org/argrento/huami-token)
project.

## Disclaimer

This is an unofficial client that uses a reverse-engineered Zepp cloud API. It is
not affiliated with or endorsed by Zepp Health / Huami. Use it with your own
account and at your own risk.
