# SPADE Tasks

Drop-box for site-simulation data-preparation requests. The agent picks tasks up from this folder, prepares the requested data (forcing, surface dataset, observations, or QC/analysis), and reports back through a status file in the same task folder.

Tasks are scoped to **data preparation for site simulations**, primarily ELM-FATES runs. Science questions and analyses belong in `projects/spade/runs/<run_id>/` (scaffolded by `e2sa init spade <run_id>`), not here.

## When to file a task here

Use this folder when you need any of the four work types below. Mix and match as needed in a single task.

1. **Forcing data.** Download or extract reanalysis fields (air temperature, surface pressure, wind, specific or relative humidity, downward shortwave and longwave radiation, precipitation) for a site or region and prepare them as ELM-readable netCDF (DATM-style single-point or CLM-style gridded).
2. **Surface datasets.** Prepare an ELM surface-dataset netCDF for the site (soil texture, soil organic matter, PFT composition and weights, lake fraction, glacier fraction, urban fraction). **For permafrost sites:** initial ground ice content profile (Brown et al. 2002 circum-Arctic ground ice map, Ran et al. 2022 NIEER 1 km dataset), permafrost extent and probability, soil thermal regime initialization (active layer depth from CALM, mean annual ground temperature from GTN-P). Source from ELM defaults or override with site-specific measurements.
3. **Observations.** Acquire and harmonize observations for the site. **Permafrost variables are first-class for SPADE:** active layer thickness (CALM 60 Alaska sites, ABoVE modeled ALT), ground temperature profiles and mean annual ground temperature (GTN-P boreholes, GIPL-UAF 344-site network), ice content and ground-ice classification (Brown 2002 circum-Arctic map), thaw event locations (Webb 2026 Alaska Permafrost Thaw DB, 19,540 labeled points), thermokarst features (Olefeldt 2016 circumpolar map), freeze-thaw timing. Also covers the standard land-surface variables: soil moisture, soil temperature at depth, snow depth or SWE, vegetation indices (NDVI, LAI, GPP), fluxes (latent / sensible / NEE / CH4) from in-situ networks (AmeriFlux, FluxNet, USDA SCAN, NEON) and satellite products (MODIS, SMAP, Sentinel, Landsat).
4. **Quality control and analysis.** Range checks, gap detection, outlier flags, cross-source consistency, basic descriptive plots and summary tables for any of the above. For permafrost variables specifically: comparing existing ground ice maps (Brown 2002 vs Webb 2026-derived thaw signatures) at site locations, identifying disagreement regions, sanity-checking ALT against CALM ground truth.

## Two ways tasks get filed

**You file one** when you know the site simulation needs prep work. See "How to file a task" below.

**The agent files one** when it is doing other work (scaffolding a new run, scoping a research-question entry, drafting a manuscript figure) and recognizes that the work needs site data that is not already prepared. Agent-filed tasks carry `requester: agent` in the frontmatter and never auto-execute. The agent files the task, sets status to `requested`, surfaces it to you, and waits for your direction. You decide whether to flip the status to `in_progress` (agent proceeds), `revise` (you edit the spec first), or `cancel`. The rules live in `.claude/skills/e2sa-file-task/SKILL.md` and `memory/knowledge/methods/20260521-when-to-file-a-data-prep-task.md`.

Either way, the lifecycle and folder structure below are the same.

## Step 0: Check what is already here (before filing anything)

Before filing a task, scan the existing SPADE data inventory. Twelve source docs under `projects/spade/data/sources/` already catalogue the permafrost-relevant datasets we have on disk or have access to. [`projects/spade/data/sources/README.md`](../data/sources/README.md) is the index. Browse it once before requesting anything that might already exist.

Inventory at a glance:

| Category | Already catalogued |
|---|---|
| Active layer thickness | CALM (60 AK sites, 1991-present, [`calm.md`](../data/sources/calm.md)); ABoVE modeled ALT ([`above.md`](../data/sources/above.md)) |
| Ground / soil temperature | GTN-P boreholes ([`gtnp.md`](../data/sources/gtnp.md)); GIPL-UAF 344-site network ([`gipl_uaf_permafrost.md`](../data/sources/gipl_uaf_permafrost.md)) |
| Ice content / ground ice | Brown et al. 2002 circum-Arctic map ([`permafrost_ground_ice_map.md`](../data/sources/permafrost_ground_ice_map.md)) |
| Thaw event labels | Alaska Permafrost Thaw DB (Webb 2026, 19,540 pts, downloaded 2026-05-20 to `data/raw/alaska_thaw_db/`, registered in catalog, [`alaska_thaw_db.md`](../data/sources/alaska_thaw_db.md)) |
| Thermokarst features | Olefeldt 2016 circumpolar map ([`thermokarst_circumpolar.md`](../data/sources/thermokarst_circumpolar.md)) |
| Multi-product Arctic | NASA ABoVE / ORNL DAAC (17+ products); NGEE-Arctic (hundreds of datasets at Kougarok, Council, Teller, Barrow/Utqiagvik, Atqasuk via ESS-DIVE, [`ngee_arctic.md`](../data/sources/ngee_arctic.md)) |

