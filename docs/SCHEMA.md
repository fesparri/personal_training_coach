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
