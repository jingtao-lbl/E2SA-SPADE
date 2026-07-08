---
name: e2sa-audit-adapter
description: Audit an E2SA adapter's data output against the REAL source and propose source-grounded corrections (applied only on human approval). Use after building or changing an adapter, after a parse, when staged data looks off, or for a periodic adapter review — "audit/validate the X adapter", "check the data X produces", "is above_stdm correct", "review the adapters for data-quality". Runs the e2sa/qc checks (serves-subset, value-range, subsurface-depth, citation-not-synthesized, self-describing) on a real parse, surfaces the value distributions, cross-checks variables/units/citation against the source, and PROPOSES a source-grounded fix for each finding (never invents) that is applied only on human approval (propose-first, like e2sa-refine-skill). NOT for run-level shippability (run skeleton / notebooks / secrets / a run_id) — that is `e2sa-validate`. Distilled from the 2026-06-23 above_stdm fabrications (reflection 20260623s).
allowed-tools: [Read, Glob, Grep, Write, Edit, Bash, WebFetch]
---

# e2sa-audit-adapter

The guard that turns "don't wait to be caught" into a runnable loop. It exists because an adapter, its fixture, and its tests can all be written against an *imagined* schema and pass green while the staged data is fabricated (invented variable), mislabeled (VWC percent as "fraction"), sentinel-poisoned (-999 ingested as data), or carries a synthesized citation. Tests that confirm the code's own assumptions cannot catch a wrong assumption; this skill checks against the **source and the real numbers** instead.

Read first: the reflection `memory/dev_logs/20260623s_Reflection_Fabrication_And_Unchecked_Data.md` (what goes wrong and why), `e2sa/qc/checks.py` (the checks you run), the memory rule [[never-fabricate-citations-or-capabilities]], and the adapter under review + its source card.

## When to fire

- After building or changing an adapter (pairs with `e2sa-add-adapter`), or after any parse.
- Staged data looks wrong (absurd counts, impossible values, null depths, a citation that reads assembled).
- A periodic "are the adapters honest" sweep.
- NOT for run-level shippability — that is `e2sa-validate` (`e2sa validate <run_id>`).

## Procedure

1. **Parse against REAL data, not a fixture.** Stage the dataset canonically (`acquire(source_id, dataset_id, project=..., parse=True)`); a fixture cannot catch a wrong-schema assumption because it was written from the same assumption. If only a fixture exists, first confirm the fixture mirrors the real CSV (real column names, real sentinels) — a hand-built fixture is itself a fabrication.

2. **Run the checks** (`e2sa.qc`):
   ```python
   from e2sa.qc import validate_observations, validate_staged_folder, summarize_distributions
   findings = validate_observations(adapter.serves, observations)
   findings += validate_staged_folder(staged_folder)
   dist = summarize_distributions(observations)   # min/median/max/depth per variable
   ```
   `validate_observations` catches: `serves` over-declaration (invented variable), values out of range (sentinel leak / unit mislabel / sign bug), and missing/negative subsurface depth. `validate_staged_folder` catches a non-self-describing folder and a synthesized citation.

3. **Look at the numbers.** Print `dist`. A median or max that is physically impossible (a "fraction" of 47, a depth of -9.99 m, a count 30x the dataset's stated size) is a finding even if no check fired. Counts are not verification; distributions are.

4. **Cross-check against the source** (the checks cannot know the source's truth): open the dataset landing page / the connector's captured native metadata (`metadata.json`/`metadata.txt`/EML). Confirm, against the source: every variable in `serves`/`VARIABLE_MAP`/`DatasetInfo.variables` is actually measured; the unit each is reported in; the missing-value sentinel; the official citation text.

5. **PROPOSE a source-grounded fix for each finding — do NOT apply yet.** This is propose-first, matching `e2sa-refine-skill` and the ReviewAgent (the auditor never silently rewrites an adapter; the failure mode it guards against is an agent confidently doing the wrong thing behind a green check). For each finding, diagnose the source cause and write the fix as a concrete **proposed diff** (which file, what change, and the source evidence it is grounded in). The one rule that matters: a fix is copied from the source or computed from real data, never a plausible guess.
   - Invented variable -> remove it from `VARIABLE_MAP` / `serves` / `DatasetInfo.variables` / the name.
   - Sentinel leak -> filter the per-file sentinel at parse (`value < 0` for non-negative quantities); never store it.
   - Unit mislabel -> emit the canonical unit (convert; e.g. VWC % -> fraction). Do NOT pre-filter outliers — that is QC's job to *report*, per the canonical-units work.
   - Lost depth -> read the real depth column(s); a subsurface reading needs `depth_m`.
   - Synthesized/missing citation -> use the source's official citation verbatim in `DatasetInfo.citation`; if you cannot find it, leave it `None` (the bundle points to the landing page). **Never assemble a citation from the title + URL.**
   - Fabricated fixture -> rewrite it from a few real rows (real column names, real sentinels).

6. **Present findings + proposed diffs together and STOP for human approval.** Do not edit anything before approval (matches `e2sa-refine-skill`: propose, never self-apply). For citation/provenance fixes, show the source text + where it was copied from as part of the proposal.

7. **On approval: apply, then re-validate.** Apply only the approved fixes, re-run step 2 until zero `error` findings, and report. Do not loop or "improve" beyond the approved set — further changes need another approval (the `e2sa-finalize` stop condition). If approval is withheld for a finding, leave it and record it as an open item.

## Guardrails

- **Propose, never self-apply.** Detect + propose fixes as diffs; apply only after explicit human approval (step 6). The auditor must not silently rewrite an adapter — that reintroduces the very risk it exists to catch.
- **A fix never fabricates.** Corrections are copied from the source or computed from the real data. If the source is silent, the honest fix is `None` + a pointer, not a guess. A fabricating "fix" re-offends.
- **Real parse + real fixture.** Validate against staged real data; a fixture must mirror the real schema (columns + sentinels) or it is a fabrication that hides the bug.
- **Report, don't drop.** Outliers that survive the sentinel filter are reported (QC), not silently removed by the adapter.
- **Distributions over counts.** "It produced N rows" is not validation; inspect min/median/max and physical plausibility.
- **Human gate on provenance.** Citation/license edits are shown with their source and authorized before commit.
- The checks live in `e2sa/qc/checks.py` and are unit-tested; extend them there (with a test) when a new failure mode appears, rather than ad-hoc in a session.

## Changelog
- 2026-06-23: Initial version. Distilled from the `above_stdm` failures (reflection `20260623s`): fabricated citation, invented `soil_temperature`, and `-999`/percent/depth values ingested without checks. Backed by the new `e2sa/qc/checks.py` validators.
- 2026-06-23: Made it **propose-first** (was correct-then-stop). Steps 5-7 now: propose source-grounded fixes as diffs, STOP for human approval, apply only on approval, then re-validate. The auditor never self-applies (matches `e2sa-refine-skill` + the ReviewAgent; auto-fixing reintroduces the confidently-wrong-behind-a-green-check failure mode this skill exists to catch). Renamed from `e2sa-validate-adapter` to avoid colliding with `e2sa-validate`.
