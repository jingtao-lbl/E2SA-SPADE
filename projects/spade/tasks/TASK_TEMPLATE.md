---
task_id: <YYYYMMDD-site-or-region-short-purpose>
created: <YYYY-MM-DD>
requester: Jing Tao
status: requested
priority: normal                       # high | normal | low
task_type: data-assembly               # data-assembly | simulation-setup | data-and-sim-setup
deadline:                              # optional, YYYY-MM-DD
related_tasks: []
related_run: ""                        # if this task feeds an existing run, drop the run_id here
---

# <Title that names the site and the work, e.g. "Toolik Lake 2010 to 2024 forcing assembly">

## Task type

Set the `task_type` frontmatter field to one of:

- **`data-assembly`**: fetch, harmonize, and QC datasets (forcing, observations, etc.). No model-configuration artifacts. Example: "give me harmonized soil temperature observations for these sites and time period".
- **`simulation-setup`**: generate model-ready configuration artifacts (domain definition, surface dataset, parameter files, namelists, initial conditions). May or may not include underlying data assembly. Example: "set up an ELM-FATES single-point case at Kougarok with the calibrated 2024 parameter set".
- **`data-and-sim-setup`**: both. Example: the [`20260521-doe-ecrp-fy26-event-catalog/`](20260521-doe-ecrp-fy26-event-catalog/) task assembles continuous 2000-2025 atmospheric forcing, per-event observations, and per-event surface datasets so downstream models can run the 26-event catalog end-to-end.

Fill in the `Work types requested` checklist below to indicate which artifact families are in scope, and skip / delete spec sections you do not need.

## Existing data check (agent populates during Step 0, leave blank when filing)

Before any download or assembly, the agent surveys local inventory and records matches here. If a request is fully covered by local data, the task may shift from "download" to "extract and harmonize". If partially covered, the task narrows to the missing pieces. Empty matches list means "fresh acquisition needed."

- [ ] `projects/spade/data/sources/README.md` scanned
- [ ] `projects/spade/data/raw/` scanned
- Matches found:
  - `<source_id>`: `<local_path>`, covers `<fraction>`, action: extract / supplement / skip

## Site or region

- Name:
- Lat (WGS84):
- Lon (WGS84):
- Elevation (m, optional):
- Existing site or source docs to consult:

## Work types requested

Check all that apply. Delete the sections below for the ones you do not need.

- [ ] Forcing data (reanalysis -> ELM netCDF)
- [ ] Surface dataset (soil + PFTs -> ELM netCDF)
- [ ] Observations (in-situ and/or satellite)
- [ ] Quality control / analysis
- [ ] Simulation setup (domain file, parameter files, namelists, initial conditions)

---

## Forcing data spec

- Reanalysis source preference: ERA5-Land | ERA5 | GSWP3v2 | CRUNCEPv7 | other:
- Variables (default = TBOT, PBOT, QBOT or RH, WIND, FSDS, FLDS, PRECTmms, ZBOT):
- Time period (UTC): YYYY-MM-DD to YYYY-MM-DD
- Temporal resolution: hourly | 3-hourly | daily
- Target format: ELM single-point DATM netCDF (default) | gridded CLM netCDF | other:
- Site reference height for ZBOT (m, if known):

## Surface dataset spec

- Soil source: ELM default mksurfdata | local site measurement | SSURGO | other:
- PFT specification: list indices and weights, or "use ELM default"
- Target resolution: site-only (single column) | 0.5deg | 0.1deg | other:
- Reference period for the surface state:

## Observations spec

- Variables (one row per variable):

  | Variable | Preferred source | Time period | Notes |
  |---|---|---|---|
  | soil moisture | AmeriFlux / NEON / USDA SCAN / SMAP / ... | YYYY to YYYY |  |
  | soil temperature |  |  |  |
  | snow depth or SWE |  |  |  |
  | NDVI / LAI / GPP |  |  |  |

- Footprint: site-only | within R km of site | watershed | other:
- Output format: harmonized CSV | netCDF | both:

## QC / analysis spec

- Checks to run: range | gap | outlier | cross-source consistency | other:
- Expected outputs: flagged data | summary table | plots | brief report:
- Acceptance threshold (e.g. "fewer than 5% flagged"):

## Simulation setup spec

(For tasks with `task_type: simulation-setup` or `data-and-sim-setup`. Skip for pure `data-assembly` tasks.)

- Target model(s): ELM | ATS | ELM-FATES | ELM-MOSART | ELM+ATS | other:
- Domain definition: lat/lon bounds, compute grid spec, sub-watershed boundaries (HUC-8 / HUC-12 if applicable):
- Surface dataset source: covered by the "Surface dataset spec" section above; reference that here if needed:
- Parameter files: list non-default parameter overrides (PFT params, soil params, etc.):
- Initial conditions: required? | use model default | site-derived spin-up | other:
- Compset / case configuration: list any non-default compset, component versions, or namelist overrides:
- Output expectations: which model output variables and frequencies the downstream consumer needs:

---

## Acceptance criteria

What needs to be true for this task to be `done`. Be specific:

- The MANIFEST.md lists N files at paths under `projects/spade/data/processed/sites/<site>/`.
- Every file has a complete provenance record.
- Variable units match the ELM convention listed in `projects/spade/tasks/CLAUDE.md`.
- (etc.)

## Notes and constraints

Anything else the agent needs to know: prior datasets to reconcile with, gotchas the site is known for, hard constraints from a paper, deadline urgency, etc.
