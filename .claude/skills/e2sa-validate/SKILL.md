---
name: e2sa-validate
description: Deterministic structural checks on a run (no LLM call). Verifies the per-run skeleton is complete, notebooks have saved outputs, no hardcoded secrets, no derived-from-script notebook helpers, requirements.txt matches imports, schemas valid, provenance complete, tests pass. Backs the `e2sa validate <run_id>` CLI. Fast (seconds), rule-based.
allowed-tools: [Bash]
---

# e2sa-validate

Thin wrapper around the `e2sa validate <run_id>` CLI command. Does not call the LLM. Returns exit code 0 on pass, non-zero with a named issue list on fail.

## When to invoke

- Mid-run, when a human wants a quick sanity check.
- Pre-commit / pre-push, automatically (also wired into `e2sa-workflow-guard`).
- As the first step of `e2sa-finalize`.

## Checks (P0 set, expand later)

1. **Skeleton complete.** `runs/<run_id>/` contains `run.yaml`, `RESEARCH_PLAN.md`, `REPORT.md`, `notebooks/`, `data/`, `figures/`.
2. **`run.yaml` parseable** and has required fields (`project`, `run_id`, `created`, `status`).
3. **Notebooks have saved outputs.** Every `.ipynb` under `notebooks/` has at least one cell with non-empty `outputs`. A notebook with all-empty outputs is a reproducibility-spirit gap; flag.
4. **No hardcoded secrets.** Regex scan for API key patterns (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `AWS_SECRET_ACCESS_KEY`, `EARTHDATA_TOKEN`, generic 32-char hex tokens, JWTs) in any file under the run dir. Match means fail.
5. **No derived-notebook helpers.** Warn if `create_notebooks.py` (or any `*_to_notebook.py` / `nbgen*.py`) exists alongside the notebooks it produced. Notebook-first execution is the policy; helper-generated notebooks are a reproducibility spirit gap.

## Expanded checks (P2+, when adapters and schemas exist)

6. Schema validation via `pandera` at module boundaries.
7. Every catalog record carries provenance (source / URL / timestamp / checksum / license / adapter version / schema version).
8. `requirements.txt` imports match the actual imports in `notebooks/` and `src/`.
9. `pytest tests/` passes.

## Behavior

- Exit 0 if all checks pass.
- Exit non-zero with a numbered list of failures, one per line, on the form `<check_id>: <human-readable description>: <path-or-line>`.
- Print a one-line summary at the end: `PASS (N checks)` or `FAIL (M issues, N checks)`.
- Do not modify any files. Read-only.

## Changelog
- 2026-06-17: Adopted the Changelog convention (`docs/design/09_skill_evolution.md`); prior history is in git.
