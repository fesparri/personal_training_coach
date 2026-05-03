"""
garmin_sync.py

Pulls wellness markers and activities from Garmin Connect and writes them to
the project data/ tree using a day-based layout:

    data/
    └── YYYY-MM-DD/
        ├── wellness.json
        ├── activities/
        │   ├── <activity_id>.json
        │   └── <activity_id>.fit
        └── notes.md           (created by the user, not by this script)

Idempotent: re-running on the same date overwrites the JSON cleanly without
duplicating activities. If a date has no wellness, the wellness.json is still
written (with whatever fields Garmin returned, possibly empty). If a date has
no activities, the activities/ folder is simply absent — no empty placeholder.

Usage:
    python scripts/garmin_sync.py                              # yesterday + today
    python scripts/garmin_sync.py --date 2026-04-28            # single date
    python scripts/garmin_sync.py --from 2026-04-15 --to 2026-04-30
    python scripts/garmin_sync.py --backfill 30                # last 30 days
    python scripts/garmin_sync.py --backfill 30 --no-fit       # skip raw .fit

Env (loaded from .env at project root):
    GARMIN_EMAIL
    GARMIN_PASSWORD

Auth model:
    This script does NOT perform a fresh SSO login. It loads OAuth tokens
    from ~/.garminconnect (created once by scripts/garmin_auth_bootstrap.py)
    and refreshes them automatically. Tokens are valid for ~1 year, so there
    is no SSO call on each run and no rate-limit risk.

    First-time setup (run once):
        python scripts/garmin_auth_bootstrap.py
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

try:
    from garminconnect import (
        Garmin,
        GarminConnectAuthenticationError,
        GarminConnectConnectionError,
        GarminConnectTooManyRequestsError,
    )
except ImportError:
    sys.stderr.write(
        "garminconnect is not installed. Run: pip install -r requirements.txt\n"
    )
    sys.exit(1)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
TOKENSTORE = Path.home() / ".garminconnect"


def get_garmin_client():
    """Returns an authenticated Garmin client using saved DI OAuth tokens.

    This function NEVER performs a fresh SSO login. It constructs the client
    WITHOUT credentials, so a missing/invalid token store surfaces as an
    authentication error (instead of silently triggering SSO).

    The bootstrap script (scripts/garmin_auth_bootstrap.py) is the only place
    in the project authorized to call SSO and create the token store.
    """
    # No email/password → if tokens fail to load, the lib raises
    # GarminConnectAuthenticationError instead of falling through to SSO.
    client = Garmin()

    try:
        # Loads tokens from ~/.garminconnect and proactively refreshes the DI
        # access_token via diauth.garmin.com when it's about to expire — no
        # SSO endpoint involvement.
        client.login(str(TOKENSTORE))
    except GarminConnectTooManyRequestsError as e:
        raise SystemExit(
            f"Garmin rate limit hit (429). Account is temporarily blocked. "
            f"Wait 1-24 hours before retrying. Do NOT delete ~/.garminconnect "
            f"unless you are certain the tokens are corrupt. Error: {e}"
        )
    except GarminConnectAuthenticationError as e:
        raise SystemExit(
            f"Token store at {TOKENSTORE} is missing or invalid. "
            f"Run `python scripts/garmin_auth_bootstrap.py` once to create "
            f"it (tokens last ~1 year and refresh automatically afterwards). "
            f"Error: {e}"
        )
    return client


def ensure_tokenstore_ready() -> None:
    """Bail out with a clear instruction if the token store is missing/empty.

    In garminconnect 0.3.3 the tokens live in ~/.garminconnect/garmin_tokens.json
    (older versions used oauth1_token.json + oauth2_token.json). We accept any
    non-empty contents — the lib decides what is valid.

    The first SSO login must go through scripts/garmin_auth_bootstrap.py.
    """
    msg = (
        "No Garmin token store found at ~/.garminconnect.\n"
        "Run `python scripts/garmin_auth_bootstrap.py` once before syncing. "
        "This creates the token store and avoids 429 errors.\n"
    )
    if not TOKENSTORE.exists():
        sys.stderr.write(msg)
        sys.exit(2)
    if TOKENSTORE.is_dir() and not any(TOKENSTORE.iterdir()):
        sys.stderr.write(msg)
        sys.exit(2)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Sync Garmin Connect data into a day-based data/ layout.",
    )
    p.add_argument("--date", type=str, default=None,
                   help="Single ISO date YYYY-MM-DD to sync.")
    p.add_argument("--from", dest="date_from", type=str, default=None,
                   help="Start ISO date YYYY-MM-DD (inclusive). Use with --to.")
    p.add_argument("--to", dest="date_to", type=str, default=None,
                   help="End ISO date YYYY-MM-DD (inclusive). Defaults to today.")
    p.add_argument("--backfill", type=int, default=None,
                   help="Sync the last N days from today (inclusive).")
    p.add_argument("--no-fit", action="store_true",
                   help="Skip downloading raw .fit files.")
    p.add_argument("--no-extended", action="store_true",
                   help="Skip downloading wellness_extended.json + athlete_metrics.json.")
    p.add_argument("--extended-recent-days", type=int, default=EXTENDED_RECENT_DAYS_DEFAULT,
                   help=f"Days back from end of range eligible for extended wellness "
                        f"(default {EXTENDED_RECENT_DAYS_DEFAULT}). Athlete metrics are "
                        f"snapshotted once at the end day regardless.")
    return p.parse_args()


def resolve_range(args: argparse.Namespace) -> tuple[date, date]:
    """Resolve CLI flags into an inclusive [start, end] date range.

    Precedence: --date > --from/--to > --backfill > default (yesterday + today).
    """
    today = date.today()

    if args.date:
        d = date.fromisoformat(args.date)
        return d, d

    if args.date_from:
        start = date.fromisoformat(args.date_from)
        end = date.fromisoformat(args.date_to) if args.date_to else today
        if end < start:
            sys.stderr.write("--to is before --from\n")
            sys.exit(2)
        return start, end

    if args.backfill is not None:
        if args.backfill <= 0:
            sys.stderr.write("--backfill must be a positive integer\n")
            sys.exit(2)
        return today - timedelta(days=args.backfill - 1), today

    # Default: yesterday + today.
    return today - timedelta(days=1), today


def date_range(start: date, end: date) -> list[date]:
    days = []
    cur = start
    while cur <= end:
        days.append(cur)
        cur += timedelta(days=1)
    return days


def safe_call(fn, *args, default=None, label: str = ""):
    """Call a Garmin client method, returning `default` on failure and logging."""
    try:
        return fn(*args)
    except Exception as e:  # noqa: BLE001 - the lib raises many distinct types
        print(f"  ! {label}: {type(e).__name__}: {e}")
        return default


def day_dir(day: date) -> Path:
    return DATA_DIR / day.isoformat()


def collect_wellness(client: Garmin, day: date) -> dict:
    iso = day.isoformat()
    sleep = safe_call(client.get_sleep_data, iso, default={}, label=f"sleep {iso}")
    hrv = safe_call(client.get_hrv_data, iso, default={}, label=f"hrv {iso}")
    rhr = safe_call(client.get_rhr_day, iso, default={}, label=f"rhr {iso}")
    body_battery = safe_call(client.get_body_battery, iso, iso, default=[], label=f"body_battery {iso}")
    stress = safe_call(client.get_stress_data, iso, default={}, label=f"stress {iso}")

    return {
        "date": iso,
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "sleep": sleep,
        "hrv": hrv,
        "resting_heart_rate": rhr,
        "body_battery": body_battery,
        "stress": stress,
    }


def wellness_has_signal(payload: dict) -> bool:
    """Best-effort check: did Garmin actually return any markers for this day?"""
    return any(payload.get(k) for k in ("sleep", "hrv", "resting_heart_rate", "body_battery", "stress"))


def write_wellness(day: date, payload: dict) -> Path:
    d = day_dir(day)
    d.mkdir(parents=True, exist_ok=True)
    out = d / "wellness.json"
    out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return out


# How many days back from the end of the sync range are eligible for the
# "extended" wellness payload (steps, training_readiness, max_metrics, etc.).
# Going further back doesn't add coaching value (state-of-the-day metrics for
# 90 days ago are mostly null) and risks Garmin rate-limiting on `--backfill`
# runs. Tunable via --extended-recent-days.
EXTENDED_RECENT_DAYS_DEFAULT = 7


def collect_wellness_extended(client: Garmin, day: date) -> dict:
    """Collect every per-day metric beyond the core wellness5 (sleep / hrv /
    rhr / body_battery / stress) that python-garminconnect 0.3.3 exposes.

    Each field is best-effort: if Garmin doesn't have the data for this day
    (e.g. you didn't wear the watch, or the metric didn't exist on your
    device firmware), the value is null/empty and the sync still succeeds.
    """
    iso = day.isoformat()

    return {
        "date": iso,
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),

        # Daily summaries (overlap with wellness.json on purpose — these are
        # the canonical Garmin objects, useful as raw source of truth).
        "user_summary": safe_call(client.get_user_summary, iso, default={}, label=f"user_summary {iso}"),
        "stats": safe_call(client.get_stats, iso, default={}, label=f"stats {iso}"),

        # Heart / breathing / oxygen
        "heart_rates": safe_call(client.get_heart_rates, iso, default={}, label=f"heart_rates {iso}"),
        "respiration": safe_call(client.get_respiration_data, iso, default={}, label=f"respiration {iso}"),
        "spo2": safe_call(client.get_spo2_data, iso, default={}, label=f"spo2 {iso}"),

        # Activity / movement
        "intensity_minutes": safe_call(client.get_intensity_minutes_data, iso, default={}, label=f"intensity_min {iso}"),
        "steps": safe_call(client.get_steps_data, iso, default=[], label=f"steps {iso}"),
        "floors": safe_call(client.get_floors, iso, default={}, label=f"floors {iso}"),

        # Body / hydration
        "hydration": safe_call(client.get_hydration_data, iso, default={}, label=f"hydration {iso}"),
        "weigh_in": safe_call(client.get_daily_weigh_ins, iso, default={}, label=f"weigh_in {iso}"),

        # All-day signals
        "all_day_stress": safe_call(client.get_all_day_stress, iso, default={}, label=f"all_day_stress {iso}"),
        "body_battery_events": safe_call(client.get_body_battery_events, iso, default=[], label=f"bb_events {iso}"),
        "all_day_events": safe_call(client.get_all_day_events, iso, default={}, label=f"all_day_events {iso}"),

        # Training-state (the Garmin "FirstBeat" stack — VO2max, training
        # status/readiness, fitness age — the values the coach uses to
        # build a longitudinal profile of the athlete).
        "max_metrics": safe_call(client.get_max_metrics, iso, default={}, label=f"max_metrics {iso}"),
        "training_status": safe_call(client.get_training_status, iso, default={}, label=f"training_status {iso}"),
        "training_readiness": safe_call(client.get_training_readiness, iso, default={}, label=f"training_readiness {iso}"),
        "morning_training_readiness": safe_call(client.get_morning_training_readiness, iso, default={}, label=f"morning_readiness {iso}"),
        "fitness_age": safe_call(client.get_fitnessage_data, iso, default={}, label=f"fitness_age {iso}"),
    }


def write_wellness_extended(day: date, payload: dict) -> Path:
    d = day_dir(day)
    d.mkdir(parents=True, exist_ok=True)
    out = d / "wellness_extended.json"
    out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return out


def collect_athlete_metrics(client: Garmin, anchor_day: date) -> dict:
    """Snapshot of the athlete's longitudinal performance profile.

    These metrics evolve over weeks/months (FTP, lactate threshold, race
    predictions, body composition trends). We snapshot them once per sync
    and store them under the anchor day, so the dashboard / coach can
    iterate `data/<fecha>/athlete_metrics.json` to plot evolution over
    time.
    """
    iso = anchor_day.isoformat()

    # For range-based queries we use a reasonable window ending at anchor.
    rng_start_30d = (anchor_day - timedelta(days=30)).isoformat()
    rng_start_7d = (anchor_day - timedelta(days=7)).isoformat()

    return {
        "date": iso,
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),

        # Performance / threshold
        "lactate_threshold": safe_call(client.get_lactate_threshold, default={}, label="lactate_threshold"),
        "cycling_ftp": safe_call(client.get_cycling_ftp, default={}, label="cycling_ftp"),
        "personal_records": safe_call(client.get_personal_record, default=[], label="personal_records"),

        # Predictions / scores (per-day from Garmin, but slow-moving).
        # get_race_predictions wants either ALL three params (start, end,
        # type) or NONE — calling with no args returns the latest values.
        "race_predictions": safe_call(client.get_race_predictions, default={}, label="race_predictions"),
        "endurance_score": safe_call(client.get_endurance_score, rng_start_30d, iso, default={}, label="endurance_score"),
        "hill_score": safe_call(client.get_hill_score, rng_start_30d, iso, default={}, label="hill_score"),
        "running_tolerance": safe_call(client.get_running_tolerance, rng_start_30d, iso, "weekly", default=[], label="running_tolerance"),

        # Body
        "body_composition": safe_call(client.get_body_composition, rng_start_7d, iso, default={}, label="body_composition"),
        "weigh_ins_recent": safe_call(client.get_weigh_ins, rng_start_7d, iso, default={}, label="weigh_ins"),

        # Identity / config (lightweight, useful for the coach's profile context)
        "user_profile": safe_call(client.get_user_profile, default={}, label="user_profile"),
        "devices": safe_call(client.get_devices, default=[], label="devices"),
        "unit_system": safe_call(client.get_unit_system, default=None, label="unit_system"),
        "full_name": safe_call(client.get_full_name, default=None, label="full_name"),
    }


def write_athlete_metrics(day: date, payload: dict) -> Path:
    d = day_dir(day)
    d.mkdir(parents=True, exist_ok=True)
    out = d / "athlete_metrics.json"
    out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return out


def athlete_metrics_has_signal(payload: dict) -> bool:
    """Best-effort check: did Garmin return any non-empty performance metric?"""
    for k in ("lactate_threshold", "cycling_ftp", "personal_records",
              "race_predictions", "endurance_score", "hill_score",
              "running_tolerance", "body_composition"):
        v = payload.get(k)
        if v and (not isinstance(v, dict) or any(v.values())):
            return True
    return False


def collect_activities(client: Garmin, start: date, end: date) -> list[dict]:
    activities = safe_call(
        client.get_activities_by_date,
        start.isoformat(),
        end.isoformat(),
        default=[],
        label=f"activities {start}..{end}",
    )
    return activities or []


def activity_day(activity: dict) -> date | None:
    start_local = (
        activity.get("startTimeLocal")
        or activity.get("startTimeGMT")
        or ""
    )
    try:
        return datetime.fromisoformat(start_local.replace("Z", "")).date()
    except Exception:
        return None


def write_activity(activity: dict) -> Path | None:
    activity_id = activity.get("activityId") or activity.get("activity_id")
    if activity_id is None:
        return None
    day = activity_day(activity)
    if day is None:
        return None
    activities_dir = day_dir(day) / "activities"
    activities_dir.mkdir(parents=True, exist_ok=True)
    out = activities_dir / f"{activity_id}.json"
    out.write_text(json.dumps(activity, indent=2, default=str), encoding="utf-8")
    return out


def write_fit(client: Garmin, activity: dict) -> Path | None:
    """Download activity and persist the raw .fit at the day's path.

    Garmin's `ORIGINAL` download format returns a ZIP containing the .fit
    file. We detect the ZIP magic bytes (PK\\x03\\x04) and extract the first
    .fit member so the on-disk file is directly usable by fitparse.
    """
    activity_id = activity.get("activityId") or activity.get("activity_id")
    if activity_id is None:
        return None
    day = activity_day(activity)
    if day is None:
        return None
    activities_dir = day_dir(day) / "activities"
    activities_dir.mkdir(parents=True, exist_ok=True)
    out = activities_dir / f"{activity_id}.fit"
    try:
        from garminconnect import Garmin as _G  # local import to access enum
        dl = None
        if hasattr(_G, "ActivityDownloadFormat"):
            dl = client.download_activity(
                activity_id, dl_fmt=_G.ActivityDownloadFormat.ORIGINAL
            )
        else:
            dl = client.download_activity(activity_id)
        if dl is None:
            return None

        # Garmin "ORIGINAL" wraps the .fit inside a ZIP — unwrap it.
        if dl[:4] == b"PK\x03\x04":
            import io, zipfile
            with zipfile.ZipFile(io.BytesIO(dl)) as zf:
                fit_members = [n for n in zf.namelist() if n.lower().endswith(".fit")]
                if not fit_members:
                    print(f"  ! fit zip for {activity_id} has no .fit member")
                    return None
                with zf.open(fit_members[0]) as src:
                    out.write_bytes(src.read())
        else:
            out.write_bytes(dl)
        return out
    except Exception as e:  # noqa: BLE001
        print(f"  ! fit download {activity_id}: {type(e).__name__}: {e}")
        return None


# -----------------------------------------------------------------------------
# Auto-update profile.yml from latest Garmin measurements
# -----------------------------------------------------------------------------
# Garmin's algorithms (FirstBeat) measure LTHR, FTP, etc. continuously and
# tend to be more accurate than a value the athlete sets once. After every
# sync that returns athlete_metrics, we refresh the physio block of
# profile.yml from the latest measurements. The user keeps ownership of the
# editorial fields: coach_profile, athlete.name, initial_body_state.

PROFILE_YML = PROJECT_ROOT / "profile.yml"


def _safe_get(d, *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur if cur not in (None, "", {}, []) else default


def _baseline_avg_recent(metric_filename: str, dot_path: str, days: int = 14) -> float | None:
    """Average of a metric across the last `days` data/<date>/ folders."""
    if not DATA_DIR.exists():
        return None
    keys = dot_path.split(".")
    values: list[float] = []
    cutoff_count = 0
    for child in sorted(DATA_DIR.iterdir(), reverse=True):
        if cutoff_count >= days:
            break
        if not child.is_dir():
            continue
        try:
            date.fromisoformat(child.name)
        except ValueError:
            continue
        cutoff_count += 1
        p = child / metric_filename
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        cur = data
        for k in keys:
            if not isinstance(cur, dict) or k not in cur:
                cur = None
                break
            cur = cur[k]
        if isinstance(cur, (int, float)):
            values.append(float(cur))
    return (sum(values) / len(values)) if values else None


def update_profile_from_garmin(athlete_metrics: dict, anchor_day: date) -> list[str]:
    """Refresh `physio.*` and `athlete.weight_kg`/`height_cm` of profile.yml
    from the latest Garmin measurements.

    Preserves editorial fields (coach_profile, athlete.name,
    initial_body_state, devices). Returns a list of human-readable change
    descriptions.

    Strategy: full rewrite of profile.yml with a stable schema. Comments
    in profile.yml are not preserved (the schema docs live in
    profile.example.yml).
    """
    if not PROFILE_YML.exists():
        return ["(profile.yml does not exist; skipping auto-update)"]

    try:
        import yaml
    except ImportError:
        return ["(pyyaml not installed; skipping auto-update)"]

    current = yaml.safe_load(PROFILE_YML.read_text(encoding="utf-8")) or {}
    changes: list[str] = []

    # Helper: set a value if it differs from current; record the change
    def set_field(holder: dict, key: str, new_val, label: str, fmt=str):
        old_val = holder.get(key)
        if new_val is None or new_val == old_val:
            return
        # Round floats to keep the file tidy
        if isinstance(new_val, float):
            new_val = round(new_val, 2)
        holder[key] = new_val
        old_str = "—" if old_val in (None, "") else fmt(old_val)
        new_str = fmt(new_val)
        changes.append(f"  {label}: {old_str} → {new_str}")

    physio = current.setdefault("physio", {})
    athlete = current.setdefault("athlete", {})

    # --- LTHR (running) — comes from lactate_threshold.speed_and_heart_rate.heartRate ---
    lthr_garmin = _safe_get(athlete_metrics, "lactate_threshold", "speed_and_heart_rate", "heartRate")
    if lthr_garmin:
        set_field(physio, "lthr_bpm", int(round(lthr_garmin)), "physio.lthr_bpm")

    # --- Cycling FTP ---
    cycling_ftp = _safe_get(athlete_metrics, "cycling_ftp", "functionalThresholdPower")
    if cycling_ftp:
        set_field(physio, "cycling_ftp_w", int(round(cycling_ftp)), "physio.cycling_ftp_w")

    # --- Running FTP (from lactate_threshold.power) ---
    run_ftp = _safe_get(athlete_metrics, "lactate_threshold", "power", "functionalThresholdPower")
    if run_ftp:
        set_field(physio, "running_ftp_w", int(round(run_ftp)), "physio.running_ftp_w")
    p2w = _safe_get(athlete_metrics, "lactate_threshold", "power", "powerToWeight")
    if p2w:
        set_field(physio, "running_power_to_weight", round(float(p2w), 2), "physio.running_power_to_weight")

    # --- Weight from latest body composition / weigh-in ---
    weight = _safe_get(athlete_metrics, "lactate_threshold", "power", "weight")
    if weight:
        set_field(athlete, "weight_kg", round(float(weight), 1), "athlete.weight_kg")

    # --- Resting HR baseline (avg of last 14 days from wellness.json) ---
    rhr_baseline = _baseline_avg_recent(
        "wellness.json",
        "resting_heart_rate.allMetrics.metricsMap.WELLNESS_RESTING_HEART_RATE.0.value",
        days=14,
    )
    # The dot path with .0. doesn't work — re-implement for this specific case
    rhr_values: list[float] = []
    if DATA_DIR.exists():
        cnt = 0
        for child in sorted(DATA_DIR.iterdir(), reverse=True):
            if cnt >= 14:
                break
            if not child.is_dir():
                continue
            try:
                date.fromisoformat(child.name)
            except ValueError:
                continue
            cnt += 1
            p = child / "wellness.json"
            if not p.exists():
                continue
            try:
                w = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            block = (((w.get("resting_heart_rate") or {}).get("allMetrics") or {}).get("metricsMap") or {}).get("WELLNESS_RESTING_HEART_RATE") or []
            if block and isinstance(block, list) and isinstance(block[0], dict):
                v = block[0].get("value")
                if isinstance(v, (int, float)) and v > 0:
                    rhr_values.append(float(v))
    if rhr_values:
        rhr_avg = round(sum(rhr_values) / len(rhr_values))
        set_field(physio, "resting_hr_typical_bpm", rhr_avg, "physio.resting_hr_typical_bpm")

    # --- HRV baseline (avg of last 14 days lastNightAvg) ---
    hrv_baseline = _baseline_avg_recent(
        "wellness.json", "hrv.hrvSummary.lastNightAvg", days=14,
    )
    if hrv_baseline:
        set_field(physio, "hrv_baseline_ms", int(round(hrv_baseline)), "physio.hrv_baseline_ms")

    # --- Body composition fields (BMI, etc.) ---
    bmi = _safe_get(athlete_metrics, "weigh_ins_recent", "totalAverage", "bmi")
    if bmi:
        set_field(physio, "bmi", round(float(bmi), 1), "physio.bmi")

    # --- Audit log of changes (append-only, capped at 200 entries) ---
    # Each entry: {date, field, from, to}. Lets the user review evolution
    # of LTHR / FTP / weight without opening 30 athlete_metrics.json files.
    meta = current.setdefault("_meta", {})
    history: list[dict] = list(meta.get("history") or [])
    iso_now = anchor_day.isoformat()
    for change_line in changes:
        # `  field: from → to` → parse back to structured entry
        try:
            after_indent = change_line.lstrip()
            field, _, rest = after_indent.partition(":")
            from_str, _, to_str = rest.strip().partition(" → ")
            history.append({
                "date": iso_now,
                "field": field.strip(),
                "from": from_str.strip(),
                "to": to_str.strip(),
            })
        except Exception:
            continue
    # Cap to last 200 to keep the file manageable
    if len(history) > 200:
        history = history[-200:]
    meta["history"] = history
    meta["last_garmin_refresh"] = iso_now
    meta["refreshed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta["source"] = "scripts/garmin_sync.py"

    # Write back. PyYAML default_flow_style=False produces clean block-style YAML.
    # We don't preserve comments — the schema docs live in profile.example.yml.
    PROFILE_YML.write_text(
        yaml.safe_dump(current, default_flow_style=False, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return changes


def main() -> int:
    args = parse_args()
    start, end = resolve_range(args)

    print(f"Garmin sync: {start} -> {end}  "
          f"(download_fit={'no' if args.no_fit else 'yes'}, "
          f"extended={'no' if args.no_extended else f'last {args.extended_recent_days}d'})")
    ensure_tokenstore_ready()
    client = get_garmin_client()

    days = date_range(start, end)
    days_with_wellness: list[date] = []
    days_skipped_no_data: list[date] = []
    days_with_extended: list[date] = []
    activities_written = 0
    fits_written = 0

    print("\n[wellness — core]")
    for day in days:
        payload = collect_wellness(client, day)
        path = write_wellness(day, payload)
        if wellness_has_signal(payload):
            days_with_wellness.append(day)
            print(f"  ✓ {path.relative_to(PROJECT_ROOT)}")
        else:
            days_skipped_no_data.append(day)
            print(f"  · {path.relative_to(PROJECT_ROOT)}  (no wellness signal returned)")

    if not args.no_extended:
        # Days eligible for extended wellness: those within the recent window
        # of the end date (limits API calls on large backfills).
        cutoff = end - timedelta(days=args.extended_recent_days - 1)
        recent_days = [d for d in days if d >= cutoff]
        print(f"\n[wellness — extended] ({len(recent_days)} day(s) eligible)")
        for day in recent_days:
            payload = collect_wellness_extended(client, day)
            path = write_wellness_extended(day, payload)
            days_with_extended.append(day)
            print(f"  ✓ {path.relative_to(PROJECT_ROOT)}")

    print("\n[activities]")
    activities = collect_activities(client, start, end)
    print(f"  found {len(activities)} activity record(s) in range")

    for activity in activities:
        path = write_activity(activity)
        if path is not None:
            activities_written += 1
            print(f"  ✓ {path.relative_to(PROJECT_ROOT)}")
            if not args.no_fit:
                fit_path = write_fit(client, activity)
                if fit_path:
                    fits_written += 1
                    print(f"  ✓ {fit_path.relative_to(PROJECT_ROOT)}")

    athlete_metrics_path: Path | None = None
    profile_changes: list[str] = []
    if not args.no_extended:
        print("\n[athlete metrics — longitudinal snapshot]")
        am_payload = collect_athlete_metrics(client, end)
        athlete_metrics_path = write_athlete_metrics(end, am_payload)
        signal = "✓" if athlete_metrics_has_signal(am_payload) else "·"
        print(f"  {signal} {athlete_metrics_path.relative_to(PROJECT_ROOT)}"
              f"{'' if signal == '✓' else '  (Garmin returned no longitudinal metrics)'}")

        # Refresh profile.yml from the just-collected athlete metrics.
        # Garmin algorithms are typically more accurate than a hand-set
        # value; the user keeps ownership of editorial fields.
        if signal == "✓":
            print("\n[profile.yml — auto-refresh from Garmin]")
            profile_changes = update_profile_from_garmin(am_payload, end)
            if profile_changes:
                for line in profile_changes:
                    print(line)
            else:
                print("  · no changes (profile.yml already in sync with Garmin)")

    print("\n[summary]")
    print(f"  dates synced:           {len(days)}  ({start} → {end})")
    print(f"  days with wellness:     {len(days_with_wellness)}")
    print(f"  days w/o wellness:      {len(days_skipped_no_data)}")
    if days_skipped_no_data:
        print("    " + ", ".join(d.isoformat() for d in days_skipped_no_data))
    if not args.no_extended:
        print(f"  days with extended:     {len(days_with_extended)}")
        if athlete_metrics_path:
            print(f"  athlete metrics:        {athlete_metrics_path.relative_to(PROJECT_ROOT)}")
    print(f"  activities downloaded:  {activities_written}")
    if not args.no_fit:
        print(f"  .fit files downloaded:  {fits_written}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
