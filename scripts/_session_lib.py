"""
_session_lib.py — helpers compartidos entre plan_session.py y
feedback_session.py.

Sin dependencias entre scripts CLI: todos los helpers viven acá. No es un
módulo público — el prefijo `_` señala que solo lo usan los otros scripts
del proyecto.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
MASTER_PLAN = PROJECT_ROOT / "master_plan.md"
ADJUSTMENTS = PROJECT_ROOT / "plan_adjustments.md"
LEDGER = PROJECT_ROOT / "executed_volume.md"

# LTHR-based zone thresholds (atleta-specific, ver CLAUDE.md / master_plan.md).
LTHR = 172
ZONE_BOUNDS = [
    ("Z1", 0, 120),
    ("Z2", 120, 135),
    ("Z3", 135, 155),
    ("Z4", 155, 172),
    ("Z5", 172, 999),
]

# Sentinel para marcar secciones de session.md que esperan feedback_session.py
PENDING_FEEDBACK = "[pendiente — completar con `feedback_session.py`]"


# ---------- date utils ----------

def day_dir(d: date) -> Path:
    return DATA_DIR / d.isoformat()


# ---------- garmin sync helper ----------

def run_sync(target: date, also_yesterday: bool = True) -> int:
    """Run garmin_sync.py for the target date (and optionally yesterday)."""
    start = (target - timedelta(days=1)) if also_yesterday else target
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "garmin_sync.py"),
        "--from", start.isoformat(),
        "--to", target.isoformat(),
    ]
    print(f"\n[sync] {' '.join(cmd)}\n")
    return subprocess.call(cmd, cwd=str(PROJECT_ROOT))


# ---------- wellness ----------

def load_wellness(target: date) -> dict | None:
    p = day_dir(target) / "wellness.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  ! could not read {p.name}: {e}")
        return None


def load_wellness_extended(target: date) -> dict | None:
    """Load `data/<date>/wellness_extended.json` (training_readiness,
    training_status, max_metrics, intensity_minutes, etc. — all the per-day
    metrics garmin_sync.py writes beyond the core wellness5).
    """
    p = day_dir(target) / "wellness_extended.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  ! could not read {p.name}: {e}")
        return None


def load_athlete_metrics(target: date) -> dict | None:
    """Load `data/<date>/athlete_metrics.json` (lactate_threshold,
    cycling_ftp, race_predictions, fitness_age, body_composition, devices,
    etc. — the longitudinal performance profile snapshot).
    """
    p = day_dir(target) / "athlete_metrics.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  ! could not read {p.name}: {e}")
        return None


def latest_athlete_metrics() -> tuple[date, dict] | None:
    """Find the most recent `data/<date>/athlete_metrics.json` and load it.

    Useful for the coach's bootstrap: even if today's snapshot doesn't
    exist yet, return whatever is most recent (typically yesterday or the
    last sync). Returns None if no snapshot exists at all.
    """
    if not DATA_DIR.exists():
        return None
    for child in sorted(DATA_DIR.iterdir(), reverse=True):
        if not child.is_dir():
            continue
        try:
            d = date.fromisoformat(child.name)
        except ValueError:
            continue
        p = child / "athlete_metrics.json"
        if p.exists():
            try:
                return d, json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
    return None


def metric_history(filename: str, field_path: str) -> list[tuple[str, object]]:
    """Iterate every `data/<date>/<filename>` and extract a value from a
    dot-separated path (e.g. 'race_predictions.time5K' or
    'fitness_age.fitnessAge').

    Returns a chronologically-sorted list of (date_iso, value) pairs,
    skipping days where the file or path is missing/null. Use this to
    plot long-term evolution of any metric across either wellness.json,
    wellness_extended.json or athlete_metrics.json.

    Examples:
        # From athlete_metrics.json
        metric_history('athlete_metrics.json', 'cycling_ftp.functionalThresholdPower')
        metric_history('athlete_metrics.json', 'race_predictions.time5K')
        metric_history('athlete_metrics.json', 'lactate_threshold.power.functionalThresholdPower')

        # From wellness_extended.json
        metric_history('wellness_extended.json', 'fitness_age.fitnessAge')
        metric_history('wellness_extended.json', 'training_status.mostRecentVO2Max.generic.vo2MaxPreciseValue')
    """
    keys = field_path.split(".")
    out: list[tuple[str, object]] = []
    if not DATA_DIR.exists():
        return out
    for child in sorted(DATA_DIR.iterdir()):
        if not child.is_dir():
            continue
        try:
            date.fromisoformat(child.name)
        except ValueError:
            continue
        p = child / filename
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        cur: object = data
        for k in keys:
            if not isinstance(cur, dict) or k not in cur:
                cur = None
                break
            cur = cur[k]
        if cur is not None and cur != {} and cur != []:
            out.append((child.name, cur))
    return out


def wellness_summary_fields(target: date) -> dict:
    """Return the structured wellness summary used by both display and md write."""
    w = load_wellness(target) or {}
    sleep_dto = (w.get("sleep") or {}).get("dailySleepDTO") or {}
    score = (sleep_dto.get("sleepScores") or {}).get("overall", {}).get("value")
    dur_s = sleep_dto.get("sleepTimeSeconds")
    sleep_dur = "—"
    if dur_s:
        h, rem = divmod(int(dur_s), 3600)
        m, _ = divmod(rem, 60)
        sleep_dur = f"{h}h{m:02d}m"

    hrv_summary = (w.get("hrv") or {}).get("hrvSummary") or {}
    rhr_block = (
        ((w.get("resting_heart_rate") or {}).get("allMetrics") or {}).get("metricsMap") or {}
    ).get("WELLNESS_RESTING_HEART_RATE") or []
    rhr = rhr_block[0].get("value") if rhr_block else None

    bb_low = bb_high = None
    bb = w.get("body_battery") or []
    if isinstance(bb, list) and bb:
        try:
            arr = bb[0].get("bodyBatteryValuesArray") or []
            vals = [x[1] for x in arr if isinstance(x, list) and len(x) >= 2 and x[1] is not None]
            if vals:
                bb_low, bb_high = min(vals), max(vals)
        except Exception:
            pass

    stress = w.get("stress") or {}

    return {
        "sleep_score": score,
        "sleep_dur": sleep_dur,
        "hrv_avg": hrv_summary.get("lastNightAvg") if hrv_summary else None,
        "hrv_max": hrv_summary.get("lastNight5MinHigh") if hrv_summary else None,
        "hrv_status": hrv_summary.get("status") if hrv_summary else None,
        "rhr": rhr,
        "bb_low": bb_low,
        "bb_high": bb_high,
        "stress_avg": stress.get("avgStressLevel") if stress else None,
        "stress_max": stress.get("maxStressLevel") if stress else None,
    }


def print_wellness(target: date) -> None:
    w = load_wellness(target)
    print(f"\n=== Wellness {target.isoformat()} ===")
    if not w:
        print("  (sin wellness.json — corré `garmin_sync.py` para este día)")
        return
    f = wellness_summary_fields(target)
    rhr_str = f"{f['rhr']:.0f}" if f['rhr'] is not None else "—"
    print(f"  Sueño: score {f['sleep_score'] if f['sleep_score'] is not None else '—'},"
          f" duración {f['sleep_dur']}")
    print(f"  HRV (anoche): avg {f['hrv_avg'] if f['hrv_avg'] is not None else '—'} ms"
          f" / max {f['hrv_max'] if f['hrv_max'] is not None else '—'} ms"
          f" ({f['hrv_status'] or '—'})")
    print(f"  RHR: {rhr_str} bpm")
    print(f"  Body Battery (rango día): {f['bb_low'] if f['bb_low'] is not None else '—'} → "
          f"{f['bb_high'] if f['bb_high'] is not None else '—'}")
    print(f"  Estrés: avg {f['stress_avg'] if f['stress_avg'] is not None else '—'},"
          f" max {f['stress_max'] if f['stress_max'] is not None else '—'}")


def build_wellness_block(target: date) -> str:
    w = load_wellness(target)
    if not w:
        return "_Sin wellness.json para este día._"
    f = wellness_summary_fields(target)
    rhr_str = f"{f['rhr']:.0f}" if f['rhr'] is not None else "—"
    return (
        f"- Sueño: score {f['sleep_score'] if f['sleep_score'] is not None else '—'},"
        f" duración {f['sleep_dur']}\n"
        f"- HRV (anoche): avg {f['hrv_avg'] if f['hrv_avg'] is not None else '—'} ms"
        f" / max {f['hrv_max'] if f['hrv_max'] is not None else '—'} ms"
        f" ({f['hrv_status'] or '—'})\n"
        f"- RHR: {rhr_str} bpm\n"
        f"- Body Battery (rango día):"
        f" {f['bb_low'] if f['bb_low'] is not None else '—'} →"
        f" {f['bb_high'] if f['bb_high'] is not None else '—'}\n"
        f"- Estrés: avg {f['stress_avg'] if f['stress_avg'] is not None else '—'},"
        f" max {f['stress_max'] if f['stress_max'] is not None else '—'}"
    )


# ---------- master plan lookup ----------

def find_master_plan_target(target: date) -> str | None:
    """Best-effort: extract the row of master_plan.md whose row starts with
    | <Día> | YYYY-MM-DD | so the caller sees what was prescribed."""
    if not MASTER_PLAN.exists():
        return None
    text = MASTER_PLAN.read_text(encoding="utf-8")
    iso = target.isoformat()
    pat = re.compile(rf"^\|[^|]+\|\s*{iso}\s*\|.*$", re.MULTILINE)
    m = pat.search(text)
    return m.group(0).strip() if m else None


# ---------- activities + zones ----------

def list_today_activities(target: date) -> list[Path]:
    adir = day_dir(target) / "activities"
    if not adir.exists():
        return []
    return sorted(adir.glob("*.json"))


def hr_zone_of(hr: int | float | None) -> str | None:
    if hr is None:
        return None
    for name, lo, hi in ZONE_BOUNDS:
        if lo <= hr < hi:
            return name
    return None


def fmt_dur(seconds: float | int | None) -> str:
    if not seconds:
        return "—"
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}h{m:02d}m{sec:02d}s" if h else f"{m}m{sec:02d}s"


def parse_fit_zones(fit_path: Path) -> dict | None:
    """Distribute time across zones using consecutive timestamp deltas
    from the .fit's record messages."""
    try:
        from fitparse import FitFile
    except ImportError:
        return None
    try:
        ff = FitFile(str(fit_path))
        ff.parse()
    except Exception as e:
        print(f"  ! could not parse {fit_path.name}: {e}")
        return None

    seconds_in_zone = {z[0]: 0.0 for z in ZONE_BOUNDS}
    prev_ts = None
    prev_hr = None
    for msg in ff.get_messages("record"):
        d = {f.name: f.value for f in msg}
        ts = d.get("timestamp")
        hr = d.get("heart_rate")
        if prev_ts is not None and ts is not None and prev_hr is not None:
            dt = (ts - prev_ts).total_seconds()
            if 0 < dt < 30:
                z = hr_zone_of(prev_hr)
                if z:
                    seconds_in_zone[z] += dt
        prev_ts = ts
        prev_hr = hr
    return seconds_in_zone


