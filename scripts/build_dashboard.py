"""build_dashboard.py — CLI entry point para regenerar `dashboard.html`.

Lee data/, executed_volume.md, plan_adjustments.md y profile.yml; computa
estado actual, alertas según los umbrales del perfil activo, tendencias
de wellness, volumen semanal por modalidad, ACWR y zonas HR; renderiza
todo en un único `dashboard.html` autocontenido en el root del proyecto.

El HTML resultante embebe Chart.js inline desde
`dashboard/vendor/chart.umd.min.js`, así que abre con doble click sin
servidor ni internet.

Usage:
    python scripts/build_dashboard.py
    python scripts/build_dashboard.py --out path/al/output.html
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.build import build_dashboard, OUTPUT_PATH  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate the local dashboard HTML.")
    p.add_argument("--out", type=str, default=None,
                   help=f"Output HTML path (default: {OUTPUT_PATH.relative_to(PROJECT_ROOT)})")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    out = Path(args.out) if args.out else OUTPUT_PATH
    target = build_dashboard(out_path=out)
    size_kb = target.stat().st_size / 1024
    print(f"✓ wrote {target.relative_to(PROJECT_ROOT)} ({size_kb:.1f} KB)")
    print(f"  Open with: open {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
