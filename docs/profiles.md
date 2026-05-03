# Perfiles de coaching

Un **perfil** define qué tipo de coach sos. Define la persona, las
métricas que prioriza, los umbrales que disparan alertas, y el formato
de salida cuando propone una sesión. El resto del proyecto (sync de
Garmin, helpers de parsing, dashboard, schemas de los living docs) es
**agnóstico al perfil** — funciona igual en wellness, hyrox o
hipertrofia.

El perfil activo se elige con la key `coach_profile` en `profile.yml`
(en el root del proyecto). Default si falta: `wellness`.

---

## Perfiles incluidos

| Perfil | Descripción | Estado |
|---|---|---|
| `wellness` | Generalista: sueño, recovery, stress, hábitos, movimiento de base. Default cuando no hay `profile.yml`. | **Completo** (system prompt detallado, umbrales, semana tipo) |
| `hyrox` | Específico Hyrox (Open / Doubles / Singles / Pro). Foco en simulacros encadenados, sled bajo fatiga, pace de competencia. | **Completo** |
| `half_marathon` | Media maratón. Estructura clásica E/M/T/I/R, ACWR conservador. | Stub mínimo — extendelo con tu plan |
| `triathlon` | Triatlón (sprint / olímpico / 70.3 / Ironman). 3 disciplinas + bricks. | Stub mínimo — confirmá distancia objetivo |
| `hypertrophy` | Hipertrofia general. Volumen progresivo por grupo, RIR controlado, deload cíclico. | Stub mínimo — definí tu split |

Los stubs están listos para usar pero deliberadamente cortos —
extenderlos es trivial (sumar reglas al `system_prompt.md`,
ajustar `alert_thresholds`).

---

## Anatomía de un perfil

Cada perfil vive en `profiles/<name>/` con tres archivos:

```
profiles/<name>/
├── system_prompt.md     # persona + métricas + formato de salida
├── profile.yml          # metadatos (name, description, métricas, umbrales, cadencia)
└── weekly_template.md   # plantilla de semana tipo
```

### `profile.yml`

Metadatos estructurados que el loader lee y expone vía la API
`CoachProfile`. Ejemplo (`profiles/hyrox/profile.yml`):

```yaml
name: hyrox
description: >
  Coach específico para Hyrox (Open Doubles / Singles / Pro). Foco en
  simulacros encadenados, pace de competencia, sled bajo fatiga.

metrics_to_watch:
  - sleep_score
  - hrv_avg
  - rhr
  - acwr
  - hr_zones_distribution_z1_z5
  - weekly_volume_run
  - weekly_volume_sled
  # ... etc

alert_thresholds:
  hrv_drop_pct_vs_baseline: 20      # % de caída de HRV vs avg 7d
  sleep_below_hours: 6.0
  sleep_streak_below_days: 2
  rhr_above_baseline_bpm: 7
  body_battery_morning_below: 30
  acwr_above: 1.5                   # ratio aguda/crónica que dispara alarma
  body_issue_open_days_max: 7       # días con body_issue open antes de re-preguntar
  rpe_chase_after_days: 3

feedback_cadence:
  after_each_session: true          # post-sesión inmediato
  weekly_review_weekday: sunday
  proactive_recovery_check: true
```

### `system_prompt.md`

El prompt que Claude Code lee como complemento al `CLAUDE.md`
universal. Define:

- **Persona y tono** — wellness es cálido y preguntón; hyrox es
  empujador y directo; hypertrophy es firme con técnica.
- **Métricas que priorizás** en la lectura del estado.
- **Triggers proactivos** específicos del deporte (sumados a los
  universales del CLAUDE.md §3).
