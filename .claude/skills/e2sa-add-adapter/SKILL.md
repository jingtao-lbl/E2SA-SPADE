---
name: e2sa-add-adapter
description: Implement a new E2SA data-source adapter (the code that fetches a source and parses it into Observation records). Use when writing the adapter for a source that has already been onboarded/inspected — "build the adapter for X", "write the X adapter", "implement the fetch/parse for X", or the coding step after e2sa-add-data-source. Walks the BaseAdapter contract (list_available / fetch / parse_to_schema), the FetchResult single-file-vs-whole-package shape, the Observation + Provenance schema, canonical units + depth + serves, ADAPTER_REGISTRY registration, the fixture + test, and the parse gotchas already learned (sentinels, CRS tiers, obs_id uniqueness, schema drift, idempotency).
allowed-tools: [Read, Glob, Grep, Write, Edit, Bash]
---

# e2sa-add-adapter

The coding step for bringing a source into SPADE: implement a `BaseAdapter` subclass that emits `Observation` records, and wire it in. This is the *downstream* half of onboarding — `e2sa-add-data-source` does the look-first inspection + source card; this skill writes the adapter. Distilled from the six existing adapters (`calm`, `gtnp`, `alaska_thaw_db`, `above`, plus the connector-backed `sloan_2014_barrow_soil` and `kanevskiy_2024_cryostratigraphy`) and the lessons they cost.

**Option C default (read this first).** A dataset on a data center that has a **connector** (`e2sa/data/connectors/`) is a *connector-backed* adapter: it sets `data_center`, **delegates `fetch` to the connector**, and owns only `parse_to_schema` + `serves`. Its `source_id` IS the `dataset_id` slug (`<owner>[_<year>]_<descriptor>`, `docs/design/15` §9). If the center has **no connector yet**, write it first with **`e2sa-add-connector`** (and see "Migrating an existing adapter" below). Only legacy/standalone sources still do their own `fetch`.

Read first: `e2sa/data/base.py` (the contract), `e2sa/schema.py` (`Observation`, `Variable`, `CANONICAL_UNITS`), one existing adapter closest to your source shape, and the source card under `projects/<project>/data/sources/`.

## When to fire

- A source is onboarded (source card exists) and now needs its adapter.
- The human says "build/write the X adapter" or "implement fetch/parse for X".
- NOT for the inspection/source-card step — that is `e2sa-add-data-source`.

## The interfaces (the contract you implement)