def fit_files_block(target: date) -> str:
    paths = list_today_activities(target)
    if not paths:
        return "ninguno todavía"
    lines = []
    for p in paths:
        try:
            a = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        aid = a.get("activityId")
        name = a.get("activityName") or "(sin nombre)"
        sport = (a.get("activityType") or {}).get("typeKey") or ""
        dur = a.get("duration") or 0
        dist = a.get("distance") or 0
        avg_hr = a.get("averageHR")
        details = [f"{sport}", fmt_dur(dur)]
        if dist:
            details.append(f"{dist/1000:.2f} km")
        if avg_hr:
            details.append(f"FC media {int(avg_hr)} bpm")
        lines.append(
            f"- `data/{target.isoformat()}/activities/{aid}.fit` — {name} · "
            + " · ".join(details)
        )
    return "\n".join(lines)


def print_performance_feedback(target: date) -> None:
    """Print full quantitative feedback for the day's activities."""
    print(f"\n=== Performance feedback {target.isoformat()} ===")

    target_row = find_master_plan_target(target)
    if target_row:
        print("  Plan (master_plan.md):")
        print(f"    {target_row}")
    else:
        print("  Plan (master_plan.md): _no se encontró fila para esta fecha_")

    paths = list_today_activities(target)
    if not paths:
        print("  Sin actividades sincronizadas para este día.")
        return

    for p in paths:
        try:
            a = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  ! could not read {p.name}: {e}")
            continue

        aid = a.get("activityId")
        name = a.get("activityName") or "(sin nombre)"
        sport = (a.get("activityType") or {}).get("typeKey") or ""
        dur = a.get("duration") or 0
        dist = a.get("distance") or 0
        avg_hr = a.get("averageHR")
        max_hr = a.get("maxHR")
        cad_avg = a.get("averageRunCadence") or a.get("averageCadence")

        print(f"\n  ─── activity {aid} · {sport} · {name!r} ───")
        print(f"    Duración:  {fmt_dur(dur)}")
        if dist:
            km = dist / 1000
            print(f"    Distancia: {km:.2f} km")
            if dur and km:
                pace_s = dur / km
                pm, ps = divmod(int(pace_s), 60)
                print(f"    Pace:      {pm}:{ps:02d} /km")
        if avg_hr:
            print(f"    FC media:  {avg_hr:.0f} bpm  ({hr_zone_of(avg_hr)})")
        if max_hr:
            print(f"    FC max:    {max_hr:.0f} bpm  ({hr_zone_of(max_hr)})")
        if cad_avg:
            print(f"    Cadencia:  {cad_avg:.0f}")

        fit_path = p.with_suffix(".fit")
        if fit_path.exists():
            zones = parse_fit_zones(fit_path)
            if zones and any(zones.values()):
                total = sum(zones.values()) or 1
                print("    Zonas (s · %):")
                for z, _, _ in ZONE_BOUNDS:
                    sec = zones[z]
                    pct = 100 * sec / total
                    if sec:
                        print(f"      {z}: {int(sec):4d}s ({pct:4.1f}%)")


