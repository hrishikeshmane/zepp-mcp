"""Live test for zepp_health_events. Logs in ONCE, reuses one client."""

import json
import os
import time

from dotenv import load_dotenv

from huami_client import HuamiClient
import zepp_health_events as h


def main():
    load_dotenv()
    client = HuamiClient(os.environ["ZEPP_EMAIL"], os.environ["ZEPP_PASSWORD"])
    client.login()
    print(f"logged in: user_id={client.user_id}, app_token set={bool(client.app_token)}\n")

    # last 60 days
    from datetime import date, timedelta
    to_date = date.today().isoformat()
    from_date = (date.today() - timedelta(days=60)).isoformat()

    funcs = [
        ("get_spo2", h.get_spo2),
        ("get_stress", h.get_stress),
        ("get_pai", h.get_pai),
        ("get_body_battery", h.get_body_battery),
        ("get_readiness", h.get_readiness),
        ("get_hrv", h.get_hrv),
    ]

    for name, fn in funcs:
        for attempt in range(2):
            try:
                res = fn(client, from_date, to_date)
                break
            except Exception as e:  # retry once on transient
                if attempt == 0:
                    print(f"{name}: error {e!r}, sleeping 10s and retrying")
                    time.sleep(10)
                else:
                    res = f"FAILED: {e!r}"
        count = len(res) if isinstance(res, list) else res
        print(f"=== {name} === count={count}")
        if isinstance(res, list) and res:
            print(json.dumps(res[0], indent=2, default=str))
        print()
        time.sleep(12)  # be gentle / avoid 429


if __name__ == "__main__":
    main()
