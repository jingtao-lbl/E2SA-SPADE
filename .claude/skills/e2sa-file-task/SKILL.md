---
name: e2sa-file-task
description: File a data-preparation task into projects/<project>/tasks/ when the current work needs site data that isn't already prepared. Use whenever the agent (not just the human) recognizes a need for forcing data, surface dataset assembly, observations, or QC/analysis that warrants its own request with provenance. Always sets status=requested and surfaces to the human; never auto-executes the filed task in the same fire.
allowed-tools: [Read, Glob, Grep, Write, Edit, Bash]
---

# e2sa-file-task

File a `<task_id>.md` into `projects/<project>/tasks/<task_id>/` when the agent recognizes that the current work needs data preparation. **The agent is a requester, not just a responder.** This skill captures when to file, what to write, how to cross-link, and the etiquette around not auto-executing.

## When to fire (triggers)

Fire when any of these is true during other work:

1. **Run scaffolding** (`e2sa_start` / S0 Intake). The new run's `RESEARCH_PLAN.md` lists a site that does not have a complete `MANIFEST.md` under `projects/<project>/tasks/` or analysis-ready files under `projects/<project>/data/processed/sites/<site>/`.
2. **Source discovery** (S2). The adapter for the requested data exists but turning the raw download into the format the run needs requires multi-step assembly (e.g. reanalysis -> hourly site-stream netCDF), or multi-source fusion (e.g. gap-fill ERA5 with site tower observations).
3. **Research-question scoping**. While scoping an entry under `memory/knowledge/research-questions/`, the question implies "we need site X prepared for ELM-FATES" as a prerequisite.
4. **Manuscript / report figure**. While drafting a figure for a manuscript or report, the figure requires a site simulation whose forcing or surface data is not yet on disk.

Do NOT fire when:

- **The data is already locally available.** Always run a Step 0 inventory check FIRST. SPADE has eight catalogued sources spanning ALT (CALM, ABoVE), ground temperature (GTN-P, GIPL-UAF), ice content (Brown 2002), thaw events (Webb 2025, registered in the catalog), thermokarst (Olefeldt 2016), and the NGEE-Arctic portal on ESS-DIVE (hundreds of datasets at Alaska sites). Check `projects/spade/data/sources/README.md`, `projects/spade/data/raw/`, the registered datasets in `projects/spade/data/catalog.duckdb`, and `~/Desktop/Work/DataObservations/` (via `additional_local_archives.md`) before filing. If covered, cite the existing source doc and skip the fetch. If partially covered, file only for the missing slice.
- The work is a one-shot adapter call already covered by `BaseAdapter.fetch()`, like the Alaska Thaw DB download. The catalog provenance record is enough; a task adds bureaucracy without adding signal.
- The agent already has all inputs in memory and can produce the deliverable in a single step with no upstream calls.
- The human's current ask is genuinely unrelated to site data prep.

## Decision rule (use-existing vs inline-do vs file vs ask)

```
Is this work data preparation for an ELM-FATES site simulation?
  no  -> not this skill; continue current work
  yes -> STEP 0: Is the data already locally available?
           (scan projects/spade/data/sources/README.md,
            projects/spade/data/raw/, ~/Desktop/Work/DataObservations/)
           yes, fully -> USE EXISTING; no fetch, no task; cite source doc
           yes, partial -> drop covered portion, apply rest to missing slice
           no -> STEP 1: Does the missing fetch fit in a single existing-adapter call?
                   yes -> inline-do; record provenance via the catalog
                   no  -> STEP 2: Is the request well-specified from project context alone?
                            no  -> ask the human (do not file a half-specified task)
                            yes -> file a task here; surface to the human;
                                   wait for go-ahead before executing
```

The full decision rule with worked examples lives in `memory/knowledge/methods/20260521-when-to-file-a-data-prep-task.md`. The "use existing data" step is non-negotiable. Re-downloading what is already on disk wastes time, network, and risks duplicate-but-not-identical artifacts that fork the provenance chain.

## Protocol

1. **Identify the project**. Use the calling context. A skill firing inside `projects/spade/runs/<run_id>/` infers `project = spade`. A research-question entry with `source_projects: [spade]` is the same. If unclear, ASK the human before filing.

