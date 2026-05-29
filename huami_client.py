"""
Zepp / Amazfit cloud data client.

Login uses the maintained `huami-token` lib (handles the 2025 encrypted
`api-user.zepp.com` handshake that the old plain flow gets 429'd on).
Data queries are issued here against api-mifit.zepp.com with the app_token.

No phone needed — all history lives in the Zepp cloud.
"""

from __future__ import annotations

import base64
import json
import sys
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta

import requests
from loguru import logger

from huami_token.constants import HEADERS, MAGIC
from huami_token.zepp import ZeppClient, ZeppSession

# Silence the lib's DEBUG/INFO logging so credentials/tokens never hit stdout.
logger.remove()
logger.add(sys.stderr, level="WARNING")

DATA_HOST = "api-mifit.zepp.com"


class HuamiError(RuntimeError):
    pass


def _data_headers(app_token: str) -> dict:
    h = HEADERS.ZEPP_DEVICES.value.copy()
    h["apptoken"] = app_token
    h["x-request-id"] = str(uuid.uuid4())
    return h


@dataclass
class HuamiClient:
    email: str
    password: str
    session: ZeppSession | None = None
    _http: requests.Session = field(default_factory=requests.Session)
    _source_cache: dict[str, str] = field(default_factory=dict)

    # ---- auth -----------------------------------------------------------

    def login(self) -> None:
        self.session = ZeppSession(self.email, self.password)
        self.session.login()

    @property
    def app_token(self) -> str | None:
        return self.session._app_token if self.session else None

    @property
    def user_id(self) -> str | None:
        return self.session._user_id if self.session else None

    def _ensure(self) -> None:
        if not self.session or not self.session._app_token:
            self.login()

    def _get(self, path: str, params: dict) -> dict:
        self._ensure()
        url = f"https://{DATA_HOST}{path}"
        r = self._http.get(
            url, headers=_data_headers(self.app_token), params=params, timeout=30
        )
        try:
            return r.json()
        except ValueError:
            raise HuamiError(f"{path} -> {r.status_code} non-JSON: {r.text[:300]}")

    # ---- data -----------------------------------------------------------

    def devices(self) -> list[dict]:
        self._ensure()
        return [d.__dict__ for d in ZeppClient(self.session).get_devices()]

    def daily_summary(self, from_date: str | None = None, to_date: str | None = None) -> list[dict]:
        """Per-day steps / distance / calories / sleep. Dates ISO YYYY-MM-DD."""
        to_d = to_date or date.today().isoformat()
        from_d = from_date or (date.today() - timedelta(days=30)).isoformat()
        j = self._get(
            "/v1/data/band_data.json",
            {
                "query_type": "summary",
                "device_type": "android_phone",
                "userid": self.user_id,
                "from_date": from_d,
                "to_date": to_d,
            },
        )
        out = []
        for day in j.get("data", []):
            entry = {"date": day.get("date_time") or day.get("date")}
            raw = day.get("summary")
            if raw:
                summary = _maybe_b64_json(raw)
                entry["summary"] = summary
                if isinstance(summary, dict):
                    stp = summary.get("stp", {})
                    slp = summary.get("slp", {})
                    entry["steps"] = stp.get("ttl")
                    entry["distance_m"] = stp.get("dis")
                    entry["calories"] = stp.get("cal")
                    if slp:
                        entry["sleep_minutes"] = (slp.get("lt", 0) + slp.get("dp", 0)) or slp.get("stage")
            out.append(entry)
        return out

    def workouts(self, limit: int = 50) -> list[dict]:
        """List workout/sport sessions. Each has a `trackid` for detail."""
        j = self._get(
            "/v1/sport/run/history.json",
            {"source": "run.mi.com", "userid": self.user_id, "limit": str(limit)},
        )
        items = _extract_list(j)
        for w in items:
            if isinstance(w, dict) and w.get("trackid") and w.get("source"):
                self._source_cache[str(w["trackid"])] = w["source"]
        return items

    def workout_detail(self, trackid: str, source: str | None = None) -> dict:
        """Full track for one workout: GPS, pace, HR series, summary.
        `source` auto-resolves from recent workouts if omitted."""
        trackid = str(trackid)
        if source is None:
            source = self._source_cache.get(trackid)
            if source is None:
                self.workouts(limit=200)  # populate source cache
                source = self._source_cache.get(trackid, "run.mi.com")
        j = self._get(
            "/v1/sport/run/detail.json",
            {"trackid": str(trackid), "source": source, "userid": self.user_id},
        )
        data = j.get("data", j)
        if isinstance(data, dict):
            for k in ("longitude_latitude", "heart_rate", "pace", "altitude", "time", "gait"):
                v = data.get(k)
                if isinstance(v, str) and len(v) > 200:
                    data[k] = {"_encoded_len": len(v), "_sample": v[:120]}
        return data


def _maybe_b64_json(raw):
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(base64.b64decode(raw).decode("utf-8"))
    except Exception:
        try:
            return json.loads(raw)
        except Exception:
            return {"_raw": raw}


def _extract_list(j: dict) -> list[dict]:
    data = j.get("data", j)
    if isinstance(data, dict):
        summary = data.get("summary")
        if isinstance(summary, str):
            try:
                summary = json.loads(summary)
            except Exception:
                pass
        if isinstance(summary, dict) and isinstance(summary.get("data"), list):
            return summary["data"]
        if isinstance(summary, list):
            return summary
        if isinstance(data.get("items"), list):
            return data["items"]
    if isinstance(data, list):
        return data
    return [{"_raw": j}]
