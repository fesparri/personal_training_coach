# SCHEMA.md — Formato exacto de los archivos editables

> Esta es la referencia técnica de cómo están estructurados los `.md`
> editables del proyecto. **Léelo antes de escribir cualquiera de estos
> archivos a mano.** Los scripts (`plan_session.py`, `feedback_session.py`,
> y los helpers de `_session_lib.py`) ya generan el formato correcto;
> este archivo es para cuando el coach necesita leer / parsear / escribir
> manualmente sin romper nada.

> Si modificás un schema, actualizá este archivo + los regex y helpers
> en `scripts/_session_lib.py` que dependen de él.

---

## 1. `data/<fecha>/session.md`

Una `session.md` por día, escrita por `plan_session.py` (parcialmente)
y completada por `feedback_session.py`. Estructura fija de 10 secciones,
en este orden exacto:

```markdown
# Sesión YYYY-MM-DD

## Plan original

> Sesión tal como estaba en master_plan.md ANTES de cualquier modificación pre-sesión.

<contenido libre — verbatim del atleta>

## Plan modificado (pre-sesión)

> Sesión ajustada en función del wellness del día y/o eventos del calendario, ANTES de ejecutar.

<contenido libre — "sin modificación" si no hubo>

## Razón del ajuste pre-sesión

<contenido libre — "N/A" si Plan modificado = "sin modificación">

## Sesión ejecutada

> Lo que el atleta efectivamente realizó. Puede coincidir con "Plan modificado" o haber sufrido más cambios sobre la marcha.

<contenido libre — "idéntico al plan modificado" si no hubo cambios>

## Desviaciones durante la ejecución

<contenido libre — "ninguna" si no hubo>

## Comentarios del atleta

> Sensaciones, dolor, fatiga, contexto de vida que afecte la lectura de la sesión.

<contenido libre>

## Marcadores post-sesión

> RPE = esfuerzo percibido global de la sesión (0-10). Bitácora = una entrada por cada parte del cuerpo cargada/dolorida/lesionada o resuelta hoy. La lista completa con histórico vive en `executed_volume.md` → sección `Bitácora corporal`.

- RPE (esfuerzo percibido global): **N** /10

**Bitácora corporal de hoy:**
- <parte> · sev N/10 · <open|resolved> · <notas opcional>
- ...

## Wellness pre-sesión

- Sueño: score N, duración HhMMm
- HRV (anoche): avg N ms / max N ms (STATUS)
- RHR: N bpm
- Body Battery (rango día): N → N
- Estrés: avg N, max N

_Auto-populated from `data/YYYY-MM-DD/wellness.json`._

## Archivos .fit asociados

- `data/YYYY-MM-DD/activities/<id>.fit` — <name> · <sport> · <duración> · <distancia> · FC media N bpm
- ...

## Vínculo con master_plan.md y plan_adjustments.md

- **Master plan reference:** `<fila copiada de master_plan.md para esta fecha>`
- **Adjustment log entry:** Ver `plan_adjustments.md` — entry con `Date: YYYY-MM-DD`.
```

### Reglas

- **Headers son exactos.** No los cambies (`_session_lib.SECTION_HEADERS`
  los usa para parsear).
- **Bullets de bitácora** siguen el formato literal:
  `- <parte> · sev <N>/10 · <estado> · <notas>` (notas opcional).
  Regex: `_session_lib.ISSUE_BULLET_RE`.
- **RPE** se renderea como `**N** /10` con doble asterisco. Regex:
  `_session_lib.RPE_RE`.
- **Sentinel** `[pendiente — completar con feedback_session.py]` lo
  escribe `plan_session.py` en las secciones 4-6 cuando todavía no se
  entrenó. El parser ignora estos sentinels.
- Si no hay archivos .fit todavía, la sección dice `ninguno todavía`.

### Render canónico

Generado por `_session_lib.render_session_md(target, sections)`.
Parseado de vuelta por `_session_lib.parse_session_md(target)`.
Roundtrip estable.

---

## 2. `executed_volume.md`

Ledger durable del trabajo real. **Tres tablas + lectura coach.**
Append-only — nunca borrar entries pasadas.

### 2.1 Tabla por semana — actividades

Una sección por ISO-week:

