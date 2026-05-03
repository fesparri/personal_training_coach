"""Dashboard generator: lee data/ + executed_volume.md + plan_adjustments.md +
profile.yml, computa el estado actual, alertas y trends, y genera un
`dashboard.html` autocontenido en el root del proyecto.

Uso:
    python scripts/build_dashboard.py
"""
from .build import build_dashboard

__all__ = ["build_dashboard"]
