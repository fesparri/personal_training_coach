"""
weekly_summary.py

Builds rolling 7- and 14-day volume reports per modality from
data/activities/*.json (Garmin summary) and the matching parsed .fit JSON
when available (data/activities_raw/<id>.json).

Modalities:
    run, row, ski, strength, sled, cycling, wb_volume, other

For each modality and window we compute:
    session_count, total_time_s, total_distance_m (when applicable),
    avg_hr (sample-weighted across sessions), zone_distribution_s.

Output:
    reports/weekly/YYYY-Www.md  (markdown tables)

Usage:
    python scripts/weekly_summary.py            # uses today as anchor
    python scripts/weekly_summary.py --asof 2026-04-30
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

# Re-uso el helper que ya parsea zonas Z1-Z5 desde un .fit (mismo cálculo
# que usa el feedback de daily/feedback_session). Si _session_lib no es
# importable por alguna razón, fall back a "sin zonas" como antes.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from _session_lib import parse_fit_zones as _parse_fit_zones  # type: ignore
except Exception:  # noqa: BLE001
    _parse_fit_zones = None

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
REPORT_DIR = PROJECT_ROOT / "reports" / "weekly"

ZONE_KEYS = ["Z1", "Z2", "Z3", "Z4", "Z5"]

# Map common Garmin activityType keys + .fit sport/sub_sport into our modalities.
MODALITIES = ["run", "row", "ski", "strength", "sled", "cycling", "wb_volume", "other"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build a 7/14-day volume report.")
    p.add_argument("--asof", type=str, default=None, help="Anchor date YYYY-MM-DD (default today).")
    return p.parse_args()


def classify(activity: dict, fit_parsed: dict | None) -> str:
    """Decide a single modality bucket per activity."""
    name = (activity.get("activityName") or "").lower()
    type_key = ""
    at = activity.get("activityType") or {}
    if isinstance(at, dict):
        type_key = (at.get("typeKey") or "").lower()

    sport = sub = ""
    if fit_parsed:
        s = fit_parsed.get("summary") or {}
        sport = (s.get("sport") or "").lower()
        sub = (s.get("sub_sport") or "").lower()

    blob = " ".join([name, type_key, sport, sub])

    # Order matters: more specific first.
    if "sled" in blob or "prowler" in blob:
        return "sled"
    if "row" in blob or "rowing" in blob:
        return "row"
    if "ski" in blob and "erg" in blob:
        return "ski"
    if "ski" in blob:
        return "ski"
    if "wall" in blob and ("ball" in blob or "wb" in blob):
        return "wb_volume"
    if "strength" in blob or "weight" in blob or "gym" in blob or sub == "strength_training":
        return "strength"
    if "cycl" in blob or "bike" in blob or "ride" in blob or sport == "cycling":
        return "cycling"
    if "run" in blob or sport == "running":
        return "run"
    return "other"


def load_activities() -> list[tuple[dict, dict | None, date]]:
    """Cargar todas las actividades + zonas Z1-Z5.

    Para cada actividad:
        1. Lee el JSON resumen de Garmin.
        2. Si existe `<id>_parsed.json` (cache), lo usa.
        3. Si no existe pero hay `<id>.fit`, parsea las zonas en vivo
           (mismo helper que feedback_session) y construye un fit_parsed
           mínimo con las zonas — así weekly_summary nunca queda sin
           datos de zonas si el .fit está en disco.
    """
    out: list[tuple[dict, dict | None, date]] = []
    if not DATA_DIR.exists():
        return out
    for day_dir in sorted(DATA_DIR.iterdir()):
        if not day_dir.is_dir():
            continue
        try:
            day = date.fromisoformat(day_dir.name)
        except Exception:
            continue
        adir = day_dir / "activities"
        if not adir.exists():
            continue
        for path in sorted(adir.glob("*.json")):
            # ignorar los _parsed.json que viven al lado del activity JSON
            if path.stem.endswith("_parsed"):
                continue
            try:
                activity = json.loads(path.read_text(encoding="utf-8"))
            except Exception as e:  # noqa: BLE001
                print(f"  ! could not read {path.relative_to(DATA_DIR)}: {e}")
                continue

            activity_id = activity.get("activityId") or activity.get("activity_id")
            fit_parsed: dict | None = None

            if activity_id is not None:
                fit_json = adir / f"{activity_id}_parsed.json"
                fit_raw = adir / f"{activity_id}.fit"

                if fit_json.exists():
                    try:
                        fit_parsed = json.loads(fit_json.read_text(encoding="utf-8"))
                    except Exception as e:  # noqa: BLE001
                        print(f"  ! could not read {fit_json.name}: {e}")

                if fit_parsed is None and fit_raw.exists() and _parse_fit_zones is not None:
                    zones = _parse_fit_zones(fit_raw)
                    if zones:
                        # construir un fit_parsed mínimo compatible con aggregate()
                        fit_parsed = {
                            "zone_seconds": {
                                "Z1": float(zones.get("Z1", 0)),
                                "Z2": float(zones.get("Z2", 0)),
                                "Z3": float(zones.get("Z3", 0)),
                                "Z4": float(zones.get("Z4", 0)),
                                "Z5": float(zones.get("Z5", 0)),
                            }
                        }

            out.append((activity, fit_parsed, day))
    return out


def aggregate(records: list[tuple[dict, dict | None, date]],
              start: date, end: date) -> dict:
    """Aggregate per modality between [start, end] inclusive."""
    buckets: dict[str, dict] = {m: {
        "session_count": 0,
        "total_time_s": 0.0,
        "total_distance_m": 0.0,
        "hr_seconds": 0.0,        # for sample-weighted avg HR
        "hr_seconds_x_bpm": 0.0,  # numerator
        "zones": {z: 0.0 for z in ZONE_KEYS},
    } for m in MODALITIES}

    for activity, fit_parsed, day in records:
        if not (start <= day <= end):
            continue
        m = classify(activity, fit_parsed)
        b = buckets[m]
        b["session_count"] += 1

        # Prefer .fit summary numbers, fall back to Garmin summary fields.
        dur = None
        dist = None
        avg_hr = None
        if fit_parsed:
            s = fit_parsed.get("summary") or {}
            dur = s.get("total_elapsed_time_s") or s.get("total_timer_time_s")
            dist = s.get("total_distance_m")
            avg_hr = s.get("avg_heart_rate")
            zs = fit_parsed.get("zone_seconds") or {}
            for z in ZONE_KEYS:
                b["zones"][z] += float(zs.get(z, 0.0) or 0.0)
        if dur is None:
            dur = activity.get("duration") or activity.get("elapsedDuration")
        if dist is None:
            dist = activity.get("distance")
        if avg_hr is None:
            avg_hr = activity.get("averageHR")

        try:
            dur = float(dur or 0.0)
        except Exception:
            dur = 0.0
        try:
            dist = float(dist or 0.0)
        except Exception:
            dist = 0.0
        try:
            avg_hr = float(avg_hr) if avg_hr is not None else None
        except Exception:
            avg_hr = None

        b["total_time_s"] += dur
        b["total_distance_m"] += dist
        if avg_hr is not None and dur > 0:
            b["hr_seconds"] += dur
            b["hr_seconds_x_bpm"] += avg_hr * dur

    # finalise avg_hr
    for m in MODALITIES:
        b = buckets[m]
        b["avg_hr"] = (b["hr_seconds_x_bpm"] / b["hr_seconds"]) if b["hr_seconds"] else None
    return buckets


def fmt_minutes(seconds: float) -> str:
    if not seconds:
        return "—"
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, _ = divmod(rem, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m"


def fmt_km(meters: float) -> str:
    if not meters:
        return "—"
    return f"{meters/1000:.2f} km"


def fmt_hr(hr: float | None) -> str:
    return f"{hr:.0f} bpm" if hr else "—"


def render_modality_table(title: str, buckets: dict) -> str:
    lines = [f"### {title}", "", "| Modalidad | Sesiones | Tiempo | Distancia | FC media |",
             "|---|---:|---:|---:|---:|"]
    for m in MODALITIES:
        b = buckets[m]
        if b["session_count"] == 0 and b["total_time_s"] == 0:
            continue
        lines.append(
            f"| {m} | {b['session_count']} | {fmt_minutes(b['total_time_s'])} "
            f"| {fmt_km(b['total_distance_m'])} | {fmt_hr(b['avg_hr'])} |"
        )
    if len(lines) == 4:
        lines.append("| _(sin sesiones en la ventana)_ | | | | |")
    return "\n".join(lines)


def render_zones_table(title: str, buckets: dict) -> str:
    lines = [f"### {title} — distribución de zonas (segundos)", "",
             "| Modalidad | Z1 | Z2 | Z3 | Z4 | Z5 |",
             "|---|---:|---:|---:|---:|---:|"]
    any_row = False
    for m in MODALITIES:
        z = buckets[m]["zones"]
        if sum(z.values()) == 0:
            continue
        any_row = True
        lines.append(
            f"| {m} | {int(z['Z1'])} | {int(z['Z2'])} | {int(z['Z3'])} "
            f"| {int(z['Z4'])} | {int(z['Z5'])} |"
        )
    if not any_row:
        lines.append("| _(sin datos de zonas en la ventana)_ | | | | | |")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    asof = date.fromisoformat(args.asof) if args.asof else date.today()

    records = load_activities()
    print(f"Loaded {len(records)} activity record(s).")

    win7_start = asof - timedelta(days=6)
    win14_start = asof - timedelta(days=13)
    b7 = aggregate(records, win7_start, asof)
    b14 = aggregate(records, win14_start, asof)

    iso_year, iso_week, _ = asof.isocalendar()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORT_DIR / f"{iso_year}-W{iso_week:02d}.md"

    parts = [
        f"# Resumen semanal — {iso_year}-W{iso_week:02d}",
        f"_Anclado al {asof.isoformat()}._",
        "",
        f"## Ventana 7 días ({win7_start} → {asof})",
        "",
        render_modality_table("Volumen por modalidad", b7),
        "",
        render_zones_table("Volumen por modalidad", b7),
        "",
        f"## Ventana 14 días ({win14_start} → {asof})",
        "",
        render_modality_table("Volumen por modalidad", b14),
        "",
        render_zones_table("Volumen por modalidad", b14),
        "",
    ]
    out_path.write_text("\n".join(parts), encoding="utf-8")
    print(f"  ✓ wrote {out_path.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