```markdown
## YYYY-Www (DD/MM → DD/MM)

| Fecha | Modalidad | Duración | Distancia | FC media / max | Notas |
|---|---|---:|---:|---:|---|
| YYYY-MM-DD | <activityType.typeKey> | NhMMm | N.NN km / — | N / N | <texto libre> |
```

- **Modalidad** = `activityType.typeKey` de Garmin tal cual
  (`running`, `treadmill_running`, `indoor_rowing`, `indoor_cardio`,
  `strength_training`, `hiit`, `obstacle_run`, etc.).
- **Duración** = formato `NhMMm` (con horas) o `NNm` (sin horas).
- **Distancia** = `N.NN km` o `—`.
- **FC** = `<media> / <max>` o `— / —`.
- **Notas** = texto libre. Cuando lo escribe `feedback_session.py`,
  agrega `_agregado por feedback_session_`.

### 2.2 Volumen acumulado por modalidad

Tabla pivot al final de la última semana, **manualmente curada**
(no la auto-genera `feedback_session.py`):

```markdown
## Volumen acumulado por modalidad — últimos 14 días (DD/MM → DD/MM)

| Modalidad | Sesiones | Tiempo total | Distancia | FC media |
|---|---:|---:|---:|---:|
| running / treadmill | N | ~NhMMm | ~N.NN km | N bpm |
| ...

**Lectura coach:**
- <bullet 1>
- ...
```

Esta tabla **se actualiza periódicamente** (e.g. cada lunes al cerrar
la semana). El coach puede generarla con `weekly_summary.py` y pegarla
acá si se quiere ledger compacto.

### 2.3 RPE por día

```markdown
## RPE por día

> RPE = esfuerzo percibido global de la sesión, escala 1-10
> (1 = paseo, 5 = moderado, 8 = duro, 10 = al límite). Cargado por
> `feedback_session.py` post-sesión. Días anteriores a la
> instrumentación quedan sin RPE.

| Fecha | RPE | Notas |
|---|---:|---|
| YYYY-MM-DD | N | <texto libre / 1ra línea de comentarios> |
```

Una fila por día. Si no hay RPE cargado, la fila tiene `—` en RPE.

### 2.4 Bitácora corporal

```markdown
## Bitácora corporal

> Append-only. Cada observación de carga / molestia / lesión va en una
> fila nueva. Para cerrar una molestia, agregá fila con
> `estado=resolved`. Para reportar empeoramiento, fila nueva con
> severidad mayor. La parte es texto libre — escribí lo que tenga
> sentido (e.g. `tibial der`, `hombro izq`, `cuádriceps`, `lumbar`,
> `rodilla der`).

| Fecha | Parte | Severidad | Estado | Notas |
|---|---|---:|---|---|
| YYYY-MM-DD | <parte libre> | N | <open|resolved> | <texto libre> |
```

- **Parte** = texto libre. **No hay vocabulario controlado** — escribí
  lo que diga el atleta. Buenas prácticas: usar la misma cadena para la
  misma parte (e.g. siempre "tibial der", no mezclar "tibial derecho"
  / "tibiales derechos") para que `current_open_body_issues()` agrupe
  bien.
- **Severidad** = entero 0-10. 0 = ya no molesta. 10 = dolor agudo /
  lesión activa.
- **Estado** = `open` o `resolved`. Si severidad = 0 → casi siempre
  `resolved`. Si severidad ≥ 5 → casi siempre `open`. El default del
  prompt en `feedback_session.py` aplica esa lógica.
- **Notas** = texto libre 1 línea (≤ 120 chars). El pipe `|` se
  reemplaza por `/` automáticamente al insertar para no romper la
  tabla.

### Reglas globales

- **Append-only**. Nunca editás filas pasadas. Si te equivocaste, agregá
  una fila nueva que contradice/cierra la anterior.
- **Headers exactos** (`## RPE por día`, `## Bitácora corporal`) — los
  helpers buscan por nombre.
- **Encoding UTF-8** — todo el proyecto.

---

## 3. `plan_adjustments.md`

Append-only log de ajustes vs `master_plan.md`. Una entry por cada
modificación material.

### Formato de entry

```markdown
---
Date: YYYY-MM-DD
Original session: <one-liner del plan original — primera línea>
Modified to: <plan modificado — multilínea OK>
Executed as: <sesión ejecutada — multilínea OK>
Reason: <por qué se ajustó — wellness, dolor, calendario, etc.>
Source: <paths separados por ` + ` de los archivos que justifican la entry>
---
```

