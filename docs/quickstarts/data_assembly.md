# Data Assembly Quickstart

The data-assembly capability fetches earth-science datasets from heterogeneous data centers, stages each one with full provenance, indexes it into a local DuckDB catalog, parses it into a unified observation schema, and assembles many sources into one analysis-ready table. This quickstart walks an end-to-end fetch and assembly for a fresh user.

## What it does today

Single-dataset acquisition (the `acquire()` core):

1. Fetches a dataset's whole package from its data center (open access, or with credentials where required)
2. Stages it into a **self-describing folder** — the data file(s) plus `PROVENANCE.json`, `CITATION.cff`, `README.md`, and the source's native metadata
3. Records the download in a DuckDB catalog (source, DOI, access timestamp, sha256 checksum, license) and indexes every file + variable
4. Parses the package into `Observation` records (the unified schema), each carrying full provenance
5. Validates the parsed output against the real source with a quality-control layer

Multi-dataset assembly (the `data_assembly` agent, `run()`):

6. **Discovers** which registered sources serve the requested variables (via the capability index), **assembles** them into one analysis-ready table (fetch + parse each, harmonize units to the canonical unit per variable, pool), runs **cross-source consistency** QC across the pooled set, and **writes** CSV or Parquet. Spatial and temporal scope (`bbox`, `time_range`) are **tagged** on each observation (`in_bbox`, `in_time_range`), not dropped, so the faithful set is preserved for downstream training.

## What it does not do yet

- **No grid harmonization.** `assemble()` pools observations and reconciles units, but regridding onto a common spatial grid and aligning to a canonical temporal grain (the `post_process()` step) is on the roadmap (see below).
- **No autonomous / LLM discovery.** `discover()` matches sources from an explicit list of `Variable`s. Composing those variables from a natural-language question (LLM decompose) and proposing brand-new sources to onboard is on the roadmap.

## The model: connectors and adapters

The data layer has two pieces:

- A **connector** (one per data center) owns access — authentication, search, and whole-package fetch. Connectors are named by the data center: `pangaea`, `zenodo`, `ess_dive`, `arctic_data_center`, `earthdata`.
- An **adapter** (one per dataset) owns parsing — it maps the downloaded files into `Observation` records and declares which `Variable`s it serves. Adapters are named by the dataset's `dataset_id` (a stable lowercase slug, `<owner>[_<year>]_<descriptor>`, e.g. `webb_2026_alaska_thaw_db`).

One `acquire()` call (and the `e2sa acquire` CLI) drives the whole path — fetch via the connector, index, and optionally parse — and is the single entry point for both agent modes.

## Install

If you have not already:

```bash
git clone https://github.com/jingtao-lbl/E2SA.git
cd E2SA
python3.12 -m venv e2sa_env
source e2sa_env/bin/activate
pip install -e ".[dev]"
pytest -q
```

The open-access sources below need no extra dependencies. NASA Earthdata additionally needs `pip install -e ".[earthdata]"` and a login (see Credentials).

## Datasets you can fetch today

| `dataset_id` | Data center (connector) | Variables served | Credentials |
|---|---|---|---|
| `calm_alt` | PANGAEA | active layer thickness | none (open) |
| `gtnp_magt` | PANGAEA | ground temperature | none (open) |
| `webb_2026_alaska_thaw_db` | Zenodo | thaw-event labels | none (open) |
| `kanevskiy_2024_cryostratigraphy` | NSF Arctic Data Center | excess ice content | none (open) |
| `sloan_2014_barrow_soil` | ESS-DIVE | soil temperature | download open; *search* needs `ESS_DIVE_TOKEN` |
| `above_stdm` | NASA Earthdata | active layer thickness, volumetric water content | `~/.netrc` Earthdata login + `.[earthdata]` |

For a connector-backed adapter the `source_id` equals the `dataset_id`, so `--source` and `--dataset` take the same slug.

## Fetch a dataset from the command line

```bash
# CALM active layer thickness (PANGAEA, open access, ~1 MB)
e2sa acquire --source calm_alt --dataset calm_alt --project spade --parse
```

| Flag | Meaning | Default |
|---|---|---|
| `--source SLUG` | adapter / source id (the `dataset_id` slug) | required |
| `--dataset SLUG` | dataset id the adapter knows (same slug) | required |
| `--project NAME` | resolves the on-disk data tree (`projects/<project>/data/{raw,catalog.duckdb}`) | one of `--project` / `--raw-dir` required |
| `--raw-dir DIR` | top-level raw dir; overrides `--project` | — |
| `--catalog FILE` | DuckDB catalog file; overrides the project default | — |
| `--parse` | also parse the dataset and ingest `Observation`s | off |

The fetch is **idempotent**: if the package is already on disk and verifies, it is not re-downloaded.

## The self-describing folder

