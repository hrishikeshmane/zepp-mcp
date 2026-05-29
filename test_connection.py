"""Standalone live test of the Zepp cloud connection. Run: uv run test_connection.py"""

import json
import os
from datetime import date, timedelta

from dotenv import load_dotenv

from huami_client import HuamiClient

load_dotenv()


def main() -> None:
    email = os.environ.get("ZEPP_EMAIL")
    password = os.environ.get("ZEPP_PASSWORD")
    if not email or not password:
        raise SystemExit("Set ZEPP_EMAIL and ZEPP_PASSWORD in .env first.")

    c = HuamiClient(email=email, password=password)
    print("Logging in...")
    c.login()
    print(f"  OK  user_id={c.user_id}")

    print("\nDevices:")
    for d in c.devices():
        print(f"  {d}")

    print("\nDaily summary (last 7 days):")
    for d in c.daily_summary(from_date=(date.today() - timedelta(days=7)).isoformat()):
        print(
            f"  {d.get('date')}: steps={d.get('steps')} "
            f"dist={d.get('distance_m')}m cal={d.get('calories')} sleep={d.get('sleep_minutes')}"
        )

    print("\nWorkouts (latest 5 of all):")
    ws = c.workouts(limit=200)
    print(f"  total sessions: {len(ws)}")
    for w in ws[:5]:
        print(
            f"  trackid={w.get('trackid')} type={w.get('type')} "
            f"dist={w.get('dis')}m cal={w.get('calorie')} hr={w.get('avg_heart_rate')} {w.get('city')}"
        )

    if ws:
        tid = str(ws[0]["trackid"])
        print(f"\nDetail for trackid={tid} (track arrays truncated):")
        det = c.workout_detail(tid)
        print(json.dumps({k: v for k, v in det.items()}, indent=2, ensure_ascii=False)[:1000])


if __name__ == "__main__":
    main()
