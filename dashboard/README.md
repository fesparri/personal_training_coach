# Dashboard local

Generador de un único HTML autocontenido con tu radiografía actual,
alertas según los umbrales del perfil, tendencias de wellness, volumen
por modalidad, ACWR, RPE y zonas HR.

## Uso

```bash
# Genera (o regenera) dashboard.html en el root del proyecto
python scripts/build_dashboard.py

# Abrirlo (macOS)
open dashboard.html
```

El HTML resultante es **autocontenido**: Chart.js + tus datos + CSS + JS
están todos embebidos. Funciona offline. Lo abrís con doble click.

## Qué muestra

- **Radiografía actual** — sleep score, duración de sueño, HRV avg,
  resting HR, body battery, stress avg del último día con datos.
- **Alertas activas** — disparadas por los `alert_thresholds` del perfil
  activo (ver `profiles/<name>/profile.yml`).
- **Bitácora corporal — abiertas** — partes con última observación
  `estado=open`.
- **Tendencias** — line charts de los últimos 90 días para sleep, HRV,
  RHR, body battery, stress.
- **ACWR** — ratio carga aguda 7d / crónica 28d, con bandas de
  referencia (sweet spot 1.0, umbral del perfil). Necesita ≥ 28 días de
  history para empezar a computar.
- **Volumen semanal por modalidad** — stacked bar chart en minutos.
- **RPE histórico** — bar chart coloreado por intensidad.
- **Zonas HR últimos 7 días** — donut con distribución Z1-Z5 sumada
  desde los `.fit` raw.
- **Bitácora corporal — histórico completo** — tabla append-only.

## Arquitectura

- `dashboard/build.py` — colectores y renderer. Agnóstico al perfil
  activo; lee `profile.yml` y aplica los thresholds correspondientes.
- `dashboard/template.html` — esqueleto HTML con CSS + JS app + 2
  placeholders: `/*__CHARTJS__*/` y `/*__DATA__*/`.
- `dashboard/vendor/chart.umd.min.js` — Chart.js 4.4.4 vendored.
- `scripts/build_dashboard.py` — CLI entry point fino.
- `dashboard.html` (output) — gitignored, regenerable.

## Cómo agregar una métrica nueva

1. En `dashboard/build.py`, sumar el colector en `collect_dashboard_data`.
2. En `dashboard/template.html`, agregar un `<canvas>` y un bloque JS
   que lo cargue con Chart.js.
3. Si la métrica es perfil-específica, leerla desde
   `profile.metrics_to_watch()` y skippearla cuando el perfil activo no
   la incluya.

## Refrescar diariamente

El comando es idempotente: re-correrlo sobreescribe `dashboard.html`.

Si querés automatizarlo, opciones:

- **Manual** — corré el comando cuando quieras ver el HTML.
- **Hook diario** — agregalo a cron / `launchd` después de tu
  `garmin_sync.py` diario.
- **Vía coach** — pedirle a Claude que lo corra cuando notes que el
  dashboard quedó desactualizado.
