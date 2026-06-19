---
name: e2sa-lessons-capture
description: Auto-fire on any stage failure, retry, data surprise, or performance issue. Capture E2SA-specific operational lessons (data-adapter quirks, geospatial reprojection traps, schema mismatches, model-training divergences, JupyterHub/cluster environment issues) so the same trap is not hit twice. Writes to memory/knowledge/lessons/. Not user-invocable.
allowed-tools: [Read, Grep, Glob, Write, Edit]
---

# e2sa-lessons-capture

Auto-firing skill. Fires whenever a pipeline stage fails, requires a substantial retry, surfaces a data surprise, or hits a performance/environment issue. Captures the lesson if novel, deduplicates if not.

## When this skill fires

- Any pipeline stage returns a failure or requires a substantial retry.
- QCAgent flags a data surprise (out-of-range values, missing coverage where coverage was expected, cross-source disagreement above threshold).
- An adapter hits a credential, rate-limit, schema-drift, or transient error that requires more than one retry.
- A modeling stage hits divergence, NaN loss, or unexpected calibration failure.

## Protocol

1. **Check duplicates.** Grep `memory/knowledge/lessons/` for entries matching the failure signature (error message, adapter name, schema field, geospatial operation, etc.). If a close match exists, append a one-line counter under the existing entry's "occurrences" section and stop. Do not create a new entry.
2. **Decide novelty.** If no match, ask the human: "Hit a [brief description] in [stage]. Worth documenting in `memory/knowledge/lessons/`? (Y/n)" Default Y. Honor "do not interrupt flow unnecessarily, the human's primary task always comes first" — if the human is mid-task, defer and ask at the end of the stage.
3. **Draft entry.** Follow the fixed template (below). Place under the appropriate section taxonomy.
4. **Present for review.** Show the draft to the human. On approval, write to `memory/knowledge/lessons/<id>.md` where `<id>` is `<YYYYMMDD>-<short-slug>` (dashes throughout, no underscores). Filename and id are identical so a grep for the id resolves directly to its file. Also append a one-line summary to `memory/knowledge/lessons/index.md`.

## Entry template

```markdown
---
id: <YYYYMMDD>-<short-slug>
title: <one-line description>
type: lesson
section: <adapter|harmonize|qc|features|train|eval|env>
status: active
source_projects: [<project>]
source_docs: [<dev_log_path_or_run_id>]
confidence: high|medium|low
last_reviewed: <YYYY-MM-DD>
related_pages: []
---

# <one-line title>

## What went wrong

<brief explanation, 2-4 sentences>

## Code example: wrong approach

```<lang>
<minimal reproduction of the wrong approach>
```

## Code example: correct approach

```<lang>
<minimal correct approach>
```

## One-sentence solution

<single sentence the agent can apply next time without reading the rest>
```

## Section taxonomy

- `adapter/` — per-source adapter quirks (CALM column shifts, GTN-P unit mismatches, ABoVE NetCDF dimension order, etc.)
- `harmonize/` — geospatial reprojection traps, CRS edge cases, time-alignment pitfalls
- `qc/` — range-check thresholds that don't generalize, cross-source consistency surprises
- `features/` — feature-engineering numerical edge cases (e.g. log-zero, undefined NDVI)
- `train/` — divergence patterns, dataloader bugs, GPU memory traps
- `eval/` — leakage from random splits, calibration metric misuse
- `env/` — JupyterHub idle timeout, cluster module conflicts, conda solver issues

## Etiquette

Do not interrupt flow unnecessarily. The human's primary task always comes first. If a stage is in mid-execution and a recoverable retry is in progress, queue the capture for the end of the stage.

## Changelog
- 2026-06-17: Adopted the Changelog convention (`docs/design/09_skill_evolution.md`); prior history is in git.
