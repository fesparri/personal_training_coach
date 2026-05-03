"""Interfaz y loader base para perfiles de coaching.

`CoachProfile` es un Protocol — cualquier objeto con esos atributos / métodos
satisface la interfaz, sin necesidad de heredar nada. La implementación
concreta `FileBackedProfile` carga todo del filesystem (3 archivos por perfil:
system_prompt.md, profile.yml, weekly_template.md).

Si en el futuro un perfil necesita lógica custom (e.g. thresholds calculados
dinámicamente desde wellness baseline), puede agregar un `profile.py` propio
que devuelva su propio objeto cumpliendo el Protocol — sin tocar este loader.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, TypedDict

import yaml


class AlertThresholds(TypedDict, total=False):
    """Umbrales que disparan que el coach proactivamente pregunte / ajuste plan.

    Todos opcionales — cada perfil define los que le importan. Las claves son
    canónicas del proyecto y los scripts que las consumen las leen por nombre.
    """

    hrv_drop_pct_vs_baseline: int      # % de caída de HRV vs avg 7d que dispara alarma
    sleep_below_hours: float           # horas de sueño por debajo de las que se alerta
    sleep_streak_below_days: int       # cuántos días seguidos antes de alarmar
    rhr_above_baseline_bpm: int        # bpm sobre baseline
    body_battery_morning_below: int    # BB al despertar por debajo del cual se alerta
    stress_avg_above: int              # avg stress level por encima del cual se alerta
    acwr_above: float                  # ratio carga aguda/crónica que dispara recovery
    body_issue_open_days_max: int      # días con body_issue open antes de re-preguntar
    rpe_chase_after_days: int          # días sin RPE cargado antes de pedirlo


class FeedbackCadence(TypedDict, total=False):
    """Cuándo el coach toma la iniciativa de preguntar."""

    after_each_session: bool           # post-sesión inmediato
    weekly_review_weekday: str         # ej. "sunday"
    proactive_recovery_check: bool     # preguntar recovery cuando wellness cae


class CoachProfile(Protocol):
    """Interfaz que cada perfil de coaching cumple."""

    name: str
    description: str
    profile_dir: Path

    def system_prompt(self) -> str: ...
    def metrics_to_watch(self) -> list[str]: ...
    def alert_thresholds(self) -> AlertThresholds: ...
    def feedback_cadence(self) -> FeedbackCadence: ...
    def weekly_template(self) -> str: ...


class FileBackedProfile:
    """Implementación concreta que carga todo del filesystem.

    Estructura esperada en `profile_dir`:
        profile_dir/
            system_prompt.md
            profile.yml         (con keys: name, description,
                                 metrics_to_watch, alert_thresholds,
                                 feedback_cadence)
            weekly_template.md
    """

    def __init__(self, profile_dir: Path):
        self.profile_dir = profile_dir
        meta_path = profile_dir / "profile.yml"
        if not meta_path.exists():
            raise FileNotFoundError(
                f"profile.yml not found at {meta_path}. "
                f"Each profile directory must contain profile.yml with at "
                f"least `name` and `description` keys."
            )
        meta = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
        self.name: str = meta.get("name") or profile_dir.name
        self.description: str = meta.get("description", "")
        self._metrics: list[str] = list(meta.get("metrics_to_watch") or [])
        self._thresholds: AlertThresholds = dict(meta.get("alert_thresholds") or {})
        self._cadence: FeedbackCadence = dict(meta.get("feedback_cadence") or {})

    def system_prompt(self) -> str:
        p = self.profile_dir / "system_prompt.md"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def metrics_to_watch(self) -> list[str]:
        return list(self._metrics)

    def alert_thresholds(self) -> AlertThresholds:
        return dict(self._thresholds)

    def feedback_cadence(self) -> FeedbackCadence:
        return dict(self._cadence)

    def weekly_template(self) -> str:
        p = self.profile_dir / "weekly_template.md"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def __repr__(self) -> str:
        return f"<FileBackedProfile name={self.name!r} dir={self.profile_dir}>"