# ---------- last sessions / alarms context ----------

ALARM_PATTERNS = re.compile(r"(?i)\b(alarma|dolor|molestia|rir|inflama|tendin|pinchaz)")


def last_n_sessions(n: int = 3, before: date | None = None) -> list[dict]:
    """Return up to N most recent activities (across all dirs) before `before`."""
    if not DATA_DIR.exists():
        return []
    pairs: list[tuple[str, Path]] = []
    for dd in sorted(DATA_DIR.iterdir()):
        if not dd.is_dir():
            continue
        try:
            d = date.fromisoformat(dd.name)
        except Exception:
            continue
        if before and d >= before:
            continue
        adir = dd / "activities"
        if not adir.exists():
            continue
        for path in sorted(adir.glob("*.json")):
            pairs.append((dd.name, path))
    out = []
    for day, path in pairs[-n:]:
        try:
            a = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        out.append({"day": day, "activity": a, "path": path})
    return out


def collect_alarms(target: date, days_back: int = 7) -> list[str]:
    alarms: list[str] = []
    if not DATA_DIR.exists():
        return alarms
    for dd in sorted(DATA_DIR.iterdir(), reverse=True):
        if not dd.is_dir():
            continue
        try:
            d = date.fromisoformat(dd.name)
        except Exception:
            continue
        if d > target or (target - d).days > days_back:
            continue
        for fn in ("notes.md", "session.md"):
            p = dd / fn
            if not p.exists():
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except Exception:
                continue
            for line in text.splitlines():
                if ALARM_PATTERNS.search(line):
                    alarms.append(f"- [{dd.name} · {fn}] {line.strip()}")
    return alarms