2. **Generate the task id**. Format: `<YYYYMMDD>-<site-or-region>-<short-purpose>`. Dashes throughout, no underscores, lowercase. Example: `20260521-toolik-lake-forcing-2010-2024`.

3. **Create the subdirectory**. `mkdir -p projects/<project>/tasks/<task_id>/`.

4. **Write `<task_id>.md`** following `projects/<project>/tasks/TASK_TEMPLATE.md`. Frontmatter conventions when the agent files:
   - `requester: agent` (not `Jing`).
   - `status: requested` (never auto-flip to `in_progress` in the same fire).
   - `related_run:` set to the originating run id, if any.
   - `related_tasks:` set to any other tasks this depends on or duplicates.
   - Top of `<task_id>.md` body, add a one-line "Filed by agent" note with the originating context (e.g. "Filed automatically from `projects/spade/runs/2026-toolik-cnp-baseline/` during S0 Intake on 2026-05-21").

5. **Cross-link back to the calling context.** If the call came from a run, append the new task to a "Data preparation dependencies" table in the run's `RESEARCH_PLAN.md`. If the call came from a research-question entry, add the task id to `related_pages`. Closing the loop is non-negotiable; an orphan task is worse than no task.

6. **Surface to the human.** Print to stdout (or whatever the calling context surfaces): "Filed task `<task_id>`. Status: requested. Estimated work: <one phrase>. Estimated cost / wall-clock: <quick estimate>. Reply with `proceed`, `revise`, or `cancel` to direct next steps." Do NOT call `/e2sa-process-task` or otherwise execute the task in the same fire.

7. **Wait for human direction.** The agent's job ends at "filed and surfaced." The human (or a separate invocation in a later turn) flips status to `in_progress` and begins execution.

## <task_id>.md additions when agent-filed

Beyond what the template requests, an agent-filed `<task_id>.md` MUST include:

- **Provenance of the request**. A short paragraph at the top of the body explaining what calling context decided this task is needed. Cite file paths, run ids, or research-question ids. The human reviewing the task should be able to trace exactly why the agent thinks the prep is necessary.
- **Acceptance criteria written from the calling context's needs**. The agent knows what downstream needs the data for (a specific ELM run, a calibration target, a figure); it should phrase acceptance criteria in those terms, not in generic data-quality language.
- **Estimated cost**. Best-effort: bytes to download, API calls, paid-API spend if any. The human reads this before authorizing execution.

## Anti-patterns to avoid

- **Filing under-specified tasks to "make the agent look productive."** If you cannot fill in target format, time period, source preference, and acceptance criteria from the calling context, ASK the human first; do not file a stub.
- **Auto-executing a filed task in the same skill fire.** This skill stops at "filed and surfaced." Execution is a separate skill (`e2sa-process-task`, to be written when the workflow needs it).
- **Filing duplicate tasks.** Before filing, grep `projects/<project>/tasks/` for tasks targeting the same site and similar work types. If a duplicate or near-duplicate exists, surface that to the human and ask whether to extend the existing task, fork from it, or fold the new request into the existing one.
- **Forgetting to cross-link.** A task filed without an updated entry in the originating context (RESEARCH_PLAN.md table, research-question `related_pages`, manuscript figure spec) is an orphan. Always close the loop.

## What this skill does NOT do

- Execute the task it filed. Execution is a separate fire, driven from a fresh prompt or a different skill, so the human has a chance to review.
- Decide between forcing-data sources, surface-dataset granularity, observation networks, or QC thresholds without project-context evidence. If the choice cannot be made from `projects/<project>/CLAUDE.md` + `data/sources/*.md` + the calling context, ASK the human.
- Spend money on the agent's own request without explicit human authorization. When executing an agent-filed task, surface any paid-API or cloud-egress cost in STATUS.md and wait for confirmation before proceeding.

## Output expected

A single new directory `projects/<project>/tasks/<task_id>/` containing `<task_id>.md`, plus any cross-link edits in the originating context. Status `requested`. Surfaced to the human. That is the entire deliverable of this skill.

## Changelog
- 2026-06-17: Adopted the Changelog convention (`docs/design/09_skill_evolution.md`); prior history is in git.
