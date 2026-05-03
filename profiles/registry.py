"""Registry: descubre perfiles disponibles y carga el activo.

Convención: cada subdirectorio de `profiles/` con un `profile.yml` adentro es
un perfil válido. El usuario elige cuál está activo poniendo el nombre en
`COACH_PROFILE` dentro de `profile.yml` (en el root del proyecto), o como
variable de entorno como override puntual.

Orden de precedencia para elegir el perfil activo:
    1. Variable de entorno COACH_PROFILE (override puntual / CI / tests)
    2. Key `coach_profile` en el `profile.yml` del root del proyecto
    3. "wellness" como default genérico (siempre disponible).
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from .base import FileBackedProfile

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROFILES_DIR = Path(__file__).resolve().parent
ROOT_PROFILE_YML = PROJECT_ROOT / "profile.yml"
DEFAULT_PROFILE = "wellness"


def list_profiles() -> list[str]:
    """Names of all profiles discoverable under profiles/."""
    out: list[str] = []
    for child in sorted(PROFILES_DIR.iterdir()):
        if child.is_dir() and (child / "profile.yml").exists():
            out.append(child.name)
    return out


def _resolve_active_profile_name() -> str:
    env = os.getenv("COACH_PROFILE")
    if env:
        return env.strip()
    if ROOT_PROFILE_YML.exists():
        data = yaml.safe_load(ROOT_PROFILE_YML.read_text(encoding="utf-8")) or {}
        name = data.get("coach_profile")
        if name:
            return str(name).strip()
    return DEFAULT_PROFILE


def load_active_profile() -> FileBackedProfile:
    """Load the profile chosen by the user (or DEFAULT_PROFILE)."""
    name = _resolve_active_profile_name()
    profile_dir = PROFILES_DIR / name
    if not profile_dir.exists():
        available = ", ".join(list_profiles()) or "(none discovered)"
        raise ValueError(
            f"Coach profile {name!r} not found in profiles/. "
            f"Available: {available}"
        )
    return FileBackedProfile(profile_dir=profile_dir)
