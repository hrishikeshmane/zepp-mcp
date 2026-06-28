"""Live test for zepp_sports decoders. Run: uv run python test_sports.py

Logs in ONCE and reuses the client. On HTTP 429 the client layer is shared,
so we sleep+retry once around the calls that hit the network.
"""

import os
import time

from dotenv import load_dotenv

from huami_client import HuamiClient
from zepp_sports import decode_sport_type, enrich_workouts, decode_workout_series

load_dotenv()


def with_retry(fn):
    """Run fn(); on a 429-ish error sleep 10s and retry once."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        if "429" in str(e):
            print("  hit 429, sleeping 10s and retrying once...")
            time.sleep(10)
            return fn()
        raise


def main() -> None:
    email = os.environ.get("ZEPP_EMAIL")
    password = os.environ.get("ZEPP_PASSWORD")
    if not email or not password:
        raise SystemExit("Set ZEPP_EMAIL and ZEPP_PASSWORD in .env first.")

    client = HuamiClient(email=email, password=password)
    print("Logging in...")
    client.login()
    print(f"  OK user_id={client.user_id}")

    print("\n=== enrich_workouts(limit=10) ===")
    rows = with_retry(lambda: enrich_workouts(client, limit=10))
    hdr = f"{'trackid':<14}{'type':>5}  {'type_name':<20}{'date':<22}{'dist':>8}{'cal':>7}{'avghr':>6}{'dur':>7}"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(
            f"{str(r['trackid']):<14}{str(r['type']):>5}  {r['type_name']:<20}"
            f"{str(r['date']):<22}{str(r['distance']):>8}{str(r['calories']):>7}"
            f"{str(r['avg_hr']):>6}{str(r['duration']):>7}"
        )

    # sanity-check the requested mappings
    print("\nspot-check decode_sport_type:")
    for code in (1, 6, 8, 16, 223, 241, 9, 10, 23, 92):
        print(f"  {code} -> {decode_sport_type(code)}")

    # --- pick a workout that has GPS/HR data --------------------------------
    # Probe truncated detail to see which series carry data. The truncated
    # detail replaces long (>200 char) series with {_encoded_len,...}; we read
    # that to find a GPS- or HR-bearing workout. Prefer GPS.
    print("\n=== probing workouts for GPS/HR data ===")
    gps_choice = None
    hr_choice = None

    def series_len(det, key):
        v = det.get(key)
        if isinstance(v, dict):
            return v.get("_encoded_len", 0)
        return len(v) if isinstance(v, str) else 0

    for r in rows:
        tid = str(r["trackid"])
        det = with_retry(lambda t=tid: client.workout_detail(t))
        ll_len = series_len(det, "longitude_latitude")
        hr_len = series_len(det, "heart_rate")
        print(f"  trackid={tid} type={r['type']}({r['type_name']}) gps_len={ll_len} hr_len={hr_len}")
        if ll_len > 10 and gps_choice is None:
            gps_choice = tid
        if hr_len > 10 and hr_choice is None:
            hr_choice = tid
        if gps_choice:
            break

    chosen = gps_choice or hr_choice
    if chosen is None:
        print("No workout with GPS/HR data found in the sample.")
        return
    print(f"\nchose trackid={chosen} (gps={'yes' if gps_choice else 'no'})")

    print(f"\n=== decode_workout_series(trackid={chosen}) ===")
    dec = with_retry(lambda: decode_workout_series(client, chosen, max_points=20))
    import json

    print("summary:")
    print(json.dumps(dec["summary"], indent=2))

    hr_series = dec["heart_rate"]
    hr_samples = hr_series["samples"] if isinstance(hr_series, dict) else hr_series
    print("\nfirst 5 HR samples:")
    for s in hr_samples[:5]:
        print(f"  {s}")

    gps_series = dec["gps"]
    gps_samples = gps_series["samples"] if isinstance(gps_series, dict) else gps_series
    print("\nfirst 5 GPS points:")
    for p in gps_samples[:5]:
        print(f"  {p}")


if __name__ == "__main__":
    main()
