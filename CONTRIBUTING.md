# Contribuir a Personal Coach

¡Gracias por interesarte en contribuir!

## Setup local

Requiere Python 3.11+.

```bash
git clone <repo-url>
cd personal-coach

python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .

# Configurar credenciales
cp .env.example .env
# Editá .env y completá GARMIN_EMAIL / GARMIN_PASSWORD

# Inicializar tus living docs personales a partir de los templates
cp templates/master_plan.md master_plan.md
cp templates/executed_volume.md executed_volume.md
cp templates/plan_adjustments.md plan_adjustments.md

# Bootstrap Garmin (una sola vez)
python scripts/garmin_auth_bootstrap.py
```

## Cómo organizamos los archivos

- `scripts/` — scripts ejecutables (sync Garmin, parse FIT, weekly summary,
  fallback CLI de plan/feedback).
- `templates/` — versiones genéricas de los living docs. Cada usuario las
  copia al root y las personaliza. **Los archivos personales del root están
  gitignored.**
- `docs/` — documentación técnica (schemas, perfiles, arquitectura).
- `data/`, `reports/` — gitignored. Generados localmente por los scripts.

## Estilo de código

- Python: type hints donde aporten, docstrings cortas, sin sobre-comentar.
- Mantené los scripts **idempotentes** (re-correrlos no debe duplicar datos).
- No agregues dependencias sin discutirlo en un issue primero — el proyecto
  busca mantener una huella mínima para que sea fácil de levantar.

## Issues y PRs

- Para bugs: incluí versión de Python, comando que corriste, y el output
  completo (sin secretos).
- Para features: abrí un issue antes de un PR grande para alinear scope.
- Idioma: español o inglés, los dos están OK. Los `.md` públicos del repo
  están en castellano.

## Privacidad

- **Nunca** commitees `.env`, `data/`, `reports/`, `docs/seed_history/`, ni
  los living docs personales del root (`master_plan.md`,
  `executed_volume.md`, `plan_adjustments.md`).
- El `.gitignore` ya cubre todo eso — si tocás esa lista, asegurate de no
  abrir un agujero.
- Si un PR tuyo incluye datos reales de Garmin de ejemplo, anonimizalos
  antes de subirlo.
