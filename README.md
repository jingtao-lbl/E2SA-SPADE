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
literature-review agent are designed to transfer to other regions, other
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
│   ├── data/                            Source adapters (CALM, GTN-P, ABoVE, ...)
│   ├── catalog/                         DuckDB provenance catalog
│   ├── qc/                              Quality-control checks
│   ├── harmonize/                       Geospatial harmonization
│   └── agents/litreview/                Literature-review agent (search + triage)
├── tests/                               pytest suite
├── projects/spade/
│   ├── data/sources/                    Per-source documentation cards
│   └── tasks/                           Task templates and the 26-event catalog
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

## Data source catalog

SPADE integrates eleven Arctic-data portal adapters, plus project-specific
sources catalogued under `projects/spade/data/sources/`.

### Eleven portal adapters

| # | Portal | Datasets served (examples) | v0.1.0 status |
|---|---|---|---|
| 1 | ESS-DIVE | NGEE-Arctic flux, soil thermal, vegetation, ecohydrology | roadmap |
| 2 | NSIDC | Brown 2002 ground ice map, CUSP, Olefeldt 2016 thermokarst | roadmap |
| 3 | AmeriFlux | flux-tower observations | roadmap |
| 4 | NASA Earthdata | NASA ABoVE, MODIS LST + Snow, SMAP soil moisture + freeze-thaw | shipping (ABoVE), roadmap (MODIS, SMAP) |
| 5 | Copernicus CDS | ERA5 (deprecated for ELM forcing; retained for other uses) | roadmap |
| 6 | NCAR RDA | Cheng et al. 2025 RASM-WRF 4 km | roadmap |
| 7 | NOAA AWS Open Data | HRRR-AK 3 km atmospheric forcing | roadmap |
| 8 | ASF Vertex | Sentinel-1 SAR/InSAR surface deformation | roadmap |
| 9 | USGS NWIS | streamflow at Mendenhall, Snow River, Copper River, etc. | roadmap |
| 10 | NOAA NWLON | tide gauges at Nome, Stebbins, Unalakleet, Valdez, Cordova | roadmap |
| 11 | PGC | ArcticDEM time-stamped strips | roadmap |

### Source documentation coverage (v0.1.0)

Seven source-documentation cards ship with v0.1.0; ten more land in the
v0.2+ adapter buildout, paired with the actual portal adapter
implementations.

| Source | Card | Adapter status |
|---|---|---|
| CALM Circumpolar Active Layer Monitoring | [calm.md](projects/spade/data/sources/calm.md) | shipping |
| GTN-P Global Terrestrial Network for Permafrost | [gtnp.md](projects/spade/data/sources/gtnp.md) | shipping |
| Alaska Permafrost Thaw Database (Webb et al. 2026) | [alaska_thaw_db.md](projects/spade/data/sources/alaska_thaw_db.md) | shipping |
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

An open SPADE data-preparation task is documented at
[projects/spade/tasks/20260521-doe-ecrp-fy26-event-catalog/](projects/spade/tasks/20260521-doe-ecrp-fy26-event-catalog/20260521-doe-ecrp-fy26-event-catalog.md):
assembling forcing, observations, and analysis-ready inputs for a
26-event Alaska extreme-event catalog covering the four-Region Alaska
coastal gradient, partitioned into 7 calibration events and 19 validation
events (5 benchmark + 14 non-benchmark). The task spec is the live
contract SPADE will deliver against; the catalog table, per-event
forcing-source assignments, reference list, and acceptance criteria
follow the file. The same catalog template is reusable for other
regional hazard-modeling efforts.

## Literature review agent

The `e2sa.agents.litreview` agent searches scientific literature, screens
results for relevance, verifies DOIs against CrossRef, and ingests into a
local LanceDB store with deduplication.

**Default backend** is `paper-search-mcp`, which fans out across Google
Scholar, PubMed, arXiv, bioRxiv, and medRxiv per theme. Semantic Scholar is
available as an alternative single-query backend via `--backend ss`.

```bash
# Themed search across multiple platforms (default)
python -m e2sa.agents.litreview search \
    --themes "permafrost ground ice,thermokarst Alaska,InSAR permafrost" \
    --max 5 \
    --catalog data/lance

# List what's in the local store
python -m e2sa.agents.litreview list --catalog data/lance --limit 10
```

**Scope at v0.1.0.** The agent currently covers the search and triage
stages (workflow stages 3 and 4 of a reproducible literature-review
pipeline). PDF acquisition, full-text extraction, and structured synthesis
are on the roadmap for v0.3+, not yet implemented.

## Data management

SPADE follows established practices for FAIR data and Better Scientific
Software (BSSw).

- **Findable, Accessible, Interoperable, Reusable (FAIR).** Every public
  release receives a Zenodo concept DOI from a tagged GitHub release.
  Metadata for SPADE-curated data products follows ESS-DIVE conventions.
- **Software licensing.** Source code under BSD-3-Clause (this repository).
  Documentation under CC-BY-4.0 (see License section below).
- **Data products.** SPADE-curated data products are released through
  ESS-DIVE (DOE BER data repository at LBNL) with CC-BY-4.0 licensing.
  The GitHub repository hosts source code and documentation, not data
  files; per-source data cards under `projects/spade/data/sources/`
  describe where the underlying datasets live and how to fetch them.
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

If you use SPADE in your research, please cite the Zenodo concept DOI for
the most recent release (cite-all-versions) or a specific version DOI for
reproducibility against a known code state:

```
Tao, J. (2026). SPADE: Subsurface Permafrost Autonomous Discovery Engine
(Version 0.1.0) [Software]. Zenodo. https://doi.org/<concept-doi-pending>
```

A machine-readable citation block is in [CITATION.cff](CITATION.cff). The
Zenodo DOIs are minted at first tagged release and will be populated into
`CITATION.cff`, `codemeta.json`, `.zenodo.json`, and this README at that
time.

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
`projects/spade/data/sources/`. The Alaska Permafrost Thaw Database (Webb
et al. 2026) and the CALM, GTN-P, NASA ABoVE, NGEE-Arctic, and related
networks are the foundational observation sources for the v0.1.0 release.