**`BaseAdapter`** (`e2sa/data/base.py`) — set two class attrs and implement three methods:
- `source_id: str` — matches the source card. (Under Option C the raw folder keys on the data center, `raw/<data_center>/<dataset_id>/`, not on `source_id`; connector-backed adapters also set `data_center` and delegate `fetch`.)
- `adapter_version: str`.
- `serves: ClassVar[frozenset[Variable]]` — the `Variable`s this adapter emits (the capability index routes on it; MUST be a subset of what `parse_to_schema` actually emits).
- `data_center: ClassVar[str | None]` — set it for a connector-backed adapter (the connector key); leave None only for a legacy standalone source.
- `list_available() -> list[DatasetInfo]` — what datasets/variables the source offers.
- `fetch(dataset_id) -> FetchResult` — **connector-backed (the default): do NOT write a `fetch` method.** `BaseAdapter.fetch` already delegates to your `data_center` connector (which writes `raw_dir/<data_center>/<dataset_id>/`). **Legacy standalone (no connector):** override `fetch` to download to `self.raw_dir`.
- `parse_to_schema(fetch_result) -> list[Observation]` — raw files → `Observation` records (the adapter's real job).

**`DatasetInfo`** (returned by `list_available`): `dataset_id`, `name`, `description`, `variables: list[str]`, `spatial_coverage`, `temporal_coverage`, `format`, `url`, `license`, `extra`.

**`FetchResult`** (returned by `fetch`): `dataset_id`, `local_path`, `bytes_downloaded`, `access_timestamp` (UTC), `content_checksum` (sha256), `source_url`, `files: list[Path]`. **Two shapes:** single-file (CALM/GTN-P/Alaska-Thaw/ABoVE) leaves `files` empty and `local_path` is the file; whole-package (ESS-DIVE, BagIt) sets `local_path` to the package root and `files` to every file. The indexer walks `files` if non-empty, else `local_path`.

**`Observation`** (emitted by `parse_to_schema`): `obs_id`, `obs_type` (`ObservationType`: POINT/PROFILE/GRID_CELL/EVENT), `variable` (a `Variable`), `value: float`, `unit: str`, `latitude` [-90,90], `longitude` [-180,180], `depth_m` (positive downward, None if surface), `time_start`, `time_end`, `qc_flags`, `provenance` (a `Provenance`), `extra`.

**`Provenance`** (on every Observation): `source_id`, `source_url`, `access_timestamp`, `content_checksum`, `license`, `adapter_version`, `schema_version`.

## Procedure

1. **Pick the closest existing adapter as a template.** Connector-backed (the default): `sloan_2014_barrow_soil` (ESS-DIVE) or `kanevskiy_2024_cryostratigraphy` (Arctic Data Center / BagIt). Legacy standalone single-file: `calm`/`gtnp`. Match the project's style; do not invent a new shape.
2. **`list_available`** — return `DatasetInfo` with `variables`, `spatial_coverage`, `temporal_coverage`, `license`, `url` **and `citation` + `references` + `keywords`** populated. These feed the self-describing metadata bundle `acquire()` writes into the staged folder (PROVENANCE.json/CITATION.cff/README.md, doc 18) — a bare data file is not an acceptable staged artifact. Take the citation from the source card / the source's native metadata; do not fabricate authors (leave `citation=None` and rely on the native record if unsure). (Discovery across a center is the connector's `search`; `list_available` returns this adapter's known dataset(s).)
3. **`fetch`** — **connector-backed: just set `data_center`; do not write a `fetch` method** (BaseAdapter's default delegates to the connector, which owns download + idempotency + the `raw_dir/<data_center>/<dataset_id>/` layout). If the center has no connector, write it first with **`e2sa-add-connector`**. **Legacy standalone only:** override `fetch` to download into `self.raw_dir`, set the right `FetchResult` shape, sha256 `content_checksum`, UTC `access_timestamp`, on-disk fast-path, idempotent.
4. **`parse_to_schema`** — map source columns/variables to `Variable` members and emit `Observation`s. Apply the gotchas below. Set `obs_type` correctly (PROFILE for depth series, POINT for surface, GRID_CELL for raster, EVENT for episodic). Attach full `Provenance`.
5. **Declare `serves`** = the `Variable`s actually emitted (derive from a var-map where possible, like `above`, so it cannot drift).
6. **Register** — add `"<source_id>": <AdapterClass>` to `ADAPTER_REGISTRY` in `e2sa/data/registry.py`. **Non-negotiable:** without this `acquire()`/`get_adapter()` cannot reach it.
7. **Fixture + test** — commit a tiny real-shaped fixture to `tests/fixtures/`; add a test that parses it and asserts schema fields, the gotchas, `serves ⊆ emitted`, and `unit == CANONICAL_UNITS[variable]`. **Also assert `validate_observations(adapter.serves, observations)` returns no `error`-severity findings** (the QC layer `acquire(parse=True)` runs; `e2sa/qc/checks.py`), so a new adapter is QC-clean by construction. The fixture MUST mirror the source's real units/conventions, not the code's assumption — a fixture built to match the adapter can hide a real bug (the `above_stdm` VWC fixture stored fraction-style values and masked a percent-vs-fraction bug; `20260629e`).
8. **Index** — the package is indexable by `index_package` (`e2sa/data/indexing.py`); no per-adapter indexing code.

## Migrating an existing self-fetching adapter to a connector (Option C refactor)

The recipe for moving a legacy adapter (calm/gtnp/above/alaska_thaw_db) onto a connector — proven on the `ess_dive`/`sloan_2014_barrow_soil` split (dev log `20260623e`):

1. **Connector first.** If the data center has no connector, write it with **`e2sa-add-connector`**, **moving the adapter's existing `fetch`/auth body into the connector's `fetch`** (move, don't rewrite — the download already works). One connector can back several adapters (PANGAEA → both CALM and GTN-P).
2. **Point the adapter at it.** Set `data_center`; **delete the adapter's `fetch` method** (it inherits BaseAdapter's connector-delegating default); keep `parse_to_schema` + `serves`.
3. **Rename to the slug.** `source_id` = `dataset_id` = the `docs/design/15` §9 slug (`calm` → `calm_alt`, `gtnp` → `gtnp_magt`). Update `ADAPTER_REGISTRY`, the source card, the raw-folder note, and any test/label references.
4. **Split the tests.** Connector-level (fetch/auth, mocked `urlopen`) → `tests/test_<center>_connector.py`; adapter-level (parse/serves/delegation) → `tests/test_<slug>_adapter.py`.
5. **Update docs.** `docs/design/13` inventory row + the README data-center registry. Keep the suite green at each step.

## Parse gotchas (each one cost a real bug)

- **Missing-value sentinels** — read the per-file sentinel (`-9999`, blank, `not_determined`); never treat it as data. `0` is often meaningful (EIC=0 ≠ missing).
- **Units → canonical** — emit `Observation.unit` as the canonical unit for the variable (`CANONICAL_UNITS`, `e2sa/schema.py`); convert at parse (e.g. EIC % → fraction `/100`, ALT cm → m). Do not store the raw source unit.
- **Depth** — for subsurface variables (soil/ground temperature, ice content, moisture) populate `depth_m` (convert to metres; parse from a column or a filename like `..._{N}cm_...`). A subsurface reading without depth is half a measurement.
- **`obs_id` uniqueness** — must be unique per (station/site, depth, time). An event/label alone collides across stations (GTN-P: an event-only id collapsed 4,088 rows to 715). Include station name + lat/lon + depth + the full date.
- **CRS tiered fallback** — machine-readable metadata → PDF user-file → assume WGS84 with a low-confidence flag; record which tier. Reproject to WGS84.
- **Column-name drift / aliasing** — map by concept with OR-chained fallbacks, not one exact string (2025 PANGAEA renamed `Event`/`MAGT`/`Date/Time`; ABoVE has `_VAR_MAP`). Check the live schema, not just the fixture.
- **Filename vs metadata mismatch** — for BagIt/EML, match files by `manifest-md5.txt` checksum, not the declared `<entityName>`.
- **Encoding** — try UTF-8, fall back to `latin-1` on legend/mojibake rows.
- **Blank rows as separators** — do not treat them as EOF; they may delimit boreholes within one file.

## Guardrails

- **Register in `ADAPTER_REGISTRY`** or the adapter is unreachable.
- **`serves` ⊆ what `parse_to_schema` emits** (tested); declare what you emit, not what you wish you served.
- **Canonical units + `depth_m`** for subsurface variables; full `Provenance` on every Observation; raw is immutable; no secrets in the repo.
- **Fixture + test required**; idempotent fetch; on-disk fast-path where downloads are large.
- One adapter module per dataset under `e2sa/data/adapters/<dataset_id>.py` — **the file name matches the slug** (`source_id` = `dataset_id` = the `ADAPTER_REGISTRY` key = the file name), so the directory is self-documenting. Per-data-center connectors live in `e2sa/data/connectors/`. The interface is fixed — add functionality inside it, not in the caller.

## Changelog
- 2026-06-22: Initial version. Split out of `e2sa-add-data-source` step 8 (which is now a handoff). Distilled the BaseAdapter/FetchResult/Observation interfaces and the parse gotchas (sentinels, units, depth, obs_id uniqueness, CRS tiers, schema drift, filename-vs-md5, encoding) from the five existing adapters + captured lessons.
- 2026-06-23: `list_available` step now requires populating `DatasetInfo.citation` +
  `references` + `keywords` (they feed the self-describing metadata bundle `acquire()`
  writes, doc 18); don't fabricate authors. 
- 2026-06-23: Updated for the Option C connector era. Connector-backed is now the default (set `data_center`, delegate `fetch` to `get_connector`, `source_id == dataset_id` slug); added the `data_center` contract attr, the delegate one-liner, the "Migrating an existing self-fetching adapter to a connector" recipe (the Phase 2 refactor checklist), and a handoff to the new `e2sa-add-connector`. Refreshed stale references (six adapters; the built ESS-DIVE/ADC connector-backed templates).
- 2026-06-23: Phase 3 cleanup — `BaseAdapter.fetch` now PROVIDES the connector-delegating default, so a connector-backed adapter writes NO `fetch` method (just `data_center` + `list_available` + `parse_to_schema`). Adapter file name now matches the slug (`e2sa/data/adapters/<dataset_id>.py`).
- 2026-06-30: Step 7 now requires the fixture test assert `validate_observations` returns no `error`-severity findings (QC-clean by construction; the layer `acquire(parse=True)` runs), and that the fixture mirror the source's real units, not the code's assumption (Josue handoff #5, proposed in `20260626a`; motivated by the `above_stdm` VWC fixture that masked a bug, `20260629e`). Dropped the now-stale "once units land" qualifier (canonical units shipped 2026-06-29).