After the fetch, the dataset folder is data **plus** provenance, never a bare file:

```
projects/spade/data/raw/pangaea/calm_alt/
├── <CALM data file(s)>
├── PROVENANCE.json     # source, DOI, citation, sha256, license, coverage, variables
├── CITATION.cff        # how to cite (the source's own citation, verbatim)
├── README.md           # human-readable summary
└── metadata.txt        # the source's native metadata, captured as-is
```

`raw/<data_center>/<dataset_id>/` is the layout: the connector owns the data center directory. (See `docs/design/18` for the full convention.)

## Inspect the catalog

```bash
# Structured summary: datasets, files, variables, observation counts
e2sa catalog inspect --catalog projects/spade/data/catalog.duckdb

# Which datasets contain a given variable
e2sa catalog query --variable soil_temperature --catalog projects/spade/data/catalog.duckdb
```

## Python API

The recommended entry point is `acquire()` — fetch, index, and (optionally) parse in one call:

```python
from e2sa.orchestrator import acquire

result = acquire(
    source_id="calm_alt",
    dataset_id="calm_alt",
    project="spade",
    parse=True,
)
print(f"{result.n_observations_ingested:,} observations ingested")
```

To work with the lower-level adapter directly (e.g. to inspect `Observation` records without the catalog):

```python
from e2sa.data.adapters.calm_alt import CALMAdapter

adapter = CALMAdapter(raw_dir="projects/spade/data/raw")
fetch_result = adapter.fetch("calm_alt")          # connector-backed; stages the package
observations = adapter.parse_to_schema(fetch_result)

for obs in observations[:5]:
    print(obs.obs_id, obs.variable.value, obs.value, obs.unit, obs.depth_m)
```

Each `Observation` carries a `provenance` record (source URL, access timestamp, sha256 checksum, license, adapter + schema version) so every row is auditable back to its source.

## Assemble multiple datasets (the data_assembly agent)

`acquire()` fetches one dataset. The `data_assembly` agent runs the full chain over *many* sources at once: it discovers which sources serve the variables you ask for, assembles and unit-harmonizes them into one pooled table, runs cross-source consistency QC, and writes the result.

```python
from e2sa.agents.data_assembly import DataAssemblyAgent, AssemblyRequest, TargetFormat
from e2sa.config import RunConfig
from e2sa.schema import Variable

agent = DataAssemblyAgent(RunConfig(project="spade"))
request = AssemblyRequest(
    question="ground temperature across Alaska",
    variables=[Variable.GROUND_TEMPERATURE],   # discover() finds gtnp_magt, tsp_*, ...
    bbox=(-168.0, 54.0, -130.0, 72.0),         # tags extra["in_bbox"]; does not drop rows
    time_range=("2016", "2024"),               # tags extra["in_time_range"]; omit = keep all
    target_format=TargetFormat.PARQUET,
)
result = agent.run(request)   # discover -> screen -> assemble -> post_process -> write_format
print(result.n_observations, "observations from", result.datasets_assembled)
print(result.qc_flags)        # cross_source_warnings, unit_contract_problems, ...
print(result.output_paths)    # projects/spade/data/processed/assembled_observations.parquet
```

`bbox` and `time_range` are optional: omit them and every observation the sources hold is kept (they only add `in_bbox` / `in_time_range` tags, they never filter). `screen()` auto-accepts all discovered candidates in this non-interactive default; a human source-selection checkpoint is on the roadmap.

## Analyze the assembled data in a notebook

Once data is in the catalog, analysis happens in **per-run Jupyter notebooks** (the notebook-first execution policy). Scaffold a run first, then work inside its `notebooks/` directory:

```bash
e2sa init spade my_analysis        # creates projects/spade/runs/my_analysis/
```

