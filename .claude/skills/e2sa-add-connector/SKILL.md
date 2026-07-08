---
name: e2sa-add-connector
description: Implement a new E2SA data-center connector (the per-data-center access layer that owns auth + search + whole-package fetch under Option C). Use when wrapping a data center not yet connected — "add a connector for X", "wrap the PANGAEA/Earthdata/Zenodo API", or when migrating an existing self-fetching adapter onto a connector. Walks the BaseConnector contract, the probe-the-API-first step, the two search patterns (server-side filter vs enrich + bbox coverage-ratio), the two fetch shapes (BagIt-zip vs file-by-file), the reusable conventions (urllib + User-Agent, raw layout, token-free reads, on-disk fast-path, manual fallback), CONNECTOR_REGISTRY registration, and the mocked-urlopen + E2E_LIVE test split. Distilled from the arctic_data_center and ess_dive connectors.
allowed-tools: [Read, Glob, Grep, Write, Edit, Bash]
---

# e2sa-add-connector

The access layer for one data center (Option C, `docs/design/15`-`16`): a `BaseConnector`
subclass that owns **auth + search + whole-package fetch**. Datasets on that center are
per-dataset **adapters** (`e2sa-add-adapter`) that set `data_center` and delegate `fetch`
here. One connector backs many adapters (PANGAEA backs both CALM and GTN-P).

Read first: `e2sa/data/connector.py` (the `BaseConnector` contract + `get_connector` +
`register_connector`), the existing connector closest to your center's shape
(`e2sa/data/connectors/arctic_data_center.py` = DataONE/BagIt; `e2sa/data/connectors/ess_dive.py`
= REST/JSON-LD, file-by-file), and the source card under `projects/<project>/data/sources/`.

## When to fire

- A data center has no connector yet and a dataset on it needs fetching.
- Migrating an existing self-fetching adapter (calm/gtnp/above/alaska_thaw_db) onto a
  connector — move its `fetch` body here, then point the adapter at it.
- NOT for the per-dataset parse — that is `e2sa-add-adapter`.

## Step 1 — probe the API FIRST (do not code blind)

Both shipped connectors needed an empirical probe before writing code; skipping it wastes
time. With `curl -A "<real User-Agent>"` (Cloudflare blocks `Python-urllib/*`):
- **Search endpoint** — find the center's dataset-search API; note the query params
  (text / bbox / time) and the response shape (does a hit carry spatial/temporal, or is it
  a thin summary needing per-package enrichment?).
- **Package/file download** — how you get the bytes (a BagIt-zip package endpoint? a
  per-file content URL list in the metadata?).
- **Auth for reads** — `curl -o /dev/null -w "%{http_code}"` the metadata/download with NO
  auth. If it returns 200, reads are open: do NOT send a token (a bearer can even break
  read endpoints, as on ESS-DIVE). Tokens are usually write-only.
Record the findings (and any auth need) in the source card / a `memory/knowledge/findings/` note.

## The contract (`e2sa/data/connector.py`)

