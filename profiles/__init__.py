"""Perfiles de coaching.

Cada perfil vive en `profiles/<name>/` y se compone de tres archivos:

- `system_prompt.md` — instrucciones específicas del coach para este objetivo.
- `profile.yml`     — metadatos: name, description, metrics_to_watch,
                       alert_thresholds, feedback_cadence.
- `weekly_template.md` — distribución semanal tipo (referencia para armar
                          master_plan.md).

El perfil activo se elige con `COACH_PROFILE` en `profile.yml` del root.
Ver `profiles/registry.py` para el loader.
"""

from .base import CoachProfile, FileBackedProfile, AlertThresholds, FeedbackCadence
from .registry import load_active_profile, list_profiles

__all__ = [
    "CoachProfile",
    "FileBackedProfile",
    "AlertThresholds",
    "FeedbackCadence",
    "load_active_profile",
    "list_profiles",
]
