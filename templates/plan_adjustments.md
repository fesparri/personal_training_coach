# Plan Adjustments — log append-only

> Plantilla genérica. Copiá este archivo al root del proyecto como
> `plan_adjustments.md` antes de arrancar.
>
> **Reglas:**
> - Append-only. Nunca borres ni edites entries pasadas.
> - Cada modificación al `master_plan.md` se registra acá con la entry
>   estándar de abajo.
> - Si la sesión salió tal cual el plan, **no se registra**. Solo se loggean
>   ajustes (cambio de carga, modalidad, día, descanso forzado, etc.).
> - "Source" debe ser un path relativo al archivo de datos que disparó el
>   cambio (`data/<fecha>/wellness.json`, `data/<fecha>/activities/...`,
>   `data/<fecha>/notes.md`).

---

## Formato de entry

```
---
Date: YYYY-MM-DD
Original session: [fecha y descripción según master_plan.md]
Modified to: [lo que efectivamente se programó]
Executed as: [lo que realmente se ejecutó]
Reason: [data point que disparó el cambio — wellness, .fit metric, nota, vida]
Source: [path del archivo de datos que disparó el cambio]
---
```

---

## Entries

<!-- Agregar nuevas entries debajo de esta línea, manteniendo orden cronológico ascendente. -->
