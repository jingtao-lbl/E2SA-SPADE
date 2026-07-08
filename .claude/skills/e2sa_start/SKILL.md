---
name: e2sa_start
description: Bootstrap a new E2SA project or run. Creates projects/<project>/runs/<run_id>/ with the canonical skeleton (RESEARCH_PLAN.md, REPORT.md, run.yaml, notebooks/, data/, figures/). Always fires first when a new run begins; the human asking for analysis directly does not get to skip it.
allowed-tools: [Bash, Read, Write, Edit]
---

# e2sa_start

Bootstrap entry point for any new E2SA run. Mandatory first step. The workflow guard refuses to advance past S0 Intake until this skill has run.

## When to invoke

- The human asks to begin a new project or run, with or without using the `/e2sa_start` slash command.
- The orchestrator's S0 Intake stage starts and no `runs/<run_id>/` exists for the requested run.

## What this skill does

1. Read the run config from arguments (or prompt for `<project>` and `<run_id>`). **`run_id` names the *analysis*, not the data.** It is lowercase snake_case describing the work and unique per run (`alaska_thaw_db_eda`, `ice_content_baseline`, `blocked_cv_v2`) — it is **not** a `dataset_id` slug. A run often spans several datasets, and you will want multiple runs on the same data (an EDA, a baseline, a validation), so name it by purpose with a verb/kind suffix (`_eda`, `_baseline`, `_validation`), never after a single dataset's slug.
2. Shell out to the CLI: `e2sa init <project> <run_id>`. The CLI does all filesystem work; this skill does not duplicate logic.
3. Echo the path of the new run subdirectory and the names of the seeded files.
4. Surface related prior work from `memory/knowledge/` and the cross-workspace index (handled by `e2sa-intake`, not by this skill, but flag the handoff).

## Per-run skeleton

```
projects/<project>/runs/<run_id>/
├── run.yaml          # manifest: project, run_id, created, author, status, model versions
├── RESEARCH_PLAN.md  # declarative scope (agent + human author together)
├── REPORT.md         # findings (agent authors after results land)
├── notebooks/        # analysis as Jupyter notebooks (with saved outputs)
├── data/             # run-specific intermediate data (gitignored)
└── figures/          # run-specific figures
```

## Non-skippable invariant

Bootstrap is non-skippable. If a human prompt asks for analysis directly (skipping the skeleton), the orchestrator must call `e2sa_start` first, then proceed.

## Trigger for the e2sa-file-task skill

After scaffolding, if the new run's intended analysis depends on site data that is not present under `projects/<project>/data/processed/sites/<site>/` and does not have a completed `MANIFEST.md` in `projects/<project>/tasks/`, fire `e2sa-file-task` once per missing site (or once per missing work-type for a multi-task site). Set `related_run` in the new <task_id>.md's frontmatter to this run's id. The decision rule for file vs inline-do vs ask lives in `memory/knowledge/methods/20260521-when-to-file-a-data-prep-task.md`. Do NOT execute the filed task in the same fire; surface to the human and wait.

## Output

Print the path of the new run subdirectory. Print which template files were seeded. Do NOT begin analysis in this skill; that is the next stage's job.

## Changelog
- 2026-06-17: Adopted the Changelog convention (`docs/design/09_skill_evolution.md`); prior history is in git.
- 2026-06-23: Documented the `run_id` naming convention in step 1 (run_id = the analysis/purpose, lowercase snake_case with a verb/kind suffix; NOT a `dataset_id` slug). Prompted by keeping `alaska_thaw_db_eda` rather than renaming it to the dataset slug.
