"""
parse_fit.py

Reads a single .fit file and outputs structured JSON with:
- session summary (sport, sub_sport, duration, distance, avg/max HR, calories,
  ascent/descent if present, training load if present)
- HR-time series (timestamp, hr, distance, speed, cadence, power if present)
- HR zone distribution (uses ZONE_BOUNDS from _session_lib — absolute bpm
  cutoffs, single source of truth across the project)
- lap summaries

If a .fit file cannot be decoded, the error is logged and the script exits 0
without crashing the rest of any pipeline that calls it. (Stop condition:
fitparse cannot decode → log it and skip.)

Usage:
    python scripts/parse_fit.py path/to/file.fit
    python scripts/parse_fit.py path/to/file.fit --out path/to/out.json
    python scripts/parse_fit.py path/to/file.fit --lthr 172
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

try:
    from fitparse import FitFile, FitParseError
except ImportError:
    sys.stderr.write(
        "fitparse is not installed. Run: pip install -e .\n"
    )
    sys.exit(1)


# Zone definition lives in scripts/_session_lib.py — single source of truth
# for the whole project. Both this CLI and the rest of the helpers
# (weekly_summary, feedback_session, dashboard) use the same ZONE_BOUNDS
# (absolute bpm cutoffs anchored to the project LTHR), so a session zoned
# by either path produces the same numbers.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _session_lib import LTHR as DEFAULT_LTHR, ZONE_BOUNDS, hr_zone_of  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Parse a .fit file into structured JSON.")
    p.add_argument("fit_path", type=str, help="Path to the .fit file.")
    p.add_argument("--out", type=str, default=None, help="Output JSON path (default: alongside input).")
    p.add_argument("--lthr", type=int, default=DEFAULT_LTHR,
                   help=f"LTHR stored in output JSON as `lthr_used` (default {DEFAULT_LTHR}). "
                        "Note: ZONE_BOUNDS are absolute bpm cutoffs from "
                        "_session_lib, NOT recomputed from --lthr.")
    return p.parse_args()


def to_jsonable(v):
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray)):
        try:
            return v.decode("utf-8", errors="replace")
        except Exception:
            return str(v)
    return v


def record_to_dict(record) -> dict:
    return {f.name: to_jsonable(f.value) for f in record}


def summarize_zones(samples: list[dict]) -> dict:
    """Distribute time across zones using consecutive timestamp deltas.

    Zone classification uses the absolute bpm cutoffs defined in
    _session_lib.ZONE_BOUNDS (single source of truth).
    """
    seconds_in_zone = {name: 0.0 for name, _, _ in ZONE_BOUNDS}
    prev_ts = None
    prev_hr = None
    for s in samples:
        ts = s.get("timestamp")
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts)
            except Exception:
                ts = None
        hr = s.get("heart_rate")
        if prev_ts is not None and ts is not None and prev_hr is not None:
            dt = (ts - prev_ts).total_seconds()
            if 0 < dt < 30:  # sanity: ignore gaps > 30s as paused
                z = hr_zone_of(prev_hr)
                if z:
                    seconds_in_zone[z] += dt
        prev_ts = ts
        prev_hr = hr
    return seconds_in_zone


def parse_fit(fit_path: Path, lthr: int) -> dict | None:
    try:
        ff = FitFile(str(fit_path))
        ff.parse()
    except (FitParseError, Exception) as e:  # noqa: BLE001
        print(f"  ! could not decode {fit_path.name}: {type(e).__name__}: {e}")
        return None

    sessions: list[dict] = []
    laps: list[dict] = []
    samples: list[dict] = []

    for msg in ff.get_messages("session"):
        sessions.append(record_to_dict(msg))
    for msg in ff.get_messages("lap"):
        laps.append(record_to_dict(msg))
    for msg in ff.get_messages("record"):
        d = record_to_dict(msg)
        # keep only commonly useful fields to keep JSON readable
        keep = {k: d.get(k) for k in (
            "timestamp", "heart_rate", "distance", "speed", "enhanced_speed",
            "cadence", "power", "altitude", "enhanced_altitude",
        ) if k in d}
        samples.append(keep)

    # Re-parse timestamps from samples for zone math
    for s in samples:
        ts = s.get("timestamp")
        if isinstance(ts, str):
            try:
                s["timestamp"] = datetime.fromisoformat(ts)
            except Exception:
                pass

    zone_seconds = summarize_zones(samples)

    # Convert sample timestamps back to ISO for JSON
    for s in samples:
        ts = s.get("timestamp")
        if isinstance(ts, datetime):
            s["timestamp"] = ts.isoformat()

    primary = sessions[0] if sessions else {}
    summary = {
        "sport": primary.get("sport"),
        "sub_sport": primary.get("sub_sport"),
        "start_time": to_jsonable(primary.get("start_time")),
        "total_elapsed_time_s": primary.get("total_elapsed_time"),
        "total_timer_time_s": primary.get("total_timer_time"),
        "total_distance_m": primary.get("total_distance"),
        "avg_heart_rate": primary.get("avg_heart_rate"),
        "max_heart_rate": primary.get("max_heart_rate"),
        "total_calories": primary.get("total_calories"),
        "total_ascent": primary.get("total_ascent"),
        "total_descent": primary.get("total_descent"),
        "training_load_peak": primary.get("training_load_peak"),
    }

    return {
        "source_file": fit_path.name,
        "lthr_used": lthr,
        "summary": summary,
        "zone_seconds": zone_seconds,
        "lap_count": len(laps),
        "laps": laps,
        "sample_count": len(samples),
        "samples": samples,
    }


def main() -> int:
    args = parse_args()
    fit_path = Path(args.fit_path)
    if not fit_path.exists():
        sys.stderr.write(f"File not found: {fit_path}\n")
        return 1

    parsed = parse_fit(fit_path, args.lthr)
    if parsed is None:
        # Stop condition: log and skip, do not crash callers
        return 0

    out_path = Path(args.out) if args.out else fit_path.with_suffix(".json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(parsed, indent=2, default=str), encoding="utf-8")

    print(f"  ✓ parsed {fit_path.name}")
    print(f"  ✓ wrote  {out_path}")
    print(f"  summary: sport={parsed['summary'].get('sport')} "
          f"dur={parsed['summary'].get('total_elapsed_time_s')}s "
          f"dist={parsed['summary'].get('total_distance_m')}m "
          f"avg_hr={parsed['summary'].get('avg_heart_rate')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