```python
@register_connector
class XConnector(BaseConnector):
    data_center: ClassVar[str] = "x"        # the registry key + the raw-folder level
    def search(self, *, variables=None, bbox=None, time_range=None, ...) -> list[DatasetInfo]: ...
    def fetch(self, dataset_id: str) -> FetchResult: ...
```
- `__init__(raw_root)` is inherited; **`fetch` writes to `self.raw_root / self.data_center / <dataset_id>/`** (Option C layout). The connector decides `raw_root`; the adapter passes it.
- A `_KNOWN_DATASETS: dict[str, str]` maps registered `dataset_id` slug → source DOI (the slug is SPADE's name; the DOI lives in `source_url`/provenance).
- Register: the `@register_connector` decorator + one import line in `e2sa/data/connectors/__init__.py`.

## Step 2 — `search()` (pick the pattern the probe revealed)

Return `DatasetInfo`s identified by **DOI** (a discovered dataset has no SPADE slug yet).
- **(a) Server-side filter** (e.g. DataONE Solr): pass bbox/time/variable to the API
  (`arctic_data_center` uses `formatType:METADATA` + `-obsoletedBy:*` for current versions
  only); map each result doc to `DatasetInfo`.
- **(b) Thin summary → enrich + coverage filter** (e.g. ESS-DIVE): full-text query over the
  variable terms → enrich the top `candidate_pool` hits via the per-package metadata GET →
  filter by **bbox coverage-ratio** (a dataset passes only if ≥ `min_coverage` of *its own
  bbox* lies inside the query box, so global/continental-scatter datasets that merely
  overlap are dropped) + time overlap. Reuse `_bbox_coverage`/`_time_overlap` from `ess_dive`.
- If a center has no search API yet, ship `search` as a documented stub returning `[]` (the
  known-DOI fetch path does not depend on it) — but prefer wiring it, the APIs are usually open.

## Step 3 — `fetch()` (on-disk fast-path → download → fallback)

1. Resolve `dataset_id` → DOI via `_KNOWN_DATASETS` (KeyError with the known list otherwise).
2. **On-disk fast-path (idempotency):** if a valid package is already at
   `raw_root/<data_center>/<dataset_id>/`, verify + return without re-downloading
   (BagIt: `bagit.txt` + `data/`; file-by-file: an `.id_cache` sidecar of name→size).
3. **Download (the shape the probe revealed):**
   - **BagIt-zip whole-package** (`arctic_data_center`): resolve the resource-map PID →
     GET the package zip → extract to a temp dir → find the bag root → move into place.
   - **File-by-file** (`ess_dive`): GET per-package metadata → stream each `distribution`
     file → cache name→size for the fast-path.
4. Build `FetchResult` (`local_path` = package dir, `files` = every file, sha256/id
   `content_checksum`, UTC `access_timestamp`, `source_url` = the DOI URL).
5. **Manual-download fallback:** on any network/zip error, raise `FileNotFoundError` with
   the DOI + manual-download instructions, so an offline/credential-lapsed run fails loud.
6. **Capture the source's native metadata** into the dataset folder (doc 18): the publisher's
   own record, as-is. PANGAEA `/* */` header -> `metadata.txt`; a REST JSON-LD record ->
   `metadata.json`; a BagIt EML is already in the package (no-op). The connector does this
   during fetch (it has the API response). The uniform `PROVENANCE.json`/`CITATION.cff`/
   `README.md` are written separately by `acquire()` — you do not write those in the connector.

## Reusable conventions (both connectors)

- **stdlib `urllib.request` only** + a real `User-Agent` constant + `# noqa: S310`; no `requests`.
- **Reads are token-free** where the probe showed open access; keep `_require_token` only
  for a future write/upload path.
- Raw layout `raw_root/<data_center>/<dataset_id>/`; never the data center in the slug.
- `# no silent caps`: if you cap a candidate pool or drop datasets (coverage filter), it is
  documented behavior; surface counts where a caller would care.

## Step 4 — tests (mocked offline + opt-in live)

- **Connector test** (`tests/test_<center>_connector.py`): monkeypatch
  `<connector_module>.urllib.request.urlopen` with a dispatcher that serves the search
  payload + per-package metadata + file/zip bytes. Cover: registry (`get_connector`
  returns it), `fetch` download + idempotency fast-path + unknown-dataset KeyError +
  network-failure fallback, and `search` filtering (bbox/coverage). No network.
- **Opt-in live test**: `@pytest.mark.skipif(not os.environ.get("E2E_LIVE"), ...)` for the
  real search + a real download. Keep heavy downloads behind it.

## Step 5 — stage the dataset(s) canonically (the live test does NOT persist)

A live test pointed at a `mktemp` `raw_root` verifies the **code** but **does not stage
data** — the temp dir is throwaway (and often deleted). The "real test" the PI expects
includes the dataset actually landing in the project tree. After the connector + adapter
work, run a **project-aware acquire** for each dataset so it persists to
`projects/<project>/data/raw/<data_center>/<dataset_id>/` and indexes into the project
catalog:

```python
from e2sa.orchestrator import acquire
acquire("<dataset_id>", "<dataset_id>", project="spade")   # no manual path (doc 17)
```

Then confirm it is on disk (`find projects/<project>/data/raw`) and **do not delete the
canonical copy**. Use temp dirs only for isolated unit/live tests, never as the end state.

## Guardrails

- **Register** the connector (`@register_connector` + `connectors/__init__.py`) or
  `get_connector` cannot reach it.
- **Stage canonically** (Step 5): a passing live test in a temp dir is not "done" — the
  dataset must be staged into `projects/<project>/data/raw/<data_center>/<dataset_id>/`
  via a `project=` acquire, or it has not actually landed anywhere.
- `fetch` writes under `raw_root/<data_center>/<dataset_id>/`; idempotent; manual fallback on failure.
- No token for open reads; no secret in the repo; `User-Agent` always (Cloudflare).
- Offline tests mock `urlopen`; real downloads are `E2E_LIVE`-gated.
- After the connector exists, the per-dataset adapter is `e2sa-add-adapter` (set
  `data_center`, delegate `fetch`).

## Changelog
- 2026-06-23: Initial version. Distilled the connector recipe (probe-first, BaseConnector
  contract, two search patterns + two fetch shapes, urllib/UA/token-free/raw-layout
  conventions, mocked + E2E_LIVE test split) from the `arctic_data_center` and `ess_dive`
  connectors (`docs/design/15`-`16`; dev logs `20260623b`-`20260623f`).
- 2026-06-23: Added Step 5 "stage the dataset(s) canonically" + a guardrail. A live test
  in a `mktemp` raw_root verifies code but does not persist data (the temp dir is
  throwaway); the dataset must be staged via a `project=` acquire into
  `projects/<project>/data/raw/<data_center>/<dataset_id>/`. Hit twice (ess_dive Sloan,
  PANGAEA calm/gtnp) before being captured (PANGAEA dev log `20260623i`).
- 2026-06-23: Added fetch step 6 "capture the source's native metadata" (PANGAEA header ->
  metadata.txt; JSON-LD -> metadata.json; BagIt EML in-package). The uniform metadata
  bundle (PROVENANCE.json/CITATION.cff/README.md) is written by `acquire()`, not the
  connector. Per doc 18 (self-describing folders); PI: a bare data file is not acceptable.