def print_recent_context(target: date) -> None:
    """Show last 3 sessions + open alarms — context for plan_session."""
    print(f"\n=== Contexto reciente (al {target.isoformat()}) ===")
    sessions = last_n_sessions(3, before=target)
    if not sessions:
        print("  Últimas sesiones: _ninguna registrada antes de hoy._")
    else:
        print("  Últimas 3 sesiones:")
        for rec in sessions:
            a = rec["activity"]
            sport = (a.get("activityType") or {}).get("typeKey") or ""
            name = a.get("activityName") or "(sin nombre)"
            dur = a.get("duration") or 0
            dist = a.get("distance") or 0
            hr = a.get("averageHR")
            line = f"    {rec['day']} · {sport:25s} · {fmt_dur(dur):8s}"
            if dist:
                line += f" · {dist/1000:.2f} km"
            if hr:
                line += f" · FC {int(hr)}"
            line += f" · {name}"
            print(line)

    alarms = collect_alarms(target)
    if alarms:
        print("\n  Alarmas abiertas (últimos 7 días):")
        for line in alarms:
            print(f"    {line}")
    else:
        print("\n  Alarmas abiertas: ninguna detectada en últimos 7 días.")


# ---------- input loop ----------

def prompt_body_issues_loop(target: date) -> list[dict]:
    """Loop flexible de captura de molestias / cargas / lesiones.

    Muestra primero las issues actualmente abiertas según
    `executed_volume.md → Bitácora corporal` para que el atleta sepa qué
    está vivo. Después acepta N entradas (parte / severidad / estado /
    notas) hasta que se ingrese una parte vacía.

    Para cerrar una issue abierta, el atleta carga la misma parte con
    severidad 0 y estado=resolved (default cuando severidad=0).
    """
    print("\n=== Bitácora corporal ===")
    open_issues = current_open_body_issues()
    if open_issues:
        print("  Abiertas según el ledger:")
        for iss in sorted(open_issues, key=lambda x: x["parte"].lower()):
            note_short = (iss.get("notas") or "")[:60]
            print(f"    · {iss['parte']} (sev {iss['severidad']}, "
                  f"abierta desde {iss['fecha']}) — {note_short}")
        print("  Podés agregar nuevas, actualizar severidad de una existente, "
              "o cerrar una (severidad 0 + estado resolved).")
    else:
        print("  No hay molestias / lesiones abiertas en el ledger.")

    print("\nLogueá cada parte cargada/dolorida o resuelta hoy.")
    print("Enter vacío en la primera pregunta = terminar.")

    issues: list[dict] = []
    while True:
        try:
            parte = input("\n  Parte (ej. tibiales, hombro izq, lumbar) o Enter para terminar: ").strip()
        except EOFError:
            break
        if not parte:
            break

        sev = prompt_int_0_10(
            f"  Severidad de {parte}",
            "0 = ya no molesta / 5 = molestia moderada / 10 = dolor agudo o lesión activa.",
        )
        if sev == "":
            print("  ! sin severidad — entrada descartada.")
            continue

        sev_int = int(sev)
        default_estado = "resolved" if sev_int == 0 else "open"
        try:
            estado_raw = input(
                f"  Estado [open/resolved] (Enter = {default_estado}): "
            ).strip().lower()
        except EOFError:
            estado_raw = ""
        estado = estado_raw if estado_raw in ("open", "resolved") else default_estado

        try:
            notas = input("  Notas breves (1 línea, opcional): ").strip()
        except EOFError:
            notas = ""

        issues.append({
            "parte": parte,
            "severidad": sev,
            "estado": estado,
            "notas": notas,
        })
        print(f"  ✅ {parte} · sev {sev}/10 · {estado}")

    if issues:
        print(f"\n✅ Bitácora: {len(issues)} entrada(s) capturada(s).")
    else:
        print("\n✅ Bitácora: sin entradas hoy.")
    return issues


