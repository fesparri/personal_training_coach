"""
feedback_session.py — feedback del entrenamiento ya ejecutado (POST-sesión).

Flujo:
    1. Sync Garmin (default: ayer + hoy) para bajar las actividades recién
       hechas + sus .fit.
    2. Mostrar las actividades descargadas para la fecha objetivo + feedback
       cuantitativo (duración, distancia, pace, FC media/max, distribución
       Z1-Z5 desde el .fit).
    3. Preguntas (3, una por una, verbatim):
        - Sesión ejecutada (qué hiciste realmente)
        - Desviaciones durante la ejecución (acortar, saltar, cambiar pesos)
        - Comentarios del atleta (sensaciones, dolor, fatiga, contexto)
    4. Actualizar `data/<fecha>/session.md` con esas 3 secciones llenas
       (manteniendo Plan original / Modificado / Razón si plan_session.py
       ya las escribió).
    5. Append la entry final a `plan_adjustments.md`.
    6. Append filas a `executed_volume.md` (una por actividad del día).

Si `session.md` no existe (e.g. no corriste plan_session.py), las 3
secciones de plan también se piden, así el flujo igual funciona como
"todo en uno post-sesión".

Usage:
    python scripts/feedback_session.py                  # hoy
    python scripts/feedback_session.py --date 2026-05-02
    python scripts/feedback_session.py --no-sync        # usar datos locales
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _session_lib import (  # noqa: E402
    ADJUSTMENTS,
    LEDGER,
    PENDING_FEEDBACK,
    PROJECT_ROOT,
    append_body_issue_rows,
    append_ledger_rows,
    append_plan_adjustment,
    append_rpe_row,
    parse_session_md,
    print_performance_feedback,
    print_wellness,
    prompt_body_issues_loop,
    prompt_int_0_10,
    prompt_section,
    run_sync,
    session_md_path,
    write_session_md,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Feedback del entrenamiento del día (post-sesión).",
    )
    p.add_argument("--date", type=str, default=None,
                   help="ISO date YYYY-MM-DD (default: hoy).")
    p.add_argument("--no-sync", action="store_true",
                   help="No sincronizar Garmin (usar datos locales).")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    target = date.fromisoformat(args.date) if args.date else date.today()
    iso = target.isoformat()

    # 1. sync (ayer + hoy: por las dudas se cargó la sesión a otro día)
    if not args.no_sync:
        rc = run_sync(target, also_yesterday=True)
        if rc != 0:
            print(f"\n[sync] garmin_sync.py exited with code {rc}.")
            print("Continuando con datos locales si existen.")

    # 2. wellness + feedback cuantitativo
    print_wellness(target)
    print_performance_feedback(target)

    # 3. levantar lo que ya escribió plan_session.py (si corrió)
    existing = parse_session_md(target)
    if not existing:
        print(f"\n  ⚠️  No hay `data/{iso}/session.md` previo "
              "(no corriste plan_session.py).")
        print("     Voy a pedirte también las secciones de plan (1-3) además del feedback.")
    else:
        print(f"\n  ✓ Detecté `data/{iso}/session.md` con plan ya cargado.")

    sections = dict(existing)

    if not sections.get("plan_original"):
        sections["plan_original"] = prompt_section(
            "Plan original (no estaba en session.md)",
            "Pegá el plan ORIGINAL del día (de master_plan.md).",
            multiline_hint="se admite multilínea",
        )
        print("✅ Plan original guardado.")
    if not sections.get("plan_modificado"):
        sections["plan_modificado"] = prompt_section(
            "Plan modificado (no estaba en session.md)",
            "Pegá el plan MODIFICADO (o 'sin modificación').",
        )
        print("✅ Plan modificado guardado.")
    if not sections.get("razon_ajuste"):
        sections["razon_ajuste"] = prompt_section(
            "Razón del ajuste (no estaba en session.md)",
            "Si modificaste, ¿cuál fue la razón? Vacío si no aplica.",
        )
        print("✅ Razón guardada.")

    # 4. el loop de feedback propiamente dicho (Q4-Q6)
    print("\n=== Loop post-sesión (3 preguntas) ===")

    sections["ejecutado"] = prompt_section(
        "1/3  Sesión ejecutada",
        "Pegá lo que efectivamente EJECUTASTE. Si fue idéntico al plan modificado, "
        "escribí 'idéntico al plan modificado'.",
        multiline_hint="se admite multilínea",
    )
    print("✅ Sección 4 guardada.")

    sections["desviaciones"] = prompt_section(
        "2/3  Desviaciones durante la ejecución",
        "¿Hubo desviaciones durante la ejecución? (acortar, saltar, cambiar "
        "pesos, etc.). Vacío si no.",
    )
    print("✅ Sección 5 guardada.")

    sections["comentarios"] = prompt_section(
        "3/3  Comentarios del atleta",
        "Comentarios libres: sensaciones, dolor, fatiga, contexto del día.",
    )
    print("✅ Sección 6 guardada.")

    # 5. marcadores: RPE + bitácora corporal flexible
    print("\n=== Marcadores post-sesión ===")
    sections["rpe"] = prompt_int_0_10(
        "RPE (esfuerzo percibido global)",
        "¿Qué tan dura sentiste la sesión en total? "
        "(1 = paseo / 5 = moderada / 8 = duro / 10 = al límite).",
    )
    sections["body_issues"] = prompt_body_issues_loop(target)

    # limpio sentinels que pudieran quedar
    for k, v in list(sections.items()):
        if isinstance(v, str) and v == PENDING_FEEDBACK:
            sections[k] = ""

    # 6. persistencia
    out = write_session_md(target, sections)
    print(f"\n✅ session.md (completo) escrito: {out.relative_to(PROJECT_ROOT)}")

    append_plan_adjustment(target, sections)
    print(f"✅ entry agregada a {ADJUSTMENTS.relative_to(PROJECT_ROOT)}")

    append_ledger_rows(target)
    print(f"✅ filas (volumen) agregadas a {LEDGER.relative_to(PROJECT_ROOT)}")

    append_rpe_row(target, sections)
    if sections.get("body_issues"):
        append_body_issue_rows(target, sections["body_issues"])
        print(f"✅ RPE + bitácora corporal ({len(sections['body_issues'])} entradas) "
              f"agregadas a {LEDGER.relative_to(PROJECT_ROOT)}")
    else:
        print(f"✅ RPE agregado a {LEDGER.relative_to(PROJECT_ROOT)} "
              f"(sin entradas en bitácora corporal hoy)")

    print("\nListo. La conversación con Claude ahora puede leer:")
    print(f"  - data/{iso}/session.md")
    print("  - master_plan.md (sesión de mañana)")
    print("  - executed_volume.md (volumen acumulado)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