### Reglas

- **Append-only.** Nunca editar entries pasadas.
- Cada entry abre y cierra con `---` en su propia línea.
- Si una sesión salió tal cual el plan, **no se registra**. Solo se
  loggean ajustes (cambio de carga, modalidad, día, descanso forzado,
  truncamiento, etc.).
- "Source" debe ser path relativo al archivo que disparó el cambio,
  e.g. `data/2026-04-30/session.md + data/2026-04-30/wellness.json +
  data/2026-04-30/activities/22719154340.fit`.

### Generación automática

`feedback_session.py` agrega una entry al cierre de cada sesión usando
`_session_lib.append_plan_adjustment(target, sections)`. El coach
**no debe** escribir entries a mano salvo backfill histórico
documentado.

---

## 4. `master_plan.md`

Plan estructural — **se reescribe solo en revisiones formales de fase**.
Las modificaciones del día a día NO van acá; van a
`plan_adjustments.md`.

### Estructura

11 secciones numeradas:

1. Atleta (perfil, fisiología, dispositivos, restricciones)
2. Fases (F1 / F2 / F3 con foco, fechas, volumen estimado, métricas
   de éxito)
3. Distribución semanal tipo (UY / BA)
4. Pesos de competencia
5. Benchmarks actuales (declarados o medidos) + diagnóstico técnico
   SkiErg
6. Próximos hitos calendario
7. Plan diario — Fase 1 (tablas semanales con `Día | Fecha | Sesión |
   Detalle`)
8. Plan diario — Fase 2
9. Plan diario — Fase 3
10. Restricciones permanentes
11. Pendientes operativos

### Tablas diarias

Formato fijo (lo lee `_session_lib.find_master_plan_target(date)`):

```markdown
| Día | Fecha | Sesión | Detalle |
|---|---|---|---|
| Mar | 2026-04-28 | <título corto> | <descripción detallada con FC target / RIR / volumen> |
| ... |
```

El regex en `find_master_plan_target` matchea filas que empiezan con
`| <Día> | YYYY-MM-DD | ...`. Cualquier cosa que no calce con ese
patrón no será encontrada por el coach.

---

## 5. `data/<fecha>/wellness.json`

Generado por `garmin_sync.py`. **No editar a mano.** Estructura:

```json
{
  "date": "YYYY-MM-DD",
  "fetched_at": "YYYY-MM-DDTHH:MM:SS.NNNNNNZ",
  "sleep": { "dailySleepDTO": { ... } },
  "hrv": { "hrvSummary": { "lastNightAvg": N, "lastNight5MinHigh": N, "status": "..." }, ... },
  "resting_heart_rate": { "allMetrics": { "metricsMap": { "WELLNESS_RESTING_HEART_RATE": [...] } } },
  "body_battery": [ { "bodyBatteryValuesArray": [[ts, val], ...] } ],
  "stress": { "avgStressLevel": N, "maxStressLevel": N, ... }
}
```

Helpers para leerlo: `_session_lib.load_wellness(date)` y
`wellness_summary_fields(date)`.

---

## 6. `data/<fecha>/activities/<id>.json`

Garmin activity summary. No editar a mano. Campos clave:
`activityId`, `activityName`, `activityType.typeKey`, `duration`
(segundos), `distance` (metros), `averageHR`, `maxHR`,
`averageRunCadence`, `startTimeLocal`.

---

## 7. `data/<fecha>/activities/<id>.fit`

Raw Garmin FIT (binario). Parseable con `fitparse.FitFile`. Helper:
`_session_lib.parse_fit_zones(path)` devuelve dict
`{Z1, Z2, Z3, Z4, Z5}` con segundos por zona basados en LTHR=172.
Las zonas son:

| Zona | Rango bpm |
|---|---|
| Z1 | < 120 |
| Z2 | 120-134 |
| Z3 | 135-154 |
| Z4 | 155-171 |
| Z5 | ≥ 172 |

---

## 8. `blood_panel.md` (living doc, generado)

Living doc en root, **regenerado automáticamente** por
`_session_lib.refresh_blood_panel_md()`. **No editar a mano.** La
fuente es `data/manual/blood.xlsx` + `data/manual/blood_reference_ranges.yml`.