def prompt_int_0_10(label: str, prompt: str) -> str:
    """Pedir un entero 0-10. Vacío permitido (= '—'). Retry hasta input válido."""
    print(f"\n--- {label} ---")
    print(prompt)
    print("  (entero 0-10; Enter vacío para saltar)")
    while True:
        try:
            raw = input().strip()
        except EOFError:
            return ""
        if raw == "":
            return ""
        try:
            v = int(raw)
        except ValueError:
            print("  ! no es un entero válido. Intentá de nuevo (o Enter para saltar).")
            continue
        if not 0 <= v <= 10:
            print("  ! fuera de rango 0-10. Intentá de nuevo.")
            continue
        return str(v)


def prompt_section(label: str, prompt: str, multiline_hint: str = "") -> str:
    """Read user input. Doble Enter para enviar (multilínea soportado)."""
    print(f"\n--- {label} ---")
    print(prompt)
    if multiline_hint:
        print(f"  ({multiline_hint})")
    print("  (terminar con una línea en blanco; doble Enter para enviar)")
    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line == "":
            if lines:
                break
            continue
        lines.append(line)
    return "\n".join(lines).strip()


# ---------- session.md read/write ----------

SECTION_HEADERS = {
    "plan_original": "## Plan original",
    "plan_modificado": "## Plan modificado (pre-sesión)",
    "razon_ajuste": "## Razón del ajuste pre-sesión",
    "ejecutado": "## Sesión ejecutada",
    "desviaciones": "## Desviaciones durante la ejecución",
    "comentarios": "## Comentarios del atleta",
    "marcadores": "## Marcadores post-sesión",
    "wellness": "## Wellness pre-sesión",
    "fits": "## Archivos .fit asociados",
    "vinculo": "## Vínculo con master_plan.md y plan_adjustments.md",
}

SECTION_DOC = {
    "plan_original": "> Sesión tal como estaba en master_plan.md ANTES de cualquier modificación pre-sesión.",
    "plan_modificado": "> Sesión ajustada en función del wellness del día y/o eventos del calendario, ANTES de ejecutar.",
    "ejecutado": '> Lo que el atleta efectivamente realizó. Puede coincidir con "Plan modificado" o haber sufrido más cambios sobre la marcha.',
    "comentarios": "> Sensaciones, dolor, fatiga, contexto de vida que afecte la lectura de la sesión.",
    "marcadores": "> RPE = esfuerzo percibido global de la sesión (0-10). Bitácora = una entrada por cada parte del cuerpo cargada/dolorida/lesionada o resuelta hoy. La lista completa con histórico vive en `executed_volume.md` → sección `Bitácora corporal`.",
}


def session_md_path(target: date) -> Path:
    return day_dir(target) / "session.md"


