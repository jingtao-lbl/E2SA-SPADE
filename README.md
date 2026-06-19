# SPADE: Subsurface Permafrost Autonomous Discovery Engine

[![License: BSD-3-Clause](https://img.shields.io/badge/License-BSD%203--Clause-blue.svg)](https://opensource.org/licenses/BSD-3-Clause)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

## Science context

**SPADE is the Subsurface Permafrost Autonomous Discovery Engine**, an
agentic data-preparation and model-simulation-setup agent for coupled
surface-subsurface Earth system workflows. It assembles permafrost
observations and forcing datasets from sparse, heterogeneous sources,
harmonizes them into a unified schema with provenance tracking, and
prepares analysis-ready inputs for downstream modeling and
machine-learning pipelines.

Give SPADE a research question or topic, and its agents are designed to
discover and assemble the relevant datasets across multiple data centers
(ESS-DIVE, the NSF Arctic Data Center, NASA Earthdata, and more), download
them with full provenance, organize them on disk, and index them for reuse,
so you start from analysis-ready data instead of assembling it by hand.

Typical use cases include:

- Producing high-resolution ground-ice content maps across Alaska
  with quantified uncertainty via a physics-constrained generative
  model. SPADE automates the permafrost surface-subsurface data
  assembly that feeds the model and the deep-learning fusion of
  sparse in-situ observations with remote sensing.
- Setting up site or regional simulations for models like ELM, ATS,
  ELM-FATES, and ELM-MOSART by assembling atmospheric forcing,
  surface datasets, and observations.
- Building calibration and validation datasets for permafrost,
  hydrology, and ecosystem modeling.
- Preparing training and evaluation data for AI/ML emulators of Earth
  system components.
- Conducting literature reviews to inform research design and dataset
  selection.

The initial source-document catalog focuses on Alaska and the pan-Arctic;
SPADE's adapter library, unified schema, DuckDB provenance catalog, and
agent pipeline are designed to transfer to other regions, other
science questions, and other coupled surface-subsurface prediction systems
with minimal additional plumbing.

## Installation

SPADE requires Python 3.12+. The geospatial stack (rasterio, geopandas)
is easier to install via Conda; pure-pip works for the core schema and
catalog only.

### Conda (recommended)

```bash
git clone https://github.com/jingtao-lbl/E2SA-SPADE.git
cd E2SA-SPADE
conda env create -f environment.yml
conda activate e2sa-spade
pip install -e .
```

### Pip + venv

```bash
git clone https://github.com/jingtao-lbl/E2SA-SPADE.git
cd E2SA-SPADE
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

### Environment variables

Copy `.env.example` to `.env` and fill in the credentials you need
(NASA Earthdata for ABoVE / MODIS / SMAP / Sentinel-1; Copernicus CDS for
ERA5; ESS-DIVE token for NGEE-Arctic search; Anthropic API key for the
literature-review agent's LLM screening). All values are optional; SPADE
adapters fall back gracefully when a credential is absent for an
optional channel.

## Quickstart

Fetch and harmonize the CALM active-layer-thickness dataset, register it in
a local DuckDB catalog, and run a single-event query:

```python
from pathlib import Path
from e2sa.catalog import open_catalog
from e2sa.data.calm import CALMAdapter

# Open (or create) a local DuckDB catalog
catalog = open_catalog(Path("./data/catalog.duckdb"))

# Fetch the PANGAEA CALM dataset (small, ~1 MB)
adapter = CALMAdapter()
observations = adapter.parse_to_schema(adapter.fetch(catalog=catalog))

# Inspect the first few rows
for obs in observations[:5]:
    print(obs.site_id, obs.time_start, obs.value, obs.unit)
```

Each `Observation` carries provenance (source URL, access timestamp,
sha256 checksum, license) so downstream consumers can audit every row back
to its upstream source.

## Repository structure

```
E2SA-SPADE/
├── e2sa/                                Vendored E2SA framework slice
│   ├── schema.py                        Unified pydantic observation schema
│   ├── config.py                        Run configuration
│   ├── data/                            Source adapters (CALM, GTN-P, ABoVE,
│   │                                      ESS-DIVE, ...) + indexing + registry
│   ├── catalog/                         DuckDB provenance catalog
│   ├── qc/                              Quality-control checks
│   ├── harmonize/                       Geospatial harmonization
│   ├── rag/                             LanceDB vector store
│   ├── agents/litreview/                Literature-review agent (search + triage)
│   └── orchestrator.py                  Autonomous-mode driver (acquire())
├── e2sa_cli/                            `e2sa` CLI (acquire, catalog, init, ...)
├── .claude/skills/                      Interactive-agent skills
├── AGENTS.md                            Interactive-agent operating contract
├── CONTRIBUTING.md                      Contributor guide
├── tests/                               pytest suite + fixtures
├── projects/spade/
│   ├── data/sources/                    Per-source documentation cards
│   └── tasks/                           Task templates
├── LICENSE
├── README.md                            (this file)
├── CITATION.cff
├── codemeta.json
├── .zenodo.json
├── pyproject.toml
├── environment.yml
└── requirements.txt
```

The vendored `e2sa/` slice contains the SPADE-relevant subset of the parent
E2SA framework. When the E2SA framework lands as its own public repository,
SPADE will switch from vendoring to a pip dependency.

The layout supports both agent modes: the autonomous mode runs through
`e2sa/orchestrator.py` and the `e2sa` CLI (`e2sa_cli/`), while the interactive
mode operates against `AGENTS.md` (the operating contract) and `.claude/skills/`.

## Data source catalog

SPADE integrates twelve Arctic-data portal adapters, plus project-specific
sources catalogued under `projects/spade/data/sources/`.

### Twelve portal adapters

| # | Portal | Datasets served (examples) | status |
|---|---|---|---|
| 1 | ESS-DIVE | NGEE-Arctic flux, soil thermal, vegetation, ecohydrology | roadmap |
| 2 | NSF Arctic Data Center | Kanevskiy 2024 cryostratigraphy / ground-ice cores | roadmap |
| 3 | NSIDC | Brown 2002 ground ice map, CUSP, Olefeldt 2016 thermokarst | roadmap |
| 4 | AmeriFlux | flux-tower observations | roadmap |
| 5 | NASA Earthdata | NASA ABoVE, MODIS LST + Snow, SMAP soil moisture + freeze-thaw | shipping (ABoVE), roadmap (MODIS, SMAP) |
| 6 | Copernicus CDS | ERA5 (deprecated for ELM forcing; retained for other uses) | roadmap |
| 7 | NCAR RDA | Cheng et al. 2025 RASM-WRF 4 km | roadmap |
| 8 | NOAA AWS Open Data | HRRR-AK 3 km atmospheric forcing | roadmap |
| 9 | ASF Vertex | Sentinel-1 SAR/InSAR surface deformation | roadmap |
| 10 | USGS NWIS | streamflow at Mendenhall, Snow River, Copper River, etc. | roadmap |
| 11 | NOAA NWLON | tide gauges at Nome, Stebbins, Unalakleet, Valdez, Cordova | roadmap |
| 12 | PGC | ArcticDEM time-stamped strips | roadmap |

### Source documentation coverage

Each documented source has a card below; the Adapter status column tracks
which sources have a working adapter. New cards are added as sources are
onboarded, paired with their portal adapter implementations.

| Source | Card | Adapter status |
|---|---|---|
| CALM Circumpolar Active Layer Monitoring | [calm.md](projects/spade/data/sources/calm.md) | shipping |
| GTN-P Global Terrestrial Network for Permafrost | [gtnp.md](projects/spade/data/sources/gtnp.md) | shipping |
| Alaska Permafrost Thaw Database (Webb et al. 2026) | [alaska_thaw_db.md](projects/spade/data/sources/alaska_thaw_db.md) | shipping |
| Kanevskiy 2024 cryostratigraphy / ground-ice cores (NSF Arctic Data Center) | [kanevskiy_cryostratigraphy.md](projects/spade/data/sources/kanevskiy_cryostratigraphy.md) | roadmap |
| NASA ABoVE products via ORNL DAAC | [above.md](projects/spade/data/sources/above.md) | shipping |
| Brown et al. 2002 Circum-Arctic Map of Permafrost and Ground-Ice Conditions | [permafrost_ground_ice_map.md](projects/spade/data/sources/permafrost_ground_ice_map.md) | roadmap |
| Olefeldt et al. 2016 circumpolar thermokarst map | [thermokarst_circumpolar.md](projects/spade/data/sources/thermokarst_circumpolar.md) | roadmap |
| UAF GIPL Permafrost Lab (Tao et al. 2017) | [gipl_uaf_permafrost.md](projects/spade/data/sources/gipl_uaf_permafrost.md) | roadmap (ESS-DIVE deposit pending) |
| NGEE-Arctic via ESS-DIVE | [ngee_arctic.md](projects/spade/data/sources/ngee_arctic.md) | roadmap |
| CommUnity near-Surface Permafrost (CUSP) | [cusp.md](projects/spade/data/sources/cusp.md) | roadmap |

Each card documents the source's role in SPADE, access endpoints (DOI, URL,
authentication), variables and units, spatial and temporal coverage, format,
known gotchas, and adapter design notes. The cards are the contract between
the upstream source and any SPADE adapter built against it.

### Tasks

`projects/spade/tasks/` is a drop-box for data-preparation requests. To start
a job, add a task folder with a spec (copy
[tasks/TASK_TEMPLATE.md](projects/spade/tasks/TASK_TEMPLATE.md)): the spec
scopes what to assemble (atmospheric forcing, surface datasets, observations,
or QC/analysis), and the same folder is where progress is tracked. SPADE picks
up the task, prepares the data, and reports back through a status file in the
folder.

A worked example ships at
[projects/spade/tasks/20260521-doe-ecrp-fy26-event-catalog/](projects/spade/tasks/20260521-doe-ecrp-fy26-event-catalog/20260521-doe-ecrp-fy26-event-catalog.md):
assembling forcing, observations, and analysis-ready inputs for an Alaska
extreme-event catalog spanning the state's coastal gradient, partitioned into
calibration and validation events for hazard-modeling experiments. Use it as a
template for authoring your own tasks.

## Agents

SPADE is designed as a multi-agent pipeline: an orchestrator plus specialist
agents for literature review, data discovery, retrieval, harmonization,
quality control, and generative model development for permafrost mapping.

It runs in two modes that share one substrate (the DuckDB catalog, the vector
store, the skills, and the run journal), so discoveries compound across both:

- **Autonomous mode** drives the pipeline from a run configuration through the
  orchestrator (`e2sa.orchestrator`) and the `e2sa` CLI, with configurable
  human-in-the-loop checkpoints.
- **Interactive mode** is a coding-agent harness operating in the repository,
  guided by `AGENTS.md` and the skills under `.claude/skills/`, for the
  open-ended work a fixed pipeline cannot cover.

## Data management

SPADE follows established practices for FAIR data and Better Scientific
Software (BSSw).

- **Findable, Accessible, Interoperable, Reusable (FAIR).** Every public
  release receives a Zenodo concept DOI from a tagged GitHub release.
  Metadata for SPADE-curated data products follows ESS-DIVE conventions.
- **Software licensing.** Source code under BSD-3-Clause (this repository).
  Documentation under CC-BY-4.0 (see License section below).
- **Data products and third-party datasets.** This repository hosts source
  code and documentation, not data. SPADE does not redistribute third-party
  datasets through GitHub unless a dataset's license explicitly permits
  redistribution. Instead, adapters download each source into a gitignored
  local `projects/spade/data/raw/` tree, and the per-source cards under
  `projects/spade/data/sources/` record each dataset's origin, license, and
  fetch instructions, so users retrieve the data themselves under its own
  terms. **Cite each dataset using its own required citation, recorded in its
  source card, when you use it.** SPADE-curated derived products that are cleared for release are
  published through ESS-DIVE (DOE BER data repository at LBNL) under
  CC-BY-4.0.
- **Best practices.** SPADE follows Better Scientific Software practices
  (https://bssw.io/): public GitHub repository, branch protection on
  `main`, versioned environment specifications, DuckDB provenance for
  every harmonized observation row.

## License

Source code in this repository, including Python scripts and tests, is
released under the BSD-3-Clause License (SPDX: `BSD-3-Clause`).
Documentation and narrative materials, including README files, model
cards, event-catalog descriptions, and project notes, are released under
CC-BY-4.0 (SPDX: `CC-BY-4.0`). Metadata files such as `CITATION.cff`,
`codemeta.json`, and `.zenodo.json` follow the repository software
license unless otherwise stated.

The full text of the BSD-3-Clause license is in [LICENSE](LICENSE). The
CC-BY-4.0 license text is at https://creativecommons.org/licenses/by/4.0/legalcode.

## Citation

If you use SPADE in your research, please cite the Zenodo **concept DOI**
(`10.5281/zenodo.20457346`). It is the cite-all-versions DOI and always
resolves to the latest release:

```
Tao, J. (2026). SPADE: Subsurface Permafrost Autonomous Discovery Engine.
Zenodo. https://doi.org/10.5281/zenodo.20457346
```

When reproducibility against a specific code state is required, cite the
per-version DOI instead. For v0.2.0:

```
Tao, J. (2026). SPADE: Subsurface Permafrost Autonomous Discovery Engine
(v0.2.0). Zenodo. https://doi.org/10.5281/zenodo.20755471
```

A machine-readable citation block is in [CITATION.cff](CITATION.cff).

## Contributing

Contributions are welcome. Please open an issue to discuss substantial
changes before sending a pull request. Standard pytest test suite under
`tests/`; run `pytest -q` to verify before submitting.

For bug reports or data-source requests, open an issue at
https://github.com/jingtao-lbl/E2SA-SPADE/issues.

## Acknowledgments

SPADE is developed at Lawrence Berkeley National Laboratory. It builds on
the parent E2SA (End-to-End Science Agent) framework and on the earlier
A2MC (Agentic Adaptive Multi-target Calibration) work at
https://github.com/jingtao-lbl/A2MC-elm.

Upstream data sources are credited in the per-source cards under
`projects/spade/data/sources/`.

## Funding

This work was supported by the DOE BER NGEE-Arctic project.