### Sección fija

```markdown
# Panel sanguíneo — historial e interpretación

> Generado por _session_lib.refresh_blood_panel_md() a partir de
> data/manual/blood.xlsx + data/manual/blood_reference_ranges.yml.
> ...
> Última regeneración: YYYY-MM-DDTHH:MM:SSZ
> Perfil activo: **<profile>** · extracciones totales: N

---

## Estado actual (al YYYY-MM-DD — última extracción)

**Resumen ejecutivo:** N markers medidos · M flag(s) dura(s) · K flag(s) blanda(s).

### 🔴 Flags duras
<lista o "_Sin flags duras en esta extracción._">

### 🟡 Flags blandas / contextuales
<lista o "_Sin flags blandas en esta extracción._">

### ✅ Estables / sin flag
<lista inline "marker = valor unidad, ..." de markers en rango normal>

---

## Por categoría — última extracción (YYYY-MM-DD)

### Hemograma
### Perfil ferroso
### Metabolismo glucémico
### Perfil lipídico
### Función hepática
### Función renal
### Endócrino
### Vitaminas
### Iones / electrolitos
### Otros markers medidos (sin interpretación configurada)

(cada categoría tiene una tabla:)
| Marker | Valor | Rango lab | Target atleta | Estado | Tendencia |

---

## Histórico completo — append-only

### Extracción YYYY-MM-DD
| Marker | Valor | Sheet |
...
```

### Reglas

- **Headers exactos** — el rendering los emite literal.
- **Categorías** vienen del campo `categoria:` en
  `blood_reference_ranges.yml`. Markers sin entrada en el YAML caen en
  "Otros markers medidos (sin interpretación configurada)".
- **`Estado`** ∈ {`bajo`, `borderline-bajo`, `normal`,
  `borderline-alto`, `alto`, `—`}.
- **`Tendencia`** ∈ {`→ estable`, `↑ subiendo`, `↓ bajando`,
  `↕ volatil`, `· sin_historia`} — calculada por `_compute_trend()`
  sobre los últimos ≤ 4 valores.
- **Rango lab** soporta lado abierto: `null` en cualquier extremo del
  `rango_lab` se renderiza como `≤ N` o `≥ N`.
- **Target atleta** es profile-aware: el rendering usa la banda del
  `coach_profile` activo, o el `default` del YAML si no hay match.

### Regeneración

```bash
python -c "import sys; sys.path.insert(0,'scripts'); \
           from _session_lib import refresh_blood_panel_md; refresh_blood_panel_md()"
```

Idempotente. La sección "Histórico completo" se reescribe entera cada
vez (la fuente de verdad es el Excel, no el `.md`). Si editás un valor
viejo en el Excel y regenerás, queda reflejado.

---

## 9. `body_composition.md` (living doc, generado)

Mismo patrón que §8 pero para antropometría. Generado por
`_session_lib.refresh_body_composition_md()` desde
`data/manual/anthropometry.xlsx`. **No editar a mano.**

### Sección fija

```markdown
# Composición corporal — historial e interpretación

> ...
> Última regeneración: ...
> Perfil activo: **<profile>** · evals totales: N

---

## Estado actual (al YYYY-MM-DD — última eval)

**Resumen ejecutivo:**
- **Peso (kg)** = N · <tendencia>
- **Masa Adiposa (%)** = N · <tendencia> (banda perfil <X>: lo–hi)
- **FFMI** = N · <tendencia> (banda perfil <X>: lo–hi)
- ... (resto de headline vars)

### 🔴 Flags duras
<lista o "_Sin flags duras en esta eval._">

### 🟡 Flags blandas
<lista o "_Sin flags blandas en esta eval._">

### Trayectoria headline (todas las evals)
| Variable | Trayectoria (más antigua → más reciente) |

---

## Por bloque — última eval (YYYY-MM-DD)

### Morfología global
### Índices de desarrollo
### Pliegues
### Sumatorias
### Perímetros
### Diámetros
### Masas corporales
### Distribución adiposa
### Somatotipo
### Áreas musculares
### Requerimiento energético
### Otros

(cada bloque tiene una tabla:)
| Variable | Valor | Estado | Target perfil | Tendencia |

---

## Histórico completo — append-only

### Eval YYYY-MM-DD
| Variable | Valor |
...
```

### Reglas