def render_session_md(target: date, sections: dict) -> str:
    """Render the canonical session.md from a sections dict.

    Missing sections render as either PENDING_FEEDBACK (for Q4-Q6 fields if
    plan-only) or a clear placeholder.
    """
    target_row = find_master_plan_target(target) or "_no encontrado en master_plan.md_"
    iso = target.isoformat()

    def block(key: str, body: str | None) -> str:
        h = SECTION_HEADERS[key]
        doc = SECTION_DOC.get(key)
        body = body if body else "[awaiting user input]"
        return f"{h}\n\n" + (f"{doc}\n\n" if doc else "") + body + "\n"

    rpe = sections.get("rpe", "")
    body_issues = sections.get("body_issues") or []
    markers_lines = [f"- RPE (esfuerzo percibido global): **{rpe or '—'}** /10"]
    if body_issues:
        markers_lines.append("")
        markers_lines.append("**Bitácora corporal de hoy:**")
        for iss in body_issues:
            parte = iss.get("parte", "")
            sev = iss.get("severidad", "—")
            estado = iss.get("estado", "")
            notas = (iss.get("notas") or "").strip()
            line = f"- {parte} · sev {sev}/10 · {estado}"
            if notas:
                line += f" · {notas}"
            markers_lines.append(line)
    else:
        markers_lines.append("")
        markers_lines.append("_Sin entradas en la bitácora corporal hoy._")
    markers_body = "\n".join(markers_lines)

    parts = [
        f"# Sesión {iso}\n",
        block("plan_original", sections.get("plan_original")),
        block("plan_modificado", sections.get("plan_modificado")),
        f"{SECTION_HEADERS['razon_ajuste']}\n\n"
        + (sections.get("razon_ajuste") or "N/A") + "\n",
        block("ejecutado", sections.get("ejecutado")),
        f"{SECTION_HEADERS['desviaciones']}\n\n"
        + (sections.get("desviaciones") or "ninguna") + "\n",
        block("comentarios", sections.get("comentarios")),
        f"{SECTION_HEADERS['marcadores']}\n\n"
        f"{SECTION_DOC['marcadores']}\n\n"
        f"{markers_body}\n",
        f"{SECTION_HEADERS['wellness']}\n\n{build_wellness_block(target)}\n\n"
        f"_Auto-populated from `data/{iso}/wellness.json`._\n",
        f"{SECTION_HEADERS['fits']}\n\n{fit_files_block(target)}\n",
        f"{SECTION_HEADERS['vinculo']}\n\n"
        f"- **Master plan reference:** `{target_row}`\n"
        f"- **Adjustment log entry:** "
        f"Ver `plan_adjustments.md` — entry con `Date: {iso}`.\n",
    ]
    return "\n".join(parts)


SECTION_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)
RPE_RE = re.compile(r"RPE[^*\d]*\*\*\s*(\d{1,2})\s*\*\*", re.IGNORECASE)

# Bullets de bitácora dentro del bloque de marcadores en session.md, formato:
#   - {parte} · sev {N}/10 · {estado} · {notas}
ISSUE_BULLET_RE = re.compile(
    r"^\s*-\s*(?P<parte>[^·\n]+?)\s*·\s*sev\s*(?P<sev>\d{1,2})\s*/\s*10\s*·\s*"
    r"(?P<estado>open|resolved)(?:\s*·\s*(?P<notas>.*))?$",
    re.MULTILINE | re.IGNORECASE,
)

# Filas de la tabla 'Bitácora corporal' en executed_volume.md, formato:
#   | YYYY-MM-DD | parte | N | open|resolved | notas |
LEDGER_BITACORA_HEADER = "## Bitácora corporal"
LEDGER_BITACORA_ROW_RE = re.compile(
    r"^\|\s*(?P<fecha>\d{4}-\d{2}-\d{2})\s*\|\s*(?P<parte>[^|]+?)\s*\|\s*"
    r"(?P<sev>\d{1,2})\s*\|\s*(?P<estado>open|resolved)\s*\|\s*(?P<notas>[^|]*?)\s*\|\s*$",
    re.MULTILINE | re.IGNORECASE,
)
LEDGER_RPE_HEADER = "## RPE por día"


def parse_session_md(target: date) -> dict:
    """Read existing session.md and return a sections dict (best-effort).

    Extra: cuando encuentra la sección 'Marcadores post-sesión', parsea
    rpe (string '0'..'10') y body_issues (lista de dicts con parte /
    severidad / estado / notas).
    """
    p = session_md_path(target)
    if not p.exists():
        return {}
    text = p.read_text(encoding="utf-8")

    sections: dict = {}
    matches = list(SECTION_RE.finditer(text))
    for i, m in enumerate(matches):
        title = m.group(1).strip()
        for key, header in SECTION_HEADERS.items():
            if header[3:].strip() == title:
                start = m.end()
                end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
                body = text[start:end].strip()
                lines = body.splitlines()
                while lines and lines[0].startswith(">"):
                    lines.pop(0)
                while lines and lines[0].strip() == "":
                    lines.pop(0)
                body_clean = "\n".join(lines).strip()
                if body_clean in (PENDING_FEEDBACK, "[awaiting user input]", "N/A", "ninguna"):
                    continue
                sections[key] = body_clean
                if key == "marcadores":
                    if (mm := RPE_RE.search(body_clean)):
                        sections["rpe"] = mm.group(1)
                    issues = []
                    for im in ISSUE_BULLET_RE.finditer(body_clean):
                        issues.append({
                            "parte": im.group("parte").strip(),
                            "severidad": im.group("sev"),
                            "estado": im.group("estado").lower(),
                            "notas": (im.group("notas") or "").strip(),
                        })
                    if issues:
                        sections["body_issues"] = issues
                break
    return sections