This seeds `RESEARCH_PLAN.md` (the run's question, data sources, method, success criteria), `REPORT.md` (findings), a `run.yaml` manifest, and `notebooks/` + `figures/`. (The `run_id` names the *analysis*, not a dataset.) In a notebook cell, load the assembled data the same way `acquire()` does — through the adapter — and analyze it:

```python
import pandas as pd
from e2sa.data.adapters.webb_2026_alaska_thaw_db import AlaskaThawDBAdapter

adapter = AlaskaThawDBAdapter(raw_dir="projects/spade/data/raw")
obs = adapter.parse_to_schema(adapter.fetch("webb_2026_alaska_thaw_db"))
df = pd.DataFrame([{"lat": o.latitude, "lon": o.longitude, "value": o.value, **o.extra} for o in obs])
df.head()
```

Notebooks are committed **with their saved outputs**, and executed in place rather than from a generator script:

```bash
jupyter nbconvert --to notebook --execute --inplace \
    --ExecutePreprocessor.kernel_name=e2sa_env \
    projects/spade/runs/my_analysis/notebooks/<notebook>.ipynb
```

`e2sa validate <run_id>` then checks the run (skeleton complete, notebook outputs saved, no secrets, provenance complete) before it is called done. Map and figure rendering need the geospatial extra (`pip install -e ".[geo]"`); notebook execution needs `nbconvert` + `ipykernel`. There is no automated notebook launcher yet — runs are authored and executed interactively (the autonomous orchestrator loop is on the roadmap).

## Credentials

Most sources are open. Two need setup:

- **NASA Earthdata** (`above_stdm`). Create a free account at `https://urs.earthdata.nasa.gov/`, add a `~/.netrc` line `machine urs.earthdata.nasa.gov login <user> password <pass>` (`chmod 600 ~/.netrc`), and `pip install -e ".[earthdata]"`. The `earthaccess` import is lazy, so the other five sources work without it.
- **ESS-DIVE** (`sloan_2014_barrow_soil`). Downloads are open; only programmatic *search* needs an `ESS_DIVE_TOKEN` (an ORCID-backed JWT, ~18 h TTL) in the environment.

Never commit a credential. See `docs/design/05_agent_credentials.md`.

## Validate an adapter's output

The quality-control layer (`e2sa/qc`) checks parsed observations against the real source, not against assumptions:

```python
from e2sa.qc import validate_observations, summarize_distributions

findings = validate_observations(adapter.serves, observations)
for f in findings:
    print(f.severity, f.check, f.message)

print(summarize_distributions(observations))   # min/median/max + depth coverage per variable
```

The checks cover: `serves` ⊆ what is actually emitted (no over-declared variable), value ranges (catching missing-value sentinels, unit mislabels, and sign errors), subsurface depth presence, a self-describing-folder check, and a citation-not-synthesized guard. In an interactive (Claude Code) session, the **`e2sa-audit-adapter`** skill runs these on a real parse, cross-checks the source, and proposes source-grounded fixes.

## Add a new data source

Onboarding a source is three skills, in order, in an interactive session:

1. **`e2sa-add-data-source`** — inspect the source (format, metadata standard, CRS, sentinels, license, citation) and write a source card under `projects/<project>/data/sources/`.
2. **`e2sa-add-connector`** — if the data center has no connector yet, write one (auth + search + whole-package fetch).
3. **`e2sa-add-adapter`** — write the connector-backed adapter (parse + `serves`), register it, add a fixture + test.

Without skills, the contracts are in `e2sa/data/base.py` (`BaseAdapter`) and `e2sa/data/connector.py` (`BaseConnector`); register adapters in `e2sa/data/registry.py`.

## Where things are stored

- **Raw packages**: `projects/<project>/data/raw/<data_center>/<dataset_id>/` (gitignored; immutable — never edited)
- **Catalog**: `projects/<project>/data/catalog.duckdb` (gitignored)
- Raw data is never redistributed through the repository; adapters fetch each source under its own license, and the source cards record how.

## Roadmap

| Capability | Status |
|---|---|
| Connectors + adapters across 5 data centers, `acquire()`, self-describing folders, DuckDB catalog | Done |
| QC checks (`e2sa/qc`) + `e2sa-audit-adapter` | Done |
| Canonical units per `Variable` + valid-range QC | Done |
| `discover()` (capability-index source matching) + `assemble()` (unit harmonize + pool + cross-source QC + CSV/Parquet write) | Done |
| `quantity_kind` (stock/state/flux) | Planned |
| `post_process()` — spatial regrid + temporal alignment onto a common analysis grid | Planned |
| LLM question-decompose (variables from a question) + autonomous source discovery + a human screen checkpoint | Planned |
| More data centers (NSIDC, AmeriFlux, MODIS/SMAP, ERA5, ASF InSAR, ArcticDEM, USGS NWIS, NOAA) | Planned |

## Troubleshooting

**`KeyError: Unknown source_id`**: the registry key is the `dataset_id` slug (e.g. `calm_alt`, not `calm`). List registered ids with `python -c "from e2sa.data.registry import ADAPTER_REGISTRY; print(sorted(ADAPTER_REGISTRY))"`.

**`earthaccess is required for Earthdata downloads`**: run `pip install -e ".[earthdata]"` and set up `~/.netrc` (see Credentials). Only `above_stdm` needs this.

**`ESS_DIVE_TOKEN env var is not set`**: only ESS-DIVE *search* needs it; a known-id fetch/download does not. Regenerate the token from your ESS-DIVE account.

**A second `acquire` re-downloads instead of using the cache**: the on-disk package failed verification (a file is missing or truncated). Delete the dataset folder and re-fetch.

## Reporting issues

For bugs or data-source requests, open an issue on the repo. Design notes are in `docs/design/` (the data-source model is `15`/`16`, self-describing folders `18`, retrieval/indexing `04`/`07`).