- **Bloques** derivan del prefijo del nombre de variable
  (`Pl.` → Pliegues, `Pr.` → Perímetros, `Diam.` → Diámetros,
  `Masa` → Masas corporales, etc.). Variables que no calzan caen en
  "Otros".
- **Targets por perfil** son hard-coded en `_session_lib._ANTHRO_TARGETS`
  (no hay YAML equivalente al de sangre — son heurísticas, no rangos
  clínicos). Currently configured: `Masa Adiposa (%)` y `FFMI`.
- **Detección de unit-bug:** `Masa Muscular (kg)` con valor > 200
  dispara una flag dura `unit_bug` y el punto se excluye del cómputo
  de tendencia. El valor crudo se preserva en el histórico.
- **Tendencia** y formato de tabla iguales que §8.

### Regeneración

```bash
python -c "import sys; sys.path.insert(0,'scripts'); \
           from _session_lib import refresh_body_composition_md; refresh_body_composition_md()"
```

---

## 10. `data/manual/blood_reference_ranges.yml`

Config de interpretación de panel sanguíneo. **Editable a mano** —
es conocimiento clínico, no PII. Versionado en el repo.

Por marcador (key = string **verbatim** de la columna en `blood.xlsx`):

```yaml
"<marker verbatim>":
  categoria: hemograma | ferroso | metabolico | lipidico | hepatico
             | renal | endocrino | vitaminas | iones
  unidad: "<string>"                 # informativo
  rango_lab: [low, high]              # null en cualquier extremo = lado abierto
  target_atleta:                      # opcional, profile-aware
    default: [low, high]
    <profile>: [low, high]
  trigger_si:                         # opcional, banderas duras (universales)
    - "valor [<|<=|>|>=] N → mensaje"
  relevancia: endurance | strength | recovery | recovery_neuromuscular
              | metabolico | cardio | renal | electrolitos | endocrino
  lectura_entrenamiento:              # opcional, una línea por estado
    en_rango: "..."
    bajo: "..."
    alto: "..."
```

Reglas:

- **Keys verbatim.** Si un marker tiene typos en el Excel (e.g.
  `'Vitamina B1  (nmol/L)'` con doble espacio), la key del YAML debe
  matchear letra por letra.
- **`rango_lab[null]`** marca lado abierto: el rendering produce
  `≤ N` o `≥ N` y el clasificador no genera flag/borderline en ese
  lado.
- **`trigger_si`** son banderas duras universales (mismo flag para
  cualquier perfil). El clasificador extrae el operador y el umbral
  con regex `valor (<|<=|>|>=) N`; cualquier rule que no calce con
  ese patrón se ignora.
- **`target_atleta`** son banderas blandas profile-aware. Precedencia:
  `<profile>` → `default` → no flag soft.

### Cargado por

`_session_lib._load_blood_reference_ranges()` lo lee en cada llamada a
`interpret_blood_panel()`. No hay caché — editás el YAML y la próxima
regeneración del `.md` lo refleja.

---

## 11. `data/manual/research/<slug>.md` (fuente, mantenido a mano)

Compendio de papers / estudios / reportes peer-reviewed. Un `.md` por
fuente. Cada archivo tiene **YAML frontmatter** al inicio + **cuerpo
libre** debajo. El living doc `research_evidence.md` se genera a partir
de estos archivos.

### Estructura del archivo

```markdown
---
id: <slug-en-kebab-case>
title: "<Título>"
authors:
  - "<Autor 1>"
  - "<Autor 2>"
year: 2024                              # int | null
source: "<Universidad / Lab / Institución>"
venue: "<Journal / Conferencia / SSAC Report / Preprint>"
doi: null                                # string | null
url: null                                # string | null
evidence_quality: peer_reviewed          # ver vocabulario abajo
topics:
  - <topic_1>
  - <topic_2>
profiles_relevant:
  - <perfil>                             # hyrox | wellness | half_marathon |
                                         # triathlon | hypertrophy | all
tldr: >-
  <1-3 frases con el aporte central.>
key_findings:
  - "<Finding numérico/empírico 1>"
  - "<Finding 2>"
training_implications:
  - "<Bullet 1 — cómo cambia la programación>"
  - "<Bullet 2>"
tags:
  - <tag_libre>
date_added: YYYY-MM-DD
---

# <Título>

<Cuerpo libre: notas, citas verbatim, tablas, gráficos, contexto. El
 coach lo lee solo cuando necesita profundizar más allá del frontmatter.>
```