- **Formato obligatorio de salida** cuando proponés una sesión (cambia
  bastante entre perfiles — la salida hyrox tiene "FC objetivo +
  alarmas", la de hipertrofia tiene "tabla de ejercicios con RIR
  target").
- **Reglas de seguridad y carga** específicas (qué cuidar, cuándo
  bajar intensidad).
- **Modos típicos de uso** — qué responde el coach según el mensaje
  del atleta.

Como referencia, el system prompt de wellness tiene ~5 KB; el de
hyrox ~7.7 KB; los stubs ~2 KB.

### `weekly_template.md`

Plantilla de semana tipo en markdown (no se parsea — es referencia
para que el atleta arme su `master_plan.md`). Ejemplo: hyrox propone
Lun fuerza inferior + skill, Mar Hybrid Engine, Mié recovery + tren
superior, Jue specific Hyrox, Vie fuerza superior, Sáb sled, Dom off.

---

## Cómo el coach usa el perfil

El bootstrap del CLAUDE.md §0.1 hace estos tres pasos al primer "hola":

1. **Carga el perfil** vía `profiles.registry.load_active_profile()`.
   Devuelve un `CoachProfile` con todos los metadatos del `profile.yml`
   parseados.
2. **Lee el system prompt** del perfil
   (`profiles/<active>/system_prompt.md`) y lo aplica como complemento
   a las reglas universales del CLAUDE.md.
3. **Lee los datos del atleta** del `profile.yml` del root
   (`athlete.name`, `physio.lthr_bpm`, etc.) para parametrizar zonas
   HR y restricciones iniciales.

Después de eso, los thresholds del perfil se usan en:

- **Triggers proactivos del coach** (CLAUDE.md §3): si HRV cae
  > `hrv_drop_pct_vs_baseline`, el coach pregunta. Si RPE no fue
  cargado en `rpe_chase_after_days` días, lo pide. Etc.
- **Alertas del dashboard**: el `dashboard/build.py` lee los mismos
  thresholds y genera tarjetas rojas/amarillas en
  `dashboard.html`.

---

## Cómo agregar un perfil nuevo

```bash
mkdir profiles/mi_objetivo/
```

Y dentro creás los tres archivos.

### Mínimo viable (`profile.yml`)

```yaml
name: mi_objetivo
description: >
  Coach para <descripción de tu objetivo>.

metrics_to_watch:
  - sleep_score
  - hrv_avg
  - rhr

alert_thresholds:
  hrv_drop_pct_vs_baseline: 20
  sleep_below_hours: 7.0

feedback_cadence:
  after_each_session: true
```

### `system_prompt.md` mínimo

```markdown
# Mi Objetivo Coach — instrucciones específicas del perfil

> Este archivo extiende `CLAUDE.md` (universal) con lo específico del
> perfil **mi_objetivo**.

## Persona

Sos un coach de <objetivo>. Tu foco es <una línea>. Hablás español
rioplatense.

## Métricas que vigilás

- Métrica 1
- Métrica 2

## Salida obligatoria al proponer una sesión

[formato]
```

### `weekly_template.md` mínimo

```markdown
# Plantilla semana tipo — Mi Objetivo

| Día | Sesión | Notas |
|-----|--------|-------|
| Lun | ... | ... |
```

### Activarlo

Editá `profile.yml` del root:

```yaml
coach_profile: mi_objetivo
```

Y verificá que cargue:

```bash
.venv/bin/python -c "from profiles.registry import load_active_profile; p = load_active_profile(); print(p.name, p.metrics_to_watch())"
```

---

## API Python

Si querés interactuar con perfiles desde código:

```python
from profiles.registry import load_active_profile, list_profiles

# Lista de perfiles disponibles
print(list_profiles())
# ['half_marathon', 'hypertrophy', 'hyrox', 'triathlon', 'wellness']

# Cargar el perfil activo (según profile.yml o env COACH_PROFILE)
p = load_active_profile()
print(p.name)                    # 'hyrox'
print(p.system_prompt())          # contenido de system_prompt.md
print(p.metrics_to_watch())       # ['sleep_score', 'hrv_avg', ...]
print(p.alert_thresholds())       # {'hrv_drop_pct_vs_baseline': 20, ...}
print(p.feedback_cadence())       # {'after_each_session': True, ...}
print(p.weekly_template())        # contenido de weekly_template.md
```

El `Protocol` `CoachProfile` está en `profiles/base.py`. Si necesitás
una implementación custom (ej. thresholds calculados dinámicamente
desde wellness baseline), creá una clase nueva que cumpla el protocolo.

---

## Filosofía

- **Datos primero, opinión después.** Las decisiones del coach se
  basan en métricas medidas, no en intuición. Los umbrales del perfil
  hacen explícito qué métrica + qué valor disparan qué reacción.
- **Append-only en el log.** El historial es sagrado. Cuando cambiás
  de perfil (hyrox → hipertrofia), el `executed_volume.md` y la
  bitácora corporal siguen creciendo — el coach del nuevo perfil lee
  todo el pasado para entender de dónde venís.
- **Scaffolding mínimo.** Cada perfil empieza tan corto como sea útil.
  Mejor un stub de 30 líneas que un mega-prompt copiado de internet.
  Lo extendés a medida que aprendés qué te sirve.
