# AGENTS.md — E2SA Interactive Agent Operating Contract

**Audience:** Any coding-agent harness (Claude Code or other AGENTS.md-aware agents) operating interactively inside a clone of this repository.

**Scope:** Framework-level, project-agnostic, public-safe, harness-neutral. This is the portable distillation of the operating rules an interactive agent needs across **all** E2SA projects. (Claude Code may additionally read a private `CLAUDE.md` superset when present; this file is the shareable subset.)

---

## What E2SA is

E2SA ("End-to-End Science Agent") is a domain-agnostic framework for building agentic science pipelines. A single orchestrator takes a research question through literature RAG, data discovery, retrieval, harmonization, QC, feature engineering, modeling, evaluation, and reporting. Each science use case is a concrete **project** built on the framework. Projects live under `projects/<project>/` and reuse the shared orchestrator, catalog, retrieval, harmonization, QC, evaluation, and reporting layers, supplying only the truly domain-specific pieces (adapters, schema extensions, model heads, domain priors).

The first project is **SPADE** (Subsurface Permafrost Autonomous Discovery Engine). This contract is written at the **framework** level — it governs your work on E2SA itself and on any project. For per-project science context, read that project's `projects/<project>/CLAUDE.md` (and `projects/<project>/AGENTS.md` if present).

## One framework, two agent modes

E2SA runs as **one framework in two modes**, both consuming the same shared substrate — operating rules (this file), the skills catalog (`.claude/skills/`), persistent memory and knowledge (`memory/`), the catalog (DuckDB) and vector store (LanceDB), and the shared tools in `tools/` and `e2sa/`:

| | **Autonomous (online) agent** | **Interactive (offline) agent** |
|---|---|---|
| Runtime | The E2SA orchestrator — Claude (Agent SDK) driving the S0→S10 pipeline from a run config | *You* — a coding-agent harness operating in the repo, driven by conversation |
| Driver | Fixed stage state machine (S0 Intake → S10 Feedback) | Human, turn-by-turn |
| Cadence | Unattended, checkpointed, at scale | Human-in-the-loop |
| Best for | The repetitive, well-defined pipeline run for a project | Open-ended, exploratory, judgment-heavy, one-off work the fixed pipeline cannot do |
| Examples | Discover → retrieve → harmonize → QC → feature → model → evaluate → report | Building framework code and adapters, data-prep task triage, schema design, forensics on a stage failure, figures, experiment design, auditing, reviewing a run |

> **Maturity note.** The autonomous orchestrator is still scaffold (`e2sa/orchestrator.py`; the full S0→S10 loop is roadmap). Today the framework ships the `e2sa` CLI (`init`, `user`, `validate`) and the interactive mode is where nearly all current work happens — building the machine that will one day run autonomously. Describe the autonomous mode as the target, not as if it already runs end-to-end.

Both modes read and write the same knowledge substrate, so discoveries made in one mode compound in the other (see §"The knowledge loop").

## Core operating rules

Framework- and project-agnostic. Follow them on every task.