If your request can be satisfied by extracting from a local copy, say so in `<task_id>.md` and the agent will skip the download step. If the source is catalogued but not yet downloaded, the task is download + ingest. If the source is not catalogued at all, the task starts with a new entry in `data/sources/`.

## How to file a task

Create a subdirectory under this folder named with the dash convention `<YYYYMMDD>-<site-or-region>-<short-purpose>`, then drop a `<task_id>.md` inside it.

```bash
mkdir -p projects/spade/tasks/20260521-toolik-lake-forcing
$EDITOR projects/spade/tasks/20260521-toolik-lake-forcing/20260521-toolik-lake-forcing.md
```

Use the template in [`TASK_TEMPLATE.md`](TASK_TEMPLATE.md) (next to this README). Only fill in the sections that apply to your task.

## Task lifecycle

```
projects/spade/tasks/<task_id>/
|-- <task_id>.md          # request spec, you write this
|-- STATUS.md        # progress log, the agent writes and updates this
|-- MANIFEST.md      # what was produced and where it lives (paths + sha256), agent writes at the end
`-- notes/           # optional: agent-written notes, intermediate plots, clarifications
```

Status field on `<task_id>.md`'s frontmatter moves through: `requested` -> `needs_clarification` (agent has questions) -> `in_progress` (agent has started) -> `blocked` (waiting on access, credentials, or upstream) -> `done` (MANIFEST.md present and reviewable) -> `accepted` (you have confirmed the deliverable).

## Where the data actually lands

The task folder stays lightweight (markdown only, gittable). The data deliverables themselves live under the existing SPADE data tree, which is gitignored:

| Deliverable kind | Lives under |
|---|---|
| Raw downloads from upstream | `projects/spade/data/raw/<source>/` |
| Reproducible intermediates | `projects/spade/data/interim/<task_id_or_site>/` |
| Analysis-ready ELM-shape netCDF | `projects/spade/data/processed/sites/<site_slug>/` |

`MANIFEST.md` in the task folder records the produced paths with checksums, so the task folder is a complete provenance record even though the bytes live elsewhere.

## What a good task looks like

Minimum viable: site name, lat/lon, time period, list of variables, source preference, target format, acceptance criteria. The smaller the ask, the faster it ships.

For a worked example, see [`20260521-doe-ecrp-fy26-event-catalog/`](20260521-doe-ecrp-fy26-event-catalog/). That task covers all four work types (forcing, surface dataset, observations, QC) across 26 Alaska extreme-event windows and is the canonical citable source for the 26-event catalog.

## Public visibility

The SPADE repository is moving toward public release. When a task is filed here, assume the task file may become publicly visible. Treat the task file as a citable artifact:

- Use real, verifiable references (DOI, peer-reviewed source URL, or government / institutional gray-literature URL). Avoid TBD-VERIFY-style placeholders in published task content; mark unresolved citations explicitly as "preliminary citation pending verification" and name the candidate sources.
- Avoid internal jargon that would not generalize to an external reader. Use full names on first occurrence (for example, "Active Layer Thickness" before abbreviating to ALT, "Mean Annual Ground Temperature" before MAGT).
- Do not include unpublished collaborator or program-officer correspondence unless that material is already public.
- Apply the global no-em-dashes rule throughout. Use commas, periods, or parentheses instead.
- "Climate" is allowed in task text if it appears in cited paper titles. For task body prose, prefer "weather and environmental extremes," "Earth system," or "land-atmosphere exchange" if there is a downstream proposal-narrative constraint to respect.

The worked example above demonstrates this style (real citations with DOIs, preliminary-citation tags where peer-reviewed sources are pending, public-facing context that a citing reader can follow without internal docs).

## Relationship to other E2SA pieces

- **Sources docs** at `projects/spade/data/sources/<source>.md` are the canonical "what is this source, how does its adapter work, what are the gotchas" reference. Cite them in `<task_id>.md` when relevant.
- **Adapters** at `e2sa/data/<source>.py` are where the actual download and parsing happens. Tasks should drive these, not bypass them. If an adapter is missing for a source you need, the task should either request the adapter as a deliverable or note that a new adapter is required.
- **Lessons layer** at `memory/knowledge/lessons/`. Operational quirks the agent hits while running a task get captured here (per `.claude/skills/e2sa-lessons-capture/SKILL.md`) so future tasks against the same source don't re-trip the same wires.
- **Methods layer** at `memory/knowledge/methods/`. Reusable how-tos that emerge from tasks (e.g. "how to bias-correct ERA5 against AmeriFlux 2 m air temperature") get promoted here.
- **Runs** at `projects/spade/runs/<run_id>/`. When a task's deliverable becomes the data substrate for a science question, the next step is `e2sa init spade <run_id>` and writing a `RESEARCH_PLAN.md`. Reference the originating task in the plan's data-sources section.