### Vocabulario

**`evidence_quality`** (case-insensitive, en orden descendente de peso):

- `meta_analysis` — meta-análisis o systematic review formal.
- `systematic_review` — alias de `meta_analysis` para revisiones
  sistemáticas sin pooling cuantitativo.
- `peer_reviewed` — paper original peer-reviewed.
- `review` — revisión narrativa no sistemática.
- `preprint` — preprint sin peer review.
- `report` — reporte institucional (ej. SSAC).
- `expert_opinion` — opinión de experto / editorial.
- `case_study` — n=1 / case report.
- `n_of_1` — auto-experimento del atleta.
- `unspecified` — default cuando el campo falta.

**`topics`** (vocabulario sugerido, extensible — el coach matchea
case-insensitive):

```
performance, fatigue, recovery, strength, endurance, hypertrophy,
energy_systems, time_intensity, hybrid_training, female_athlete,
nutrition, sleep, hydration, hrv, vo2max, lactate, mobility,
injury_prevention, periodization, mental_skills, data_science,
acwr, deload, taper, race_strategy
```

**`profiles_relevant`** debe contener al menos uno de los perfiles
válidos del repo (`hyrox`, `wellness`, `half_marathon`, `triathlon`,
`hypertrophy`) o el wildcard `"all"`. Si la lista está vacía, el
loader la sustituye por `["all"]` (el paper aparece para todos).

### Reglas

- **`id` único.** Es el anchor de markdown en `research_evidence.md`
  (`#<id>`); si dos archivos tienen el mismo `id`, los links rompen.
  Default si falta: el filename sin extensión.
- **Frontmatter opcional, body siempre.** Un `.md` sin `---...---` al
  inicio igual se incorpora — sólo aparece sin metadata estructurada
  (defaults razonables). Útil para fuentes ad-hoc, pero perdés filtros
  por topic / perfil.
- **Cuerpo libre.** No hay schema sobre el body. Podés pegar el paper
  entero, citas, o solo notas propias.
- **`tldr` / `key_findings` / `training_implications` son lo que el
  coach surface.** Son los bullets que se renderean en
  `research_evidence.md`. Si los dejás vacíos, el paper aparece como
  "stub" — el coach no tiene takeaways que citar.
- **No editar `research_evidence.md` a mano.** Es generado.

### Cargado por

`_session_lib.load_research_papers()` parsea cada `.md`. El frontmatter
se lee con `yaml.safe_load` después de un regex que separa
`---\n...\n---\n` del cuerpo. `interpret_research()` agrupa por tema,
filtra por perfil y ordena por `year` desc. `refresh_research_evidence_md()`
serializa todo a `research_evidence.md`.

---

## 12. `research_evidence.md` (living doc, generado)

Vista compilada del compendio de research. **No editar a mano** —
regenerado por `_session_lib.refresh_research_evidence_md()` desde
todos los `.md` en `data/manual/research/`.

### Secciones fijas

1. **Estado actual** — resumen ejecutivo: total de papers, temas únicos,
   distribución por calidad de evidencia.
2. **Top takeaways para el perfil activo** — tabla con todas las
   `training_implications` de los papers cuyo `profiles_relevant`
   incluye el perfil activo o `"all"`. Cada fila linkea al card del
   paper.
3. **Índice por tema** — cada `topic` con la lista de papers que lo
   tocan (con tldr).
4. **Catálogo completo de papers** — un card por paper con metadata
   completa + tldr + key_findings + training_implications + link al
   archivo fuente.

### Reglas

- **Anchors** son `<id>` del frontmatter, lowercased + dashes (mismo
  esquema que GitHub-flavored markdown).
- **Orden de catálogo:** por `date_added` descendente; ties por `id`.
- **Orden de tema:** alfabético; dentro de cada tema por `year` desc.
- **Regeneración no destructiva:** sobrescribe el archivo entero.
  Cualquier edición manual se pierde.

### Regeneración

```bash
.venv/bin/python -c "
import sys; sys.path.insert(0,'scripts')
from _session_lib import refresh_research_evidence_md
refresh_research_evidence_md()
"
```

Idempotente y rápido (~milisegundos para decenas de papers).