def write_session_md(target: date, sections: dict) -> Path:
    """Write session.md with the given sections, creating dir if needed."""
    out = session_md_path(target)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_session_md(target, sections), encoding="utf-8")
    return out


# ---------- plan_adjustments.md / executed_volume.md updates ----------

def append_plan_adjustment(target: date, sections: dict) -> None:
    iso = target.isoformat()
    fit_paths = list_today_activities(target)
    fits = " + ".join(
        f"data/{iso}/activities/{p.stem}.fit" for p in fit_paths
    ) or "(sin .fit)"

    plan_orig = (sections.get("plan_original") or "").splitlines()
    plan_orig_first = plan_orig[0] if plan_orig else "(ver session.md)"

    entry = f"""

---
Date: {iso}
Original session: {plan_orig_first}
Modified to: {sections.get('plan_modificado','') or 'sin modificación'}
Executed as: {sections.get('ejecutado','') or '(ver session.md)'}
Reason: {sections.get('razon_ajuste','') or 'N/A — sin modificación pre-sesión'}
Source: data/{iso}/session.md + data/{iso}/wellness.json + {fits}
---
"""
    with open(ADJUSTMENTS, "a", encoding="utf-8") as f:
        f.write(entry)


def _append_to_section(header: str, ensure_block: str | None, rows_text: str) -> None:
    """Insert `rows_text` at the END of the section that starts with `header`.

    The "end of the section" is just before the next `^## ` header (or EOF).
    This is the fix for the bug where every helper appended at the end of
    the file, causing RPE and activity rows to accidentally land inside
    the Bitácora corporal section (the last section in the file).

    Behavior:
    - If the section header is missing AND `ensure_block` is provided, the
      block is appended to the end of the file plus the new rows. Use this
      when first-creating a section.
    - If the section header is missing AND `ensure_block` is None, this
      function is a no-op (caller asked to append into a section that
      doesn't exist, no action taken).
    """
    if not LEDGER.exists():
        return
    text = LEDGER.read_text(encoding="utf-8")
    if header not in text:
        if ensure_block is None:
            return
        with open(LEDGER, "a", encoding="utf-8") as f:
            f.write(ensure_block)
            f.write(rows_text)
            if not rows_text.endswith("\n"):
                f.write("\n")
        return

    header_pos = text.find(header)
    after_header = header_pos + len(header)
    next_header = re.search(r"\n## ", text[after_header:])
    section_end = after_header + next_header.start() if next_header else len(text)

    before = text[:section_end].rstrip("\n")
    after_text = text[section_end:]
    rows_clean = rows_text.rstrip("\n")

    new_text = before + "\n" + rows_clean + "\n"
    if after_text:
        new_text += "\n" + after_text.lstrip("\n")

    LEDGER.write_text(new_text, encoding="utf-8")


def append_ledger_rows(target: date) -> None:
    """Append a row to executed_volume.md for each activity of the day.

    Each row goes into the ISO-week section of `target` (e.g. `## 2026-W18`).
    If the week section doesn't exist yet, it gets created at the end of
    the file with the canonical header + table header.
    """
    paths = list_today_activities(target)
    if not paths:
        return
    if not LEDGER.exists():
        return
    iso = target.isoformat()
    iso_year, iso_week, _ = target.isocalendar()
    week_header = f"## {iso_year}-W{iso_week:02d}"

    monday = target - timedelta(days=target.isoweekday() - 1)
    sunday = monday + timedelta(days=6)

    lines: list[str] = []
    lines.append(f"<!-- feedback_session.py: append for {iso} at "
                 f"{datetime.utcnow().isoformat()}Z -->")
    for p in paths:
        try:
            a = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        sport = (a.get("activityType") or {}).get("typeKey") or ""
        dur = a.get("duration") or 0
        dist = a.get("distance") or 0
        avg_hr = a.get("averageHR")
        max_hr = a.get("maxHR")
        h, rem = divmod(int(dur), 3600)
        m, _ = divmod(rem, 60)
        dur_s = f"{h}h{m:02d}m" if h else f"{m}m"
        dist_s = f"{dist/1000:.2f} km" if dist else "—"
        hr_s = f"{int(avg_hr)} / {int(max_hr) if max_hr else '—'}" if avg_hr else "— / —"
        lines.append(
            f"| {iso} | {sport} | {dur_s} | {dist_s} | {hr_s} | _agregado por feedback_session_ |"
        )

    rows_text = "\n".join(lines)
    ensure_block = (
        f"\n\n{week_header} ({monday.strftime('%d/%m')} → {sunday.strftime('%d/%m')})\n\n"
        f"| Fecha | Modalidad | Duración | Distancia | FC media / max | Notas |\n"
        f"|---|---|---:|---:|---:|---|\n"
    )
    _append_to_section(week_header, ensure_block, rows_text)