1. **Verify, don't assume.** Never state what a parameter, flag, file, dataset, or mechanism does from its name. Read the source of truth first — the relevant config, schema, adapter, or doc. When uncertain, check before claiming.
2. **Provenance is non-negotiable.** Every downloaded record carries source id, source URL or API endpoint, access timestamp (UTC), content checksum (sha256), license, adapter version, and schema version. A record without provenance does not enter the catalog.
3. **Raw data is immutable.** Never edit `data/raw/` (or a project's `raw/`). Every transformation must be reproducible from raw. Cleaned and analysis-ready artifacts are derived, never hand-edited.
4. **Inference is not observation.** Model predictions are labeled as inference, never presented as measured data. Keep data, model inference, and interpretation visibly separate in code, figures, and prose.
5. **No hallucinated datasets — ever.** A claimed dataset, source, or value is a critical failure unless backed by a verifiable retrieval hit. The vector store holds only extracted text with its source. Never invent references or numbers.
6. **Framework stays domain-agnostic; projects hold the specifics.** Code under `e2sa/` must not hardcode a project's sites, variables, paths, or domain assumptions. Domain-specific content lives under `projects/<project>/`. One adapter module per data source under `e2sa/data/adapters/` (per-data-center connectors under `e2sa/data/connectors/`), with the fixed interface.
7. **Start every run through `e2sa_start`.** A new run must be bootstrapped into `projects/<project>/runs/<run_id>/` with the canonical skeleton before analysis begins. The workflow guard refuses to advance past S0 Intake until it has. A human asking for analysis directly does not get to skip it.
8. **Read before you write.** Before adding code, read the exports, immediate callers, and shared utilities you will touch. Verify folder and file names by listing or reading — never guess directory names. Match existing conventions even where you would choose differently.
9. **Surgical changes.** Touch only what the task needs. Do not refactor, reformat, or "improve" adjacent code. Minimum code that solves the problem; nothing speculative.
10. **No AI attribution in commits.** Never add `Co-Authored-By` or any AI-attribution trailer, and no human-attribution trailer either. The git author metadata is enough. (Authored docs and scripts use the project's in-file author convention.)
11. **Fail loud.** "Done" is wrong if anything was skipped silently; "tests pass" is wrong if any were skipped. Surface uncertainty instead of hiding it.
12. **Verify what you build.** After building something (an adapter, parser, transform, model output), build a validator that checks the result against the **real source and the real numbers** (value distributions, units, missing-value sentinels, citations) — not against a hand-built fixture or your own assumptions. A green test on a self-built fixture confirms the code's assumptions, not their correctness. Reusable checks live in `e2sa/qc/checks.py`; the `e2sa-audit-adapter` skill runs them on a real parse and proposes source-grounded fixes. Never fabricate to pass a check; if the source is silent, the honest result is `None` plus a pointer, not a guess.

## Capability catalog (skills)

Your reusable capabilities live in `.claude/skills/`, each a folder with a `SKILL.md` whose `description` frontmatter is the trigger the harness matches against a request. When a request matches a skill's trigger, invoke the skill **before** improvising — it encodes conventions (run skeleton, provenance, task etiquette, validation gates) that are easy to get wrong from first principles.

| Skill | Invoke when… | Notes |
|---|---|---|
| `e2sa_start` | a new project or run begins — "start a run", "set up the analysis for X" | **Mandatory first step.** Creates `projects/<project>/runs/<run_id>/` (`RESEARCH_PLAN.md`, `REPORT.md`, `run.yaml`, `notebooks/`, `data/`, `figures/`). Fires before any analysis. |
| `e2sa-file-task` | the current work needs data that isn't prepared — forcing data, surface dataset assembly, observations, QC/analysis warranting its own request | The agent is a **requester**, not just a responder. Files a `<task_id>.md` into `projects/<project>/tasks/` with `status=requested`, surfaces to the human; never auto-executes the filed task in the same fire. |
| `e2sa-add-data-source` | adding a new dataset or archive — "add a data source", "add this dataset", or after downloading from a center not yet documented | Walks inventory check → latest version → whole-package download to `raw/<data_center>/<dataset_id>/` → inspect → project-named source card → update the sources index + data-center registry → finding → credentials. Hands off the adapter coding to `e2sa-add-adapter`. |
| `e2sa-add-adapter` | writing the adapter code for an onboarded source — "build/write the X adapter", "implement fetch/parse for X" (the coding step after `e2sa-add-data-source`) | Implements the `BaseAdapter` contract (`list_available`/`fetch`/`parse_to_schema`), the `FetchResult` single-file-vs-package shape, `Observation`+`Provenance`, canonical units + `depth_m` + `serves`, `ADAPTER_REGISTRY` registration, a fixture + test, and the parse gotchas (sentinels, CRS tiers, `obs_id` uniqueness, schema drift, idempotency). Connector-backed adapters set `data_center` + delegate `fetch`; includes a migrate-existing-adapter-to-a-connector recipe. |
| `e2sa-add-connector` | wrapping a data center not yet connected, or migrating a self-fetching adapter onto one — "add a connector for X", "wrap the PANGAEA/Earthdata/Zenodo API" | Implements a `BaseConnector` (auth + search + whole-package fetch, Option C): probe-the-API-first, the contract + `CONNECTOR_REGISTRY` registration, the two `search` patterns (server-side filter vs enrich + bbox coverage-ratio), the two `fetch` shapes (BagIt-zip vs file-by-file), urllib/User-Agent/token-free-reads/raw-layout/on-disk-fast-path/manual-fallback conventions, and the mocked-`urlopen` + `E2E_LIVE` test split. Distilled from `arctic_data_center` + `ess_dive`. |
| `e2sa-validate` | you need to check a **run** is shippable — "validate run X", before declaring a run done | Deterministic, no LLM call. Backs `e2sa validate <run_id>`. Checks the run skeleton, saved notebook outputs, no hardcoded secrets, requirements match imports, schemas valid, provenance complete, tests pass. (For an adapter's **data**, not a run, use `e2sa-audit-adapter`.) |
| `e2sa-audit-adapter` | after building/changing an adapter, after a parse, or when staged data looks off — "audit/validate the X adapter", "check the data X produces", "is X correct" | Runs the `e2sa/qc` checks (serves⊆emitted, value-range, subsurface-depth, citation-not-synthesized, self-describing) on a **real** parse, surfaces value distributions, cross-checks variables/units/citation against the **source**, and **proposes** a source-grounded fix for each finding (never inventing), applied only on **human approval** (propose-first, like `e2sa-refine-skill`). NOT run-level shippability (that is `e2sa-validate`). Distilled from the 2026-06-23 `above_stdm` fabrications (`20260623s`). |
| `e2sa-lessons-capture` | (auto) a stage fails, needs a substantial retry, surfaces a data surprise, or hits a perf/environment issue | **Not user-invocable** — auto-fires. Writes a deduplicated lesson to `memory/knowledge/lessons/` so the same trap is not hit twice. |
| `e2sa-add-skill` | creating a new capability — "add a skill", "scaffold a skill", "make this reusable as a skill" | Scaffolds `SKILL.md` + **registers it in this catalog** + seeds a Changelog; human-gated. See `docs/design/09_skill_evolution.md`. |
| `e2sa-refine-skill` | a skill missed a step, a lesson/feedback piled up in its domain, or a periodic skill review — "refine the X skill", "improve this skill" | Distills signal (lessons, run-journal outcomes, feedback) into a proposed `SKILL.md` diff; **proposes, never self-applies**; human-gated. See `docs/design/09_skill_evolution.md`. |
| `e2sa-site-figure` | building a study-site / watershed / regional map figure — "make a site/watershed map", "plot a DEM with sites overlaid", "stage HUC-8 boundaries", "add/rescope a study site" | Public-data → georeferenced map → reviewer-clean PNG/PDF. Config-driven reference scripts in `projects/spade/tools/site_figure/` (boundary download, DEM tile/mosaic/clip, NWIS gauges, zorder figure template). Consumed by the ReportAgent (S9). NOT for conceptual diagrams or data plots. |

## Memory & knowledge conventions

| Where | What it holds | You should… |
|---|---|---|
| `memory/dev_logs/` | Engineering changelog (Markdown, dated `YYYYMMDDx_Topic.md`) | **read before** starting related work; **write** a dated log for substantive changes |
| `memory/knowledge/lessons/` | Operational traps and their one-line fixes | read for context; let `e2sa-lessons-capture` add new ones |
| `memory/knowledge/findings/` | Cross-run scientific findings | read; add vetted findings |
| `memory/knowledge/methods/` | Reusable method notes | read; add when a method generalizes |
| `memory/knowledge/research-questions/` | Open and answered research questions | read; update as questions resolve |
| `memory/run_journals/` | Per-run agent decisions and tool calls (JSONL) | the autonomous mode writes these; read them to reason over a run |
| `memory/decision_records/` | Architecture decision records (ADRs) | read before re-litigating a settled design choice |
| catalog (DuckDB) / vector store (LanceDB) | what datasets exist / extracted literature snippets | query before asserting a dataset exists or a claim has a source |
| `tools/`, `e2sa/` | shared utilities and framework code | reuse rather than re-implement |

**Before starting a task:** grep `memory/dev_logs/` (and the relevant `memory/knowledge/` sub-dir) for prior work on the same topic. Repeating a superseded approach is the most common avoidable mistake.

**When you finish substantive work:** write a dated dev log per the workspace convention (Summary, Problem, Solution, Files Changed table, Verification), so the next session — and the autonomous mode's knowledge absorption — can build on it.

## The knowledge loop

The two modes are two writers on **one knowledge substrate** — neither forks it, so improvements compound across both:

```
  Interactive agent  ──writes──►  dev_logs / knowledge / tools / adapters / schema
        ▲                                          │
        │ reasons over                             │ absorbed by
        │ run journals + REPORT.md                 ▼
  Autonomous agent  ◄──reads/writes──  catalog + RAG (LanceDB) + run journals
```

The interactive agent builds framework code and adapters, writes engineering logs, curates `memory/knowledge/`, and builds shared tools; the autonomous orchestrator's catalog and RAG absorb that knowledge and apply it inside a pipeline run, while emitting run journals and a `REPORT.md` the interactive agent then reasons over. A discovery made in either mode is available to the other on the next run.

## Human-in-the-loop checkpoints

During development the orchestrator checkpoints — and you, the interactive agent, confirm — at: (a) data-source selection, (b) schema additions, (c) model hyperparameter choices, (d) an independent review pass, and (e) the final report. Human approval advances past each. In the autonomous mode these human-in-the-loop checkpoints are configurable per run (each can be enabled or disabled); with all disabled, the autonomous mode runs fully hands-off, relying on the automated safeguards and an always-on automated review pass that records its findings regardless of whether a human gate is enabled. Independent of the toggles, always confirm before destructive or hard-to-reverse actions, and before anything outward-facing (publishing to a public mirror, sending data to an external service), unless the run config explicitly pre-authorizes it.

## Guardrails

- Never assert a dataset, parameter, or mechanism without checking the source of truth (rules 1–2, 5).
- Raw data is immutable; transforms reproduce from raw (rule 3).
- Predictions are inference, not observation (rule 4).
- Framework code stays domain-agnostic; project specifics live under `projects/<project>/` (rule 6).
- No AI attribution in commits (rule 10).
- Public-facing artifacts may carry a normal funding acknowledgment of an awarded grant (funder, office, project, or award number). Keep them otherwise project-agnostic — do not name internal program labels, pending or unawarded proposals, or strategic codenames in anything that ships to a public mirror.

---

*This is the public, harness-neutral, framework-level operating contract. For the development-repo superset (private science context, public-mirror sync workflow, host-specific paths, per-project deep context), Claude Code reads the private `CLAUDE.md` and the relevant `projects/<project>/CLAUDE.md` when present — that content is intentionally not part of this shareable file.*
