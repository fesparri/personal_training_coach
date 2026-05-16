---
# Identificador único (kebab-case). También se usa como anchor en research_evidence.md.
id: <slug-en-kebab-case>

# Título del paper / estudio / reporte tal como aparece en la fuente.
title: "<Título completo>"

# Autoría. Lista de strings — uno por autor; "et al." está permitido.
authors:
  - "<Autor 1>"
  - "<Autor 2>"
  # - "et al."

# Año de publicación.
year: 2024

# Institución / lab / grupo que produjo el estudio.
source: "<Universidad / Lab / Institución>"

# Venue donde se publicó (journal, conferencia, reporte).
venue: "<Journal / Conferencia / SSAC Report / Preprint server>"

# DOI o URL si están disponibles (null si no hay).
doi: null            # "10.1234/xyz"
url: null            # "https://..."

# Calidad de evidencia. Valores aceptados:
#   peer_reviewed | meta_analysis | systematic_review | review |
#   preprint | report | expert_opinion | case_study | n_of_1
evidence_quality: peer_reviewed

# Temas que cubre el paper. El coach filtra por estos al planificar.
# Vocabulario sugerido (extensible):
#   performance, fatigue, recovery, strength, endurance, hypertrophy,
#   energy_systems, time_intensity, hybrid_training, female_athlete,
#   nutrition, sleep, hydration, hrv, vo2max, lactate, mobility,
#   injury_prevention, periodization, mental_skills, data_science,
#   acwr, deload, taper, race_strategy
topics:
  - <topic_1>
  - <topic_2>

# Perfiles del coach para los que este paper es relevante.
# Usá "all" para hacerlo universal.
# Valores: hyrox | wellness | half_marathon | triathlon | hypertrophy | all
profiles_relevant:
  - <perfil>

# TL;DR — 1-3 frases que capturen el aporte central. El coach lo usa
# como resumen rápido cuando armar planes.
tldr: >-
  <Resumen ejecutivo en 1-3 frases.>

# Findings clave del estudio (los hechos crudos: lo que midió/encontró).
# Mantenelos numéricos cuando sea posible.
key_findings:
  - "<Finding 1 con número/efecto si aplica>"
  - "<Finding 2>"

# Implicaciones para programación / cómo cambia esto la forma de planificar.
# Estos son los bullets que el coach va a citar al proponer/justificar sesiones.
training_implications:
  - "<Implicación práctica 1 — cómo se traduce a la rutina>"
  - "<Implicación práctica 2>"

# Tags libres (vocabulario controlado opcional). Útil para buscar.
tags:
  - <tag_1>

# Fecha en que se incorporó al compendio (YYYY-MM-DD).
date_added: <YYYY-MM-DD>
---

# <Título completo>

> Notas libres, citas verbatim, gráficos, tablas o cualquier
> contenido adicional que quieras conservar del paper original.
> El coach lee el frontmatter primero; este cuerpo lo lee solo
> cuando necesita profundizar.

## Resumen del estudio

<descripción del diseño, sample, métodos>

## Resultados detallados

<resultados, tablas, citas>

## Limitaciones / contexto

<limitaciones declaradas, generalización, pop estudiada>

## Notas del atleta / coach

<anotaciones propias — por qué este paper importa para mi caso, qué
adaptaciones específicas voy a probar, cómo lo voy a verificar>