def append_rpe_row(target: date, sections: dict) -> None:
    """Append a row to the 'RPE por día' table in executed_volume.md.

    Always lands inside the RPE section, regardless of which sections come
    after it in the file.
    """
    if not LEDGER.exists():
        return
    iso = target.isoformat()
    rpe = (sections.get("rpe") or "—").strip() or "—"
    note = (sections.get("comentarios") or "").splitlines()
    note_one = (note[0] if note else "").strip()[:80]

    ensure_block = (
        "\n\n---\n\n" + LEDGER_RPE_HEADER + "\n\n"
        "> RPE = esfuerzo percibido global de la sesión, escala 1-10\n"
        "> (1 = paseo, 5 = moderado, 8 = duro, 10 = al límite). Cargado por\n"
        "> `feedback_session.py` post-sesión.\n\n"
        "| Fecha | RPE | Notas |\n"
        "|---|---:|---|\n"
    )
    rows_text = f"| {iso} | {rpe} | {note_one} |"
    _append_to_section(LEDGER_RPE_HEADER, ensure_block, rows_text)


def append_body_issue_rows(target: date, issues: list[dict]) -> None:
    """Append one row per body issue to 'Bitácora corporal' in
    executed_volume.md. Always lands inside the Bitácora section.
    """
    if not LEDGER.exists() or not issues:
        return
    iso = target.isoformat()

    ensure_block = (
        "\n\n---\n\n" + LEDGER_BITACORA_HEADER + "\n\n"
        "> Append-only. Cada observación de carga / molestia / lesión va en una\n"
        "> fila nueva. Para cerrar una molestia, agregá fila con `estado=resolved`.\n"
        "> Para reportar empeoramiento, fila nueva con severidad mayor. La parte\n"
        "> es texto libre — escribí lo que tenga sentido (e.g. `tibial der`,\n"
        "> `hombro izq`, `cuádriceps`, `lumbar`).\n\n"
        "| Fecha | Parte | Severidad | Estado | Notas |\n"
        "|---|---|---:|---|---|\n"
    )
    rows = []
    for iss in issues:
        parte = (iss.get("parte") or "").strip().replace("|", "/")
        sev = (str(iss.get("severidad") or "")).strip() or "—"
        estado = (iss.get("estado") or "open").strip().lower()
        notas = (iss.get("notas") or "").strip().replace("|", "/")[:120]
        rows.append(f"| {iso} | {parte} | {sev} | {estado} | {notas} |")
    rows_text = "\n".join(rows)
    _append_to_section(LEDGER_BITACORA_HEADER, ensure_block, rows_text)


def read_bitacora_rows() -> list[dict]:
    """Devuelve TODAS las filas de la 'Bitácora corporal' como lista de dicts.

    Sirve para que el coach (o el script) sepa cuáles partes están
    actualmente abiertas (=última fila por parte con estado=open) y cuáles
    se resolvieron y cuándo.
    """
    if not LEDGER.exists():
        return []
    text = LEDGER.read_text(encoding="utf-8")
    if LEDGER_BITACORA_HEADER not in text:
        return []
    # buscar solo filas que vengan después del header
    start = text.index(LEDGER_BITACORA_HEADER)
    sub = text[start:]
    rows = []
    for m in LEDGER_BITACORA_ROW_RE.finditer(sub):
        rows.append({
            "fecha": m.group("fecha"),
            "parte": m.group("parte").strip(),
            "severidad": m.group("sev"),
            "estado": m.group("estado").lower(),
            "notas": m.group("notas").strip(),
        })
    return rows


def current_open_body_issues() -> list[dict]:
    """Para cada parte presente en la bitácora, devuelve la última observación
    cronológica solo si su estado es `open`. Es la 'foto' del estado actual
    del cuerpo del atleta."""
    rows = read_bitacora_rows()
    if not rows:
        return []
    # ordenar cronológicamente; si hay empate de fecha, la última en el
    # archivo gana (suficiente como heurística — el script no agrega
    # múltiples filas para la misma parte el mismo día sin querer).
    by_part: dict[str, dict] = {}
    for r in rows:
        key = r["parte"].lower()
        prev = by_part.get(key)
        if prev is None or r["fecha"] >= prev["fecha"]:
            by_part[key] = r
    return [r for r in by_part.values() if r["estado"] == "open"]
