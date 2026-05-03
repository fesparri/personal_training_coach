# Volumen ejecutado — ledger histórico

> Plantilla genérica. Copiá este archivo al root del proyecto como
> `executed_volume.md` antes de arrancar.
>
> **Append-only ledger** del trabajo realmente ejecutado (no del programado).
> Se mantiene en paralelo a `master_plan.md` y a los reportes auto-generados
> en `reports/weekly/`. Cuando hay diferencia entre programado y ejecutado,
> esta es la fuente de verdad para "qué carga real acumulé".
>
> **Fuente:** datos descargados por `scripts/garmin_sync.py` y consolidados
> por los helpers de `scripts/_session_lib.py` al cierre de cada día.
>
> **No editar entries pasadas.** Solo se agregan filas nuevas. Los ajustes
> y por qué de cada sesión se loggean en `plan_adjustments.md`.

---

## Notación

- **Modalidad** usa el `activityType.typeKey` de Garmin tal cual
  (`running`, `treadmill_running`, `indoor_rowing`, `indoor_cardio`,
  `strength_training`, `hiit`, `obstacle_run`, `lap_swimming`, `walking`,
  `cycling`, etc.).
- **FC** se reporta en bpm: `media / max`.
- **Pace** solo para correr (min/km), calculado como `dur / (dist/1000)`.
- **`.fit`** identifica al activity_id; el archivo está en
  `data/<fecha>/activities/<id>.fit`.

---

## YYYY-Www (DD/MM → DD/MM)

| Fecha | Modalidad | Duración | Distancia | FC media / max | Notas |
|---|---|---:|---:|---:|---|

---

## RPE por día

> RPE = esfuerzo percibido global de la sesión, escala 1-10
> (1 = paseo, 5 = moderado, 8 = duro, 10 = al límite). Cargado por
> `feedback_session.py` post-sesión.

| Fecha | RPE | Notas |
|---|---:|---|

---

## Bitácora corporal

> **Append-only.** Cada observación de carga / molestia / lesión va en una
> fila nueva. Para **cerrar** una molestia, agregá fila con
> `estado=resolved`. Para reportar **empeoramiento**, fila nueva con
> severidad mayor. La parte es texto libre — escribí lo que tenga sentido
> (e.g. `tibial der`, `hombro izq`, `cuádriceps`, `lumbar`, `rodilla der`).
>
> **Cómo se lee el "estado actual del cuerpo":** para cada parte distinta,
> tomá la fila más reciente. Si su `estado=open`, la molestia sigue activa.
> Si es `resolved`, ya cerró. El histórico queda intacto para ver
> trayectoria.

| Fecha | Parte | Severidad | Estado | Notas |
|---|---|---:|---|---|
