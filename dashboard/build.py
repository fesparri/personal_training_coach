"""dashboard/build.py — generador del dashboard local.

Pipeline:
    1. Leer perfil activo (profiles/<name>/profile.yml + system_prompt.md).
    2. Iterar `data/YYYY-MM-DD/` y construir trends de wellness.
    3. Iterar `data/YYYY-MM-DD/activities/` y agrupar por ISO-week +
       computar ACWR y zonas Z1-Z5 últimos 7d.
    4. Leer `executed_volume.md` para RPE y bitácora corporal.
    5. Aplicar umbrales del perfil → generar lista de alertas.
    6. Renderizar `dashboard/template.html` con la data inline.
    7. Escribir `dashboard.html` en el root del proyecto.

Output: un solo archivo HTML autocontenido (Chart.js inline + data inline +
CSS + JS) que abre con doble click en cualquier browser sin servidor.
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DASHBOARD_DIR = Path(__file__).resolve().parent
TEMPLATE_PATH = DASHBOARD_DIR / "template.html"
CHARTJS_PATH = DASHBOARD_DIR / "vendor" / "chart.umd.min.js"
OUTPUT_PATH = PROJECT_ROOT / "dashboard.html"

# Reuse helpers from scripts/_session_lib (single source of truth for
# wellness parsing, fit zones, bitacora, etc.)
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from _session_lib import (  # noqa: E402
    LTHR,
    ZONE_BOUNDS,
    current_open_body_issues,
    find_master_plan_target,
    latest_athlete_metrics,
    load_athlete_metrics,
    load_wellness,
    load_wellness_extended,
    metric_history,
    parse_fit_zones,
    read_bitacora_rows,
    wellness_summary_fields,
)

# Profile loader
sys.path.insert(0, str(PROJECT_ROOT))
from profiles.registry import load_active_profile  # noqa: E402


# -----------------------------------------------------------------------------
# Iteration helpers
# -----------------------------------------------------------------------------

def _iter_day_dirs() -> list[date]:
    """Return all data/YYYY-MM-DD/ directories as sorted list of dates."""
    if not DATA_DIR.exists():
        return []
    out: list[date] = []
    for child in sorted(DATA_DIR.iterdir()):
        if not child.is_dir():
            continue
        try:
            out.append(date.fromisoformat(child.name))
        except ValueError:
            continue
    return out


def _activities_of(day: date) -> list[Path]:
    adir = DATA_DIR / day.isoformat() / "activities"
    if not adir.exists():
        return []
    # Skip the *_parsed.json sidecar files
    return sorted(p for p in adir.glob("*.json") if not p.stem.endswith("_parsed"))


# -----------------------------------------------------------------------------
# Wellness trends
# -----------------------------------------------------------------------------

def _safe_get(d, *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur if cur not in (None, "", {}, []) else default


def _collect_wellness_trends(days: list[date]) -> dict:
    """Return {metric: [[YYYY-MM-DD, value], ...]} for each tracked metric."""
    keys = [
        "sleep_score", "sleep_duration_h", "hrv_avg", "hrv_max",
        "rhr", "body_battery_low", "body_battery_high",
        "stress_avg", "stress_max",
    ]
    series: dict[str, list[list]] = {k: [] for k in keys}

    for d in days:
        f = wellness_summary_fields(d)
        # sleep_dur returned as "Hh MMm"; convert to hours float
        dur_h = None
        s = f.get("sleep_dur") or "—"
        if s and s != "—":
            try:
                # format "7h35m" or "0h45m"
                h_part, m_part = s.split("h")
                m_part = m_part.rstrip("m")
                dur_h = round(int(h_part) + int(m_part) / 60.0, 2)
            except Exception:
                dur_h = None

        per_day = {
            "sleep_score": f.get("sleep_score"),
            "sleep_duration_h": dur_h,
            "hrv_avg": f.get("hrv_avg"),
            "hrv_max": f.get("hrv_max"),
            "rhr": f.get("rhr"),
            "body_battery_low": f.get("bb_low"),
            "body_battery_high": f.get("bb_high"),
            "stress_avg": f.get("stress_avg"),
            "stress_max": f.get("stress_max"),
        }
        iso = d.isoformat()
        for k, v in per_day.items():
            if v is not None:
                series[k].append([iso, v])

    return series


# -----------------------------------------------------------------------------
# Extended trends (training_readiness, respiration, spo2) from wellness_extended.json
# -----------------------------------------------------------------------------

def _collect_extended_trends(days: list[date]) -> dict:
    """Series for metrics that live in wellness_extended.json.

    Each series is [[date_iso, value], ...]. Skips days where the file or
    field is missing.
    """
    series: dict[str, list[list]] = {
        "training_readiness": [],
        "recovery_time_min": [],
        "respiration_avg": [],
        "spo2_avg": [],
        "intensity_minutes_total": [],
        "steps_total": [],
        "floors": [],
    }
    for d in days:
        we = load_wellness_extended(d)
        if not we:
            continue
        iso = d.isoformat()

        # training_readiness comes as a list (the device may emit several
        # readings per day) — take the latest non-null score
        tr = we.get("training_readiness") or []
        if isinstance(tr, list) and tr:
            latest = tr[-1] if isinstance(tr[-1], dict) else None
            if latest:
                if (sc := latest.get("score")) is not None:
                    series["training_readiness"].append([iso, sc])
                if (rt := latest.get("recoveryTime")) is not None:
                    series["recovery_time_min"].append([iso, rt])

        # respiration: avgWakingRespirationValue, avgSleepRespirationValue, etc.
        resp = we.get("respiration") or {}
        if isinstance(resp, dict):
            v = (resp.get("avgWakingRespirationValue")
                 or resp.get("avgSleepRespirationValue"))
            if v:
                series["respiration_avg"].append([iso, v])

        # spo2
        spo2 = we.get("spo2") or {}
        if isinstance(spo2, dict):
            v = spo2.get("averageSpO2")
            if v:
                series["spo2_avg"].append([iso, v])

        # intensity minutes total = moderate + 2*vigorous (Garmin standard)
        im = we.get("intensity_minutes") or {}
        if isinstance(im, dict):
            mod = im.get("moderateMinutes") or 0
            vig = im.get("vigorousMinutes") or 0
            total = mod + 2 * vig
            if total:
                series["intensity_minutes_total"].append([iso, total])

        # steps: Garmin returns either {"totalSteps": N} or a list of
        # 15min buckets — sum bucket steps if list
        steps_raw = we.get("steps")
        steps_total = None
        us = we.get("user_summary") or {}
        if isinstance(us, dict) and us.get("totalSteps"):
            steps_total = us["totalSteps"]
        elif isinstance(steps_raw, list):
            steps_total = sum(b.get("steps", 0) for b in steps_raw if isinstance(b, dict))
        if steps_total:
            series["steps_total"].append([iso, steps_total])

        # floors climbed
        fl = we.get("floors") or {}
        if isinstance(fl, dict):
            v = fl.get("floorsAscended") or fl.get("floorsClimbed")
            if v:
                series["floors"].append([iso, v])

    return series


# -----------------------------------------------------------------------------
# Athlete profile snapshot + longitudinal evolution
# -----------------------------------------------------------------------------

def _collect_athlete_profile_snapshot() -> dict:
    """Read the most recent athlete_metrics.json + wellness_extended.json
    and assemble a clean dict for the dashboard's "Athlete profile" panel.
    """
    result = latest_athlete_metrics()
    if not result:
        return {}
    snap_date, am = result

    # Fitness age + VO2max live in wellness_extended.json
    we = load_wellness_extended(snap_date) or {}
    fa = we.get("fitness_age") or {}
    ts = we.get("training_status") or {}

    # VO2max can be in two places (Garmin returns it inconsistently per
    # firmware). Try several paths.
    vo2 = (_safe_get(ts, "mostRecentVO2Max", "generic", "vo2MaxPreciseValue")
           or _safe_get(ts, "mostRecentVO2Max", "generic", "vo2MaxValue")
           or _safe_get(we, "max_metrics", 0, "generic", "vo2MaxPreciseValue"))

    rp = am.get("race_predictions") or {}
    lt = am.get("lactate_threshold") or {}
    lt_sahr = lt.get("speed_and_heart_rate") or {}
    lt_pwr = lt.get("power") or {}

    bc = am.get("body_composition") or {}
    bc_total = (bc.get("totalAverage") or {}) if isinstance(bc, dict) else {}
    weighins = (am.get("weigh_ins_recent") or {}).get("totalAverage") or {}

    return {
        "snapshot_date": snap_date.isoformat(),
        "fitness_age": {
            "chronological": fa.get("chronologicalAge"),
            "fitness": fa.get("fitnessAge"),
            "achievable": fa.get("achievableFitnessAge"),
            "previous": fa.get("previousFitnessAge"),
        } if fa else None,
        "vo2_max": vo2,
        "training_status_phrase": _safe_get(ts, "mostRecentTrainingStatus", "latestTrainingStatusData"),
        "lactate_threshold": {
            "running_hr_bpm": lt_sahr.get("heartRate"),
            "running_speed_ms": lt_sahr.get("speed"),
            "running_ftp_w": lt_pwr.get("functionalThresholdPower"),
            "running_pwr_to_weight": lt_pwr.get("powerToWeight"),
            "weight_kg_at_test": lt_pwr.get("weight"),
        } if lt else None,
        "cycling_ftp": {
            "watts": _safe_get(am, "cycling_ftp", "functionalThresholdPower"),
            "calendar_date": _safe_get(am, "cycling_ftp", "calendarDate"),
            "stale": _safe_get(am, "cycling_ftp", "isStale"),
        },
        "race_predictions": {
            "5k_s": rp.get("time5K"),
            "10k_s": rp.get("time10K"),
            "hm_s": rp.get("timeHalfMarathon"),
            "marathon_s": rp.get("timeMarathon"),
            "calendar_date": rp.get("calendarDate"),
        } if rp else None,
        "endurance_score": _safe_get(am, "endurance_score", "overallScore"),
        "hill_score": _safe_get(am, "hill_score", "overallScore"),
        "body_composition": {
            "weight_kg": bc_total.get("weight") or weighins.get("weight"),
            "bmi": bc_total.get("bmi") or weighins.get("bmi"),
            "body_fat_pct": bc_total.get("bodyFat"),
            "body_water_pct": bc_total.get("bodyWater"),
            "muscle_mass_kg": bc_total.get("muscleMass"),
        },
        "devices": [
            {
                "name": d.get("displayName") or d.get("productDisplayName"),
                "model": d.get("productNickname"),
            }
            for d in (am.get("devices") or [])
            if isinstance(d, dict)
        ],
    }


# -----------------------------------------------------------------------------
# Planned sessions (master_plan.md) and recent volume summary
# -----------------------------------------------------------------------------

# A row in master_plan.md looks like:
#   | Mar | 2026-04-28 | Hybrid Engine — sesión llave | 5 rondas: ... |
_MP_ROW_RE = re.compile(
    r"^\|\s*(?P<dia>[^|]+?)\s*\|\s*(?P<fecha>\d{4}-\d{2}-\d{2})\s*\|\s*"
    r"(?P<titulo>[^|]+?)\s*\|\s*(?P<detalle>[^|]+?)\s*\|\s*$",
    re.MULTILINE,
)


def _parse_master_plan_row(target: date) -> dict | None:
    """Return {dia, fecha, titulo, detalle} for `target` if master_plan.md
    has a matching row, else None.
    """
    raw = find_master_plan_target(target)
    if not raw:
        return None
    m = _MP_ROW_RE.match(raw)
    if not m:
        # Fallback: best-effort split by `|` so we still surface SOMETHING
        parts = [p.strip() for p in raw.strip("|").split("|")]
        if len(parts) >= 4:
            return {
                "dia": parts[0], "fecha": parts[1],
                "titulo": parts[2], "detalle": parts[3],
            }
        return None
    return {
        "dia": m.group("dia").strip(),
        "fecha": m.group("fecha").strip(),
        "titulo": m.group("titulo").strip(),
        "detalle": m.group("detalle").strip(),
    }


def _collect_planned_sessions(anchor_day: date, days_ahead: int = 7) -> dict:
    """Returns {today, tomorrow, next_7_days[]} planned-session info from
    master_plan.md."""
    today_row = _parse_master_plan_row(anchor_day)
    tomorrow_row = _parse_master_plan_row(anchor_day + timedelta(days=1))
    next_rows: list[dict] = []
    for i in range(days_ahead):
        d = anchor_day + timedelta(days=i)
        row = _parse_master_plan_row(d)
        if row:
            next_rows.append(row)
    return {
        "today": today_row,
        "tomorrow": tomorrow_row,
        "next_7_days": next_rows,
    }


def _collect_recent_volume_summary(days: list[date]) -> dict:
    """Compute volume rollups for the last 7d, last 14d, and the previous
    7d (for week-over-week comparison). Useful to surface "did I train
    enough this week?" at a glance.
    """
    if not days:
        return {}
    last = days[-1]

    def window(start: date, end: date) -> dict:
        sessions = 0
        time_s = 0.0
        distance_m = 0.0
        per_modality: dict[str, dict] = {}
        for d in days:
            if not (start <= d <= end):
                continue
            for ap in _activities_of(d):
                try:
                    a = json.loads(ap.read_text(encoding="utf-8"))
                except Exception:
                    continue
                mod = _modality_of(a)
                dur = float(a.get("duration") or 0)
                dist = float(a.get("distance") or 0)
                sessions += 1
                time_s += dur
                distance_m += dist
                pm = per_modality.setdefault(mod, {"sessions": 0, "time_s": 0.0, "distance_m": 0.0})
                pm["sessions"] += 1
                pm["time_s"] += dur
                pm["distance_m"] += dist
        return {
            "sessions": sessions,
            "time_s": int(time_s),
            "distance_m": int(distance_m),
            "per_modality": {
                m: {"sessions": v["sessions"], "time_s": int(v["time_s"]),
                    "distance_m": int(v["distance_m"])}
                for m, v in per_modality.items()
            },
        }

    win_7d = window(last - timedelta(days=6), last)
    win_14d = window(last - timedelta(days=13), last)
    win_prev_7d = window(last - timedelta(days=13), last - timedelta(days=7))

    # Week-over-week deltas (vs previous 7d)
    def pct_change(a, b):
        if not b:
            return None
        return round((a - b) / b * 100, 1)

    return {
        "last_7d": win_7d,
        "last_14d": win_14d,
        "prev_7d": win_prev_7d,
        "wow_deltas": {
            "sessions": pct_change(win_7d["sessions"], win_prev_7d["sessions"]),
            "time_s": pct_change(win_7d["time_s"], win_prev_7d["time_s"]),
            "distance_m": pct_change(win_7d["distance_m"], win_prev_7d["distance_m"]),
        },
    }


def _collect_athlete_evolution() -> dict:
    """Longitudinal series for the dashboard's "Athlete evolution" panel.

    Each series uses metric_history() from _session_lib, which iterates
    every data/<date>/<file>.json and extracts a dot-path. As more days
    accumulate, the series grow naturally.
    """
    return {
        "fitness_age": metric_history("wellness_extended.json", "fitness_age.fitnessAge"),
        "vo2max": metric_history(
            "wellness_extended.json",
            "training_status.mostRecentVO2Max.generic.vo2MaxPreciseValue",
        ),
        "cycling_ftp_w": metric_history("athlete_metrics.json", "cycling_ftp.functionalThresholdPower"),
        "running_ftp_w": metric_history("athlete_metrics.json", "lactate_threshold.power.functionalThresholdPower"),
        "running_lthr_bpm": metric_history("athlete_metrics.json", "lactate_threshold.speed_and_heart_rate.heartRate"),
        "race_5k_s": metric_history("athlete_metrics.json", "race_predictions.time5K"),
        "race_10k_s": metric_history("athlete_metrics.json", "race_predictions.time10K"),
        "race_hm_s": metric_history("athlete_metrics.json", "race_predictions.timeHalfMarathon"),
        "race_marathon_s": metric_history("athlete_metrics.json", "race_predictions.timeMarathon"),
        "endurance_score": metric_history("athlete_metrics.json", "endurance_score.overallScore"),
        "hill_score": metric_history("athlete_metrics.json", "hill_score.overallScore"),
        "weight_kg": metric_history("athlete_metrics.json", "lactate_threshold.power.weight"),
    }


# -----------------------------------------------------------------------------
# Activities + weekly volume + ACWR + HR zones
# -----------------------------------------------------------------------------

MODALITIES = [
    "running", "treadmill_running", "indoor_rowing", "indoor_cardio",
    "strength_training", "hiit", "obstacle_run", "lap_swimming", "walking",
    "cycling", "road_biking", "other",
]


def _modality_of(activity: dict) -> str:
    at = activity.get("activityType") or {}
    key = (at.get("typeKey") or "other").lower() if isinstance(at, dict) else "other"
    return key if key in MODALITIES else "other"


def _collect_weekly_volume(days: list[date]) -> list[dict]:
    """Group activities by ISO-week → {modality: {sessions, time_s, distance_m, avg_hr}}."""
    week_buckets: dict[str, dict] = defaultdict(lambda: defaultdict(lambda: {
        "sessions": 0, "time_s": 0.0, "distance_m": 0.0,
        "_hr_num": 0.0, "_hr_den": 0.0,
    }))
    week_meta: dict[str, dict] = {}

    for d in days:
        iso_year, iso_week, _ = d.isocalendar()
        wk = f"{iso_year}-W{iso_week:02d}"
        if wk not in week_meta:
            # week start = Monday, end = Sunday
            week_meta[wk] = {
                "week": wk,
                "start": (d - timedelta(days=d.isoweekday() - 1)).isoformat(),
                "end": (d + timedelta(days=7 - d.isoweekday())).isoformat(),
            }
        for ap in _activities_of(d):
            try:
                a = json.loads(ap.read_text(encoding="utf-8"))
            except Exception:
                continue
            mod = _modality_of(a)
            b = week_buckets[wk][mod]
            b["sessions"] += 1
            dur = float(a.get("duration") or 0)
            dist = float(a.get("distance") or 0)
            hr = a.get("averageHR")
            b["time_s"] += dur
            b["distance_m"] += dist
            if hr is not None and dur > 0:
                b["_hr_num"] += float(hr) * dur
                b["_hr_den"] += dur

    out: list[dict] = []
    for wk in sorted(week_meta.keys()):
        modalities = {}
        for mod, b in week_buckets[wk].items():
            avg_hr = (b["_hr_num"] / b["_hr_den"]) if b["_hr_den"] else None
            modalities[mod] = {
                "sessions": b["sessions"],
                "time_s": int(b["time_s"]),
                "distance_m": int(b["distance_m"]) if b["distance_m"] else None,
                "avg_hr": round(avg_hr, 1) if avg_hr else None,
            }
        out.append({**week_meta[wk], "modalities": modalities})
    return out


def _collect_acwr(days: list[date]) -> list[dict]:
    """Acute (7d) vs chronic (28d) workload ratio, computed per anchor day.

    Workload proxy: total activity duration in minutes per day (simple, robust).
    For each day d in days that has >=28 days of history, compute:
        acute_7  = sum(duration_minutes for d-6..d) / 7
        chronic_28 = sum(duration_minutes for d-27..d) / 28
        ratio = acute_7 / chronic_28
    """
    if not days:
        return []
    daily_min: dict[date, float] = defaultdict(float)
    for d in days:
        total = 0.0
        for ap in _activities_of(d):
            try:
                a = json.loads(ap.read_text(encoding="utf-8"))
                total += float(a.get("duration") or 0) / 60.0
            except Exception:
                pass
        daily_min[d] = total

    out: list[dict] = []
    sorted_days = sorted(daily_min.keys())
    if not sorted_days:
        return []
    span_start = sorted_days[0]
    cur = span_start + timedelta(days=27)  # need 28 days of history
    last = sorted_days[-1]
    while cur <= last:
        acute = sum(daily_min.get(cur - timedelta(days=i), 0.0) for i in range(7)) / 7
        chronic = sum(daily_min.get(cur - timedelta(days=i), 0.0) for i in range(28)) / 28
        if chronic > 0:
            out.append({
                "date": cur.isoformat(),
                "acute_min_d": round(acute, 1),
                "chronic_min_d": round(chronic, 1),
                "ratio": round(acute / chronic, 2),
            })
        cur += timedelta(days=1)
    return out


def _collect_hr_zones_recent(days: list[date], window_days: int = 7) -> dict:
    """Sum seconds in each HR zone (Z1-Z5) across .fit files of last N days."""
    if not days:
        return {z[0]: 0 for z in ZONE_BOUNDS}
    last = days[-1]
    cutoff = last - timedelta(days=window_days - 1)
    totals = {z[0]: 0.0 for z in ZONE_BOUNDS}
    for d in days:
        if d < cutoff:
            continue
        adir = DATA_DIR / d.isoformat() / "activities"
        if not adir.exists():
            continue
        for fit in adir.glob("*.fit"):
            zones = parse_fit_zones(fit)
            if not zones:
                continue
            for k, v in zones.items():
                totals[k] += float(v)
    return {k: int(v) for k, v in totals.items()}


# -----------------------------------------------------------------------------
# Ledger: RPE + body log
# -----------------------------------------------------------------------------

LEDGER = PROJECT_ROOT / "executed_volume.md"
RPE_TABLE_HEADER = "## RPE por día"
RPE_ROW_RE = re.compile(
    r"^\|\s*(?P<date>\d{4}-\d{2}-\d{2})\s*\|\s*(?P<rpe>\d{1,2}|—)\s*\|\s*(?P<notes>[^|]*?)\s*\|\s*$",
    re.MULTILINE,
)


def _collect_rpe_history() -> list[dict]:
    if not LEDGER.exists():
        return []
    text = LEDGER.read_text(encoding="utf-8")
    if RPE_TABLE_HEADER not in text:
        return []
    sub = text[text.index(RPE_TABLE_HEADER):]
    out: list[dict] = []
    for m in RPE_ROW_RE.finditer(sub):
        rpe_raw = m.group("rpe")
        if rpe_raw == "—":
            continue  # skip backfill placeholders
        try:
            out.append({
                "date": m.group("date"),
                "rpe": int(rpe_raw),
                "notes": m.group("notes").strip(),
            })
        except ValueError:
            continue
    return out


def _collect_body_log_history() -> list[dict]:
    return [
        {
            "date": r["fecha"],
            "parte": r["parte"],
            "severidad": int(r["severidad"]),
            "estado": r["estado"],
            "notas": r["notas"],
        }
        for r in read_bitacora_rows()
    ]


# -----------------------------------------------------------------------------
# Alerts (driven by profile thresholds)
# -----------------------------------------------------------------------------

def _baseline_avg(series: list[list], days_back: int = 14) -> float | None:
    """Average of the last `days_back` numeric points of a series, excluding the latest."""
    if len(series) < 3:
        return None
    pts = [v for _, v in series[-(days_back + 1):-1] if v is not None]
    return (sum(pts) / len(pts)) if pts else None


def _compute_alerts(current: dict, trends: dict, body_open: list[dict],
                    acwr: list[dict], thresholds: dict) -> list[dict]:
    alerts: list[dict] = []

    # HRV drop vs baseline
    hrv_now = current.get("hrv_avg")
    baseline = _baseline_avg(trends.get("hrv_avg") or [])
    drop_pct_thresh = thresholds.get("hrv_drop_pct_vs_baseline")
    if hrv_now is not None and baseline and drop_pct_thresh is not None:
        drop_pct = (1 - hrv_now / baseline) * 100
        if drop_pct >= drop_pct_thresh:
            alerts.append({
                "level": "warning",
                "metric": "hrv_avg",
                "message": f"HRV cayó {drop_pct:.0f}% vs baseline 14d "
                           f"(actual {hrv_now}, baseline {baseline:.0f})",
            })

    # Sleep below threshold
    sleep_now = current.get("sleep_duration_h")
    sleep_thresh = thresholds.get("sleep_below_hours")
    streak_thresh = thresholds.get("sleep_streak_below_days") or 1
    if sleep_now is not None and sleep_thresh and sleep_now < sleep_thresh:
        # Check streak
        sd_series = trends.get("sleep_duration_h") or []
        last = sd_series[-streak_thresh:]
        if len(last) >= streak_thresh and all(v < sleep_thresh for _, v in last):
            alerts.append({
                "level": "warning",
                "metric": "sleep_duration_h",
                "message": f"Dormiste menos de {sleep_thresh}h en los últimos "
                           f"{streak_thresh} días seguidos",
            })

    # RHR above baseline
    rhr_now = current.get("rhr")
    rhr_baseline = _baseline_avg(trends.get("rhr") or [])
    rhr_thresh = thresholds.get("rhr_above_baseline_bpm")
    if rhr_now and rhr_baseline and rhr_thresh:
        delta = rhr_now - rhr_baseline
        if delta >= rhr_thresh:
            alerts.append({
                "level": "warning",
                "metric": "rhr",
                "message": f"RHR está {delta:+.0f} bpm sobre baseline "
                           f"({rhr_now} vs {rhr_baseline:.0f})",
            })

    # Body battery morning low
    bb_thresh = thresholds.get("body_battery_morning_below")
    bb_high = current.get("body_battery_high")
    if bb_high is not None and bb_thresh and bb_high < bb_thresh:
        alerts.append({
            "level": "warning",
            "metric": "body_battery",
            "message": f"Body Battery máximo del día = {bb_high} (umbral {bb_thresh})",
        })

    # Stress avg above
    stress_thresh = thresholds.get("stress_avg_above")
    stress_now = current.get("stress_avg")
    if stress_now is not None and stress_thresh and stress_now > stress_thresh:
        alerts.append({
            "level": "warning",
            "metric": "stress",
            "message": f"Stress avg = {stress_now} (umbral {stress_thresh})",
        })

    # ACWR (latest reading)
    acwr_thresh = thresholds.get("acwr_above")
    if acwr and acwr_thresh:
        latest = acwr[-1]
        if latest["ratio"] >= acwr_thresh:
            alerts.append({
                "level": "danger",
                "metric": "acwr",
                "message": f"ACWR = {latest['ratio']} (umbral {acwr_thresh}). "
                           f"Riesgo de sobrecarga.",
            })

    # Body issue open too long
    open_days_thresh = thresholds.get("body_issue_open_days_max")
    if open_days_thresh:
        today = date.today()
        for issue in body_open:
            try:
                opened = date.fromisoformat(issue["fecha"])
                days_open = (today - opened).days
                if days_open >= open_days_thresh:
                    alerts.append({
                        "level": "warning",
                        "metric": "body_issue",
                        "message": f"{issue['parte']} abierto hace {days_open} días "
                                   f"(sev {issue['severidad']})",
                    })
            except Exception:
                pass

    return alerts


# -----------------------------------------------------------------------------
# Top-level builder
# -----------------------------------------------------------------------------

def _collect_current_training_state(day: date) -> dict:
    """Pull today's training_readiness + training_status + recovery_time
    from wellness_extended.json (the FirstBeat training stack)."""
    we = load_wellness_extended(day)
    if not we:
        return {}
    out: dict = {}

    tr_list = we.get("training_readiness") or []
    if isinstance(tr_list, list) and tr_list:
        latest = tr_list[-1] if isinstance(tr_list[-1], dict) else None
        if latest:
            out["readiness_score"] = latest.get("score")
            out["readiness_level"] = latest.get("level")
            out["readiness_feedback_short"] = latest.get("feedbackShort")
            out["readiness_feedback_long"] = latest.get("feedbackLong")
            out["recovery_time_min"] = latest.get("recoveryTime")
            out["sleep_score_factor"] = latest.get("sleepScoreFactorPercent")
            out["acwr_factor_pct"] = latest.get("acwrFactorPercent")
            out["acwr_factor_feedback"] = latest.get("acwrFactorFeedback")
            out["acute_load"] = latest.get("acuteLoad")
            out["hrv_factor_pct"] = latest.get("hrvFactorPercent")
            out["hrv_factor_feedback"] = latest.get("hrvFactorFeedback")
            out["stress_history_factor_pct"] = latest.get("stressHistoryFactorPercent")
            out["stress_history_feedback"] = latest.get("stressHistoryFactorFeedback")

    ts = we.get("training_status") or {}
    if isinstance(ts, dict):
        # mostRecentTrainingStatus is a dict keyed by deviceId
        most_recent = ts.get("mostRecentTrainingStatus") or {}
        if isinstance(most_recent, dict):
            ldd = most_recent.get("latestTrainingStatusData")
            # ldd is itself a dict keyed by deviceId
            if isinstance(ldd, dict):
                vals = list(ldd.values())
                if vals and isinstance(vals[0], dict):
                    out["training_status_phrase"] = vals[0].get("trainingStatus")
                    out["training_status_feedback"] = vals[0].get("trainingStatusFeedbackPhrase")

    # Respiration / SpO2 of the day for the hero
    resp = we.get("respiration") or {}
    if isinstance(resp, dict):
        out["respiration_avg"] = resp.get("avgWakingRespirationValue") or resp.get("avgSleepRespirationValue")
    spo2 = we.get("spo2") or {}
    if isinstance(spo2, dict):
        out["spo2_avg"] = spo2.get("averageSpO2")
        out["spo2_lowest"] = spo2.get("lowestSpO2")

    return out


def _load_profile_history() -> list[dict]:
    """Load `_meta.history` from profile.yml (audit log of Garmin-driven
    changes to LTHR, FTP, weight, etc.). Returns [] if absent."""
    try:
        import yaml
    except ImportError:
        return []
    p = PROJECT_ROOT / "profile.yml"
    if not p.exists():
        return []
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    hist = (data.get("_meta") or {}).get("history") or []
    return list(hist) if isinstance(hist, list) else []


def collect_dashboard_data() -> dict:
    """Build the complete dashboard data payload (no rendering)."""
    profile = load_active_profile()
    days = _iter_day_dirs()
    last_day = days[-1] if days else None

    trends = _collect_wellness_trends(days) if days else {}
    extended_trends = _collect_extended_trends(days) if days else {}
    weekly_volume = _collect_weekly_volume(days) if days else []
    acwr = _collect_acwr(days) if days else []
    hr_zones_recent = _collect_hr_zones_recent(days) if days else {}
    rpe_history = _collect_rpe_history()
    body_log_history = _collect_body_log_history()
    athlete_profile = _collect_athlete_profile_snapshot()
    athlete_evolution = _collect_athlete_evolution()
    anchor = days[-1] if days else date.today()
    planned_sessions = _collect_planned_sessions(anchor, days_ahead=7)
    recent_volume = _collect_recent_volume_summary(days) if days else {}

    # current state from latest day
    current_wellness: dict = {}
    current_training: dict = {}
    if last_day:
        f = wellness_summary_fields(last_day)
        sd = f.get("sleep_dur") or "—"
        dur_h = None
        if sd and sd != "—":
            try:
                h_part, m_part = sd.split("h")
                dur_h = round(int(h_part) + int(m_part.rstrip("m")) / 60.0, 2)
            except Exception:
                pass
        current_wellness = {
            "date": last_day.isoformat(),
            "sleep_score": f.get("sleep_score"),
            "sleep_duration_h": dur_h,
            "hrv_avg": f.get("hrv_avg"),
            "hrv_status": f.get("hrv_status"),
            "rhr": f.get("rhr"),
            "body_battery_low": f.get("bb_low"),
            "body_battery_high": f.get("bb_high"),
            "stress_avg": f.get("stress_avg"),
            "stress_max": f.get("stress_max"),
        }
        current_training = _collect_current_training_state(last_day)

    body_open = current_open_body_issues()
    thresholds = profile.alert_thresholds()
    alerts = _compute_alerts(current_wellness, trends, body_open, acwr, thresholds)

    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "profile": {
            "name": profile.name,
            "description": profile.description.strip(),
            "metrics_to_watch": profile.metrics_to_watch(),
            "thresholds": thresholds,
            "feedback_cadence": profile.feedback_cadence(),
        },
        "current_state": {
            "wellness": current_wellness,
            "training": current_training,
            "open_body_issues": body_open,
            "alerts": alerts,
        },
        "athlete_profile": athlete_profile,
        "athlete_evolution": athlete_evolution,
        "planned_sessions": planned_sessions,
        "recent_volume": recent_volume,
        "trends": trends,
        "extended_trends": extended_trends,
        "weekly_volume": weekly_volume,
        "rpe_history": rpe_history,
        "body_log_history": body_log_history,
        "acwr": acwr,
        "hr_zones_recent_7d": hr_zones_recent,
        "profile_history": _load_profile_history(),
        "lthr_bpm": LTHR,
    }


def render_dashboard_html(payload: dict) -> str:
    """Inline Chart.js + payload + template into a single HTML string."""
    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(
            f"Dashboard template missing at {TEMPLATE_PATH}. "
            "Did you delete dashboard/template.html?"
        )
    if not CHARTJS_PATH.exists():
        raise FileNotFoundError(
            f"Chart.js missing at {CHARTJS_PATH}. "
            "Re-download with: curl -sSL "
            "https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js "
            f"-o {CHARTJS_PATH}"
        )
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    chartjs = CHARTJS_PATH.read_text(encoding="utf-8")
    data_json = json.dumps(payload, indent=None, separators=(",", ":"),
                           ensure_ascii=False, default=str)
    html = template.replace("/*__CHARTJS__*/", chartjs)
    html = html.replace("/*__DATA__*/", data_json)
    return html


def build_dashboard(out_path: Path | None = None) -> Path:
    """End-to-end: collect data → render → write HTML."""
    payload = collect_dashboard_data()
    html = render_dashboard_html(payload)
    target = out_path or OUTPUT_PATH
    target.write_text(html, encoding="utf-8")
    return target
