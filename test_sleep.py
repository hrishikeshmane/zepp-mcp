"""Live test of zepp_sleep.get_sleep_detail. Run: uv run python test_sleep.py

Logs in ONCE, reuses the client, pretty-prints a few nights with their stage
timeline, and sanity-checks the totals (deep+light+rem+awake ~= time in bed).
"""

import json
import os
from datetime import date, timedelta

from dotenv import load_dotenv

from huami_client import HuamiClient
from zepp_sleep import get_sleep_detail

load_dotenv()


def main():
    email = os.environ.get("ZEPP_EMAIL")
    password = os.environ.get("ZEPP_PASSWORD")
    if not email or not password:
        raise SystemExit("Set ZEPP_EMAIL and ZEPP_PASSWORD in .env first.")

    client = HuamiClient(email=email, password=password)
    print("Logging in (once)...")
    client.login()
    print(f"  OK  user_id={client.user_id}")

    frm = (date.today() - timedelta(days=14)).isoformat()
    nights = get_sleep_detail(client, from_date=frm)
    print(f"\nGot {len(nights)} nights with sleep data "
          f"(range {frm} .. {date.today().isoformat()})\n")

    # Print the last 3 nights with full detail.
    for night in nights[-3:]:
        print("=" * 64)
        print(f"DATE {night['date']}   score={night['sleep_score']} "
              f"rhr={night['resting_hr']}")
        print(f"  in bed:  {night['sleep_start']} -> {night['sleep_end']}")
        d = night["deep_minutes"] or 0
        l = night["light_minutes"] or 0
        r = night["rem_minutes"] or 0
        a = night["awake_minutes"] or 0
        tib = night["time_in_bed_minutes"]
        print(f"  minutes: deep={d} light={l} rem={r} awake={a}  "
              f"total_sleep={night['total_sleep_minutes']}  in_bed={tib}")
        print(f"  awake_count={night['awake_count']} turn_over={night['turn_over_count']} "
              f"supRem={night['supports_rem']} supNap={night['supports_nap']}")
        # sanity: deep+light+rem+awake should ~= time in bed
        summ = d + l + r + a
        delta = (summ - tib) if tib is not None else None
        flag = "OK" if (delta is not None and abs(delta) <= 3) else "CHECK"
        print(f"  SANITY: d+l+r+awake={summ} vs in_bed={tib}  (delta={delta}) [{flag}]")
        print(f"  stage timeline ({len(night['stages'])} segments):")
        for seg in night["stages"]:
            print(f"     {seg['start']} - {seg['end']}  {seg['stage']:<7} {seg['minutes']:>3}m")
        if night["naps"]:
            print(f"  naps ({len(night['naps'])}): {json.dumps(night['naps'])}")

    print("\n--- one full night as JSON ---")
    if nights:
        print(json.dumps(nights[-1], indent=2))


if __name__ == "__main__":
    main()
