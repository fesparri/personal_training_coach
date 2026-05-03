"""
plan_session.py — programar el entrenamiento del día (PRE-sesión).

Flujo:
    1. (opcional) sync de Garmin para tener wellness fresco del día.
    2. Mostrar wellness markers del día.
    3. Mostrar la fila de master_plan.md correspondiente a la fecha.
    4. Mostrar contexto reciente: últimas 3 sesiones + alarmas abiertas.
    5. Preguntas (3, una por una, verbatim):
        - Plan original
        - Plan modificado (pre-sesión) — o "sin modificación"
        - Razón del ajuste
    6. Escribir `data/<fecha>/session.md` con esas 3 secciones llenas y
       Sección 4-6 marcadas como "[pendiente — completar con
       feedback_session.py]". El bloque de wellness se autogenera.

Salida: el archivo session.md queda parcialmente lleno. Después del
entrenamiento, correr `feedback_session.py` para completar el resto.

Usage:
    python scripts/plan_session.py                  # hoy
    python scripts/plan_session.py --date 2026-05-02
    python scripts/plan_session.py --no-sync        # sin tocar Garmin
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

# scripts/ está en sys.path cuando lo corrés con `python scripts/plan_session.py`,
# pero lo aseguramos para que `_session_lib` se resuelva en cualquier caso.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _session_lib import (  # noqa: E402
    PENDING_FEEDBACK,
    PROJECT_ROOT,
    append_plan_adjustment,
    find_master_plan_target,
    parse_session_md,
    print_recent_context,
    print_wellness,
    prompt_section,
    run_sync,
    session_md_path,
    write_session_md,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Programar el entrenamiento del día (pre-sesión).",
    )
    p.add_argument("--date", type=str, default=None,
                   help="ISO date YYYY-MM-DD (default: hoy).")
    p.add_argument("--no-sync", action="store_true",
                   help="No sincronizar Garmin antes de mostrar wellness.")
    p.add_argument("--no-adjust-log", action="store_true",
                   help="No appendear entry preliminar a plan_adjustments.md.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    target = date.fromisoformat(args.date) if args.date else date.today()
    iso = target.isoformat()

    # 1. sync (solo el día — wellness es lo único relevante pre-sesión)
    if not args.no_sync:
        rc = run_sync(target, also_yesterday=False)
        if rc != 0:
            print(f"\n[sync] garmin_sync.py exited with code {rc}.")
            print("Continuando con datos locales si existen.")

    # 2-4. read-only display
    print_wellness(target)

    print(f"\n=== Plan del día — master_plan.md ===")
    target_row = find_master_plan_target(target)
    if target_row:
        print(f"  {target_row}")
    else:
        print(f"  _no se encontró fila para {iso} en master_plan.md_")

    print_recent_context(target)

    # 5. interactive 3-question loop (Q1-Q3)
    print("\n=== Loop pre-sesión (3 preguntas) ===")

    # Si ya existe session.md (re-run), leer lo que haya y permitir
    # sobreescribir respondiendo de nuevo.
    existing = parse_session_md(target)
    if existing:
        print(f"\n  ⚠️  Ya existe `data/{iso}/session.md` con datos. Las preguntas")
        print("     que respondas ahora SOBREESCRIBEN sólo las secciones 1-3.")
        print("     Las secciones de feedback (4-6) se mantienen.")

    sections = dict(existing)  # start from whatever already exists

    sections["plan_original"] = prompt_section(
        "1/3  Plan original",
        "Pegá el plan ORIGINAL del día (lo que estaba programado en master_plan.md "
        "antes de cualquier ajuste).",
        multiline_hint="se admite multilínea",
    )
    print("✅ Sección 1 guardada.")

    sections["plan_modificado"] = prompt_section(
        "2/3  Plan modificado (pre-sesión)",
        "Pegá el plan MODIFICADO antes de ejecutar (la versión final con la que "
        "vas a arrancar). Si no hay modificación, escribí 'sin modificación'.",
    )
    print("✅ Sección 2 guardada.")

    sections["razon_ajuste"] = prompt_section(
        "3/3  Razón del ajuste pre-sesión",
        "Si modificaste, ¿cuál fue la razón? (wellness, dolor, contexto, etc.). "
        "Vacío si no hubo modificación.",
    )
    print("✅ Sección 3 guardada.")

    # 6. preserve / mark pending the post-session sections
    for k in ("ejecutado", "desviaciones", "comentarios"):
        if not sections.get(k):
            sections[k] = PENDING_FEEDBACK

    out = write_session_md(target, sections)
    print(f"\n✅ session.md (parcial) escrito: {out.relative_to(PROJECT_ROOT)}")
    print("   Secciones 4-6 quedan pendientes — corré "
          "`python scripts/feedback_session.py` después del entrenamiento.")

    if not args.no_adjust_log:
        # Optional: append a preliminary plan_adjustments entry. We skip
        # it here by default — the canonical entry should be written by
        # feedback_session.py when the executed/desviaciones data is real.
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
