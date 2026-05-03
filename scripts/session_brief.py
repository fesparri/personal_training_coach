"""
session_brief.py

Generates the pre-session brief Claude reads before proposing or adjusting the
next session. Combines:
- today's wellness markers (sleep, HRV, RHR, body battery, stress)
- last 3 sessions (key metrics: modality, duration, distance, avg HR, zones)
- current week's volume vs. plan target (best-effort textual section, since
  weekly_summary.py owns the structured rollup)
- open alarms scraped from data/manual_notes/ and any "ALARMA"/"DOLOR"/"RIR"
  lines
- the next session as defined in master_plan.md (best-effort: prints the next
  date heading after today)

Output goes to stdout (so the user can pipe into a conversation), and to
reports/briefs/YYYY-MM-DD.md.

Usage:
    python scripts/session_brief.py            # uses today
    python scripts/session_brief.py --asof 2026-04-30
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
MASTER_PLAN = PROJECT_ROOT / "master_plan.md"
ADJUSTMENTS = PROJECT_ROOT / "plan_adjustments.md"
BRIEFS_DIR = PROJECT_ROOT / "reports" / "briefs"


def _wellness_path(day: date) -> Path:
    return DATA_DIR / day.isoformat() / "wellness.json"


def _notes_path(day: date) -> Path:
    return DATA_DIR / day.isoformat() / "notes.md"


def _activities_dir(day: date) -> Path:
    return DATA_DIR / day.isoformat() / "activities"

ALARM_PATTERNS = re.compile(r"(?i)\b(alarma|dolor|molestia|rir|inflama|tendin|pinchaz)")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate pre-session brief.")
    p.add_argument("--asof", type=str, default=None, help="Anchor date YYYY-MM-DD (default today).")
    p.add_argument("--days-back", type=int, default=7, help="Window for notes/wellness scan (default 7).")
    return p.parse_args()


def load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        print(f"  ! could not read {path.name}: {e}", file=sys.stderr)
        return None


def wellness_for(day: date) -> dict | None:
    p = _wellness_path(day)
    return load_json(p) if p.exists() else None


def fmt_wellness_block(day: date) -> str:
    w = wellness_for(day)
    if not w:
        return f"_Sin wellness para {day.isoformat()}._"

    sleep = w.get("sleep") or {}
    sleep_dto = sleep.get("dailySleepDTO") if isinstance(sleep, dict) else None
    sleep_score = None
    sleep_dur = None
    if isinstance(sleep_dto, dict):
        sleep_score = (sleep_dto.get("sleepScores") or {}).get("overall", {}).get("value")
        sleep_dur_s = sleep_dto.get("sleepTimeSeconds")
        if sleep_dur_s:
            h, rem = divmod(int(sleep_dur_s), 3600)
            m, _ = divmod(rem, 60)
            sleep_dur = f"{h}h{m:02d}m"

    hrv = w.get("hrv") or {}
    hrv_summary = hrv.get("hrvSummary") if isinstance(hrv, dict) else None
    hrv_last = hrv_summary.get("lastNightAvg") if isinstance(hrv_summary, dict) else None
    hrv_status = hrv_summary.get("status") if isinstance(hrv_summary, dict) else None

    rhr = w.get("resting_heart_rate") or {}
    rhr_val = None
    if isinstance(rhr, dict):
        try:
            metrics = ((rhr.get("allMetrics") or {}).get("metricsMap") or {}) \
                .get("WELLNESS_RESTING_HEART_RATE") or []
            if metrics:
                rhr_val = metrics[0].get("value")
        except Exception:
            pass

    bb = w.get("body_battery") or []
    bb_low = bb_high = None
    if isinstance(bb, list) and bb:
        try:
            first = bb[0]
            arr = first.get("bodyBatteryValuesArray") or []
            vals = [x[1] for x in arr if isinstance(x, list) and len(x) >= 2 and x[1] is not None]
            if vals:
                bb_low, bb_high = min(vals), max(vals)
        except Exception:
            pass

    stress = w.get("stress") or {}
    stress_avg = stress.get("avgStressLevel") if isinstance(stress, dict) else None
    stress_max = stress.get("maxStressLevel") if isinstance(stress, dict) else None

    return (
        f"- Sueño: score {sleep_score if sleep_score is not None else '—'}, "
        f"duración {sleep_dur or '—'}\n"
        f"- HRV (anoche): {hrv_last if hrv_last is not None else '—'} ms"
        f" ({hrv_status or '—'})\n"
        f"- RHR: {rhr_val if rhr_val is not None else '—'} bpm\n"
        f"- Body Battery (rango día): {bb_low if bb_low is not None else '—'}"
        f" → {bb_high if bb_high is not None else '—'}\n"
        f"- Estrés: avg {stress_avg if stress_avg is not None else '—'},"
        f" max {stress_max if stress_max is not None else '—'}"
    )


def last_n_sessions(n: int = 3) -> list[dict]:
    if not DATA_DIR.exists():
        return []
    activity_paths: list[tuple[str, Path]] = []
    for day_dir in sorted(DATA_DIR.iterdir()):
        if not day_dir.is_dir():
            continue
        try:
            date.fromisoformat(day_dir.name)
        except Exception:
            continue
        adir = day_dir / "activities"
        if not adir.exists():
            continue
        for path in sorted(adir.glob("*.json")):
            activity_paths.append((day_dir.name, path))
    out = []
    for day, path in activity_paths[-n:]:
        a = load_json(path) or {}
        activity_id = a.get("activityId") or a.get("activity_id")
        fit_parsed = None
        if activity_id is not None:
            fp = path.parent / f"{activity_id}_parsed.json"
            if fp.exists():
                fit_parsed = load_json(fp)
        out.append({"day": day, "activity": a, "fit": fit_parsed, "path": path})
    return out


def fmt_session_line(rec: dict) -> str:
    a = rec["activity"]
    fit = rec.get("fit")
    name = a.get("activityName") or "(sin nombre)"
    dur = (fit.get("summary", {}).get("total_elapsed_time_s") if fit else None) \
        or a.get("duration") or 0
    dist = (fit.get("summary", {}).get("total_distance_m") if fit else None) \
        or a.get("distance") or 0
    avg_hr = (fit.get("summary", {}).get("avg_heart_rate") if fit else None) \
        or a.get("averageHR")
    try:
        dur = float(dur or 0)
    except Exception:
        dur = 0.0
    try:
        dist = float(dist or 0)
    except Exception:
        dist = 0.0
    h, rem = divmod(int(dur), 3600)
    m, _ = divmod(rem, 60)
    dur_s = f"{h}h{m:02d}m" if h else f"{m}m"
    dist_s = f"{dist/1000:.2f} km" if dist else "—"
    hr_s = f"{int(avg_hr)} bpm" if avg_hr else "—"
    zone_s = ""
    if fit:
        zs = fit.get("zone_seconds") or {}
        if any(zs.values()):
            zone_s = " · zonas " + ", ".join(f"{k}:{int(v)}s" for k, v in zs.items())
    return f"- {rec['day']} — {name} · {dur_s} · {dist_s} · FC {hr_s}{zone_s}"


def collect_alarms(asof: date, days_back: int) -> list[str]:
    alarms: list[str] = []
    if not DATA_DIR.exists():
        return alarms
    for day_dir in sorted(DATA_DIR.iterdir(), reverse=True):
        if not day_dir.is_dir():
            continue
        try:
            day = date.fromisoformat(day_dir.name)
        except Exception:
            continue
        if (asof - day).days > days_back or day > asof:
            continue
        notes_path = day_dir / "notes.md"
        if not notes_path.exists():
            continue
        try:
            text = notes_path.read_text(encoding="utf-8")
        except Exception:
            continue
        for line in text.splitlines():
            if ALARM_PATTERNS.search(line):
                alarms.append(f"- [{day.isoformat()}] {line.strip()}")
    return alarms


def find_next_session(asof: date) -> str:
    if not MASTER_PLAN.exists():
        return "_master_plan.md no existe._"
    text = MASTER_PLAN.read_text(encoding="utf-8")
    # Find the first ## or ### heading whose date is >= asof.
    pattern = re.compile(r"^(#{1,4})\s*(\d{4}-\d{2}-\d{2})\b(.*)$", re.MULTILINE)
    matches = list(pattern.finditer(text))
    if not matches:
        return "_No se detectaron encabezados con fecha YYYY-MM-DD en master_plan.md._"
    chosen = None
    for m in matches:
        try:
            d = date.fromisoformat(m.group(2))
        except Exception:
            continue
        if d >= asof:
            chosen = m
            break
    if not chosen:
        return "_master_plan.md no contiene una sesión con fecha >= hoy._"

    start = chosen.start()
    next_match = None
    for m in matches:
        if m.start() > start:
            next_match = m
            break
    end = next_match.start() if next_match else len(text)
    block = text[start:end].strip()
    return block


def recent_adjustments() -> str:
    if not ADJUSTMENTS.exists():
        return "_plan_adjustments.md no existe._"
    text = ADJUSTMENTS.read_text(encoding="utf-8").strip()
    if not text:
        return "_Sin ajustes registrados._"
    blocks = [b.strip() for b in text.split("---") if b.strip()]
    last = blocks[-3:] if len(blocks) > 3 else blocks
    return "\n\n---\n\n".join(last)


def main() -> int:
    args = parse_args()
    asof = date.fromisoformat(args.asof) if args.asof else date.today()

    sections: list[str] = []
    sections.append(f"# Pre-session brief — {asof.isoformat()}")
    sections.append("")
    sections.append("## Wellness de hoy")
    sections.append(fmt_wellness_block(asof))
    sections.append("")

    sections.append("## Últimas 3 sesiones")
    sessions = last_n_sessions(3)
    if not sessions:
        sections.append("_Sin sesiones registradas._")
    else:
        for rec in sessions:
            sections.append(fmt_session_line(rec))
    sections.append("")

    sections.append("## Volumen semanal vs. plan")
    iso_year, iso_week, _ = asof.isocalendar()
    weekly_path = PROJECT_ROOT / "reports" / "weekly" / f"{iso_year}-W{iso_week:02d}.md"
    if weekly_path.exists():
        sections.append(f"_Ver `{weekly_path.relative_to(PROJECT_ROOT)}` para el detalle._")
    else:
        sections.append(
            "_No hay reporte semanal generado para esta semana. "
            "Corré `python scripts/weekly_summary.py` antes de pedir un brief._"
        )
    sections.append("")

    sections.append("## Alarmas abiertas (notas, dolor, RIR)")
    alarms = collect_alarms(asof, args.days_back)
    if not alarms:
        sections.append("_Sin alarmas en la ventana revisada._")
    else:
        sections.extend(alarms)
    sections.append("")

    sections.append("## Próxima sesión según master_plan.md")
    sections.append("")
    sections.append(find_next_session(asof))
    sections.append("")

    sections.append("## Últimos ajustes registrados")
    sections.append("")
    sections.append(recent_adjustments())
    sections.append("")

    out = "\n".join(sections)

    BRIEFS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = BRIEFS_DIR / f"{asof.isoformat()}.md"
    out_path.write_text(out, encoding="utf-8")

    print(out)
    print(f"\n[brief escrito en {out_path.relative_to(PROJECT_ROOT)}]", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
