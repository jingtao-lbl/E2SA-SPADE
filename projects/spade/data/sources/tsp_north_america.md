# TSP North America (Thermal State of Permafrost) — annually observed ground temperatures

Romanovsky, V., A. Kholodov, D. Nicolsky, and T. Wright. 2023. *Thermal state of
permafrost in North America - annually observed ground temperatures, Alaska, 2023.*
Arctic Data Center. doi:10.18739/A2DB7VR9J.
Landing page: https://arcticdata.io/catalog/view/doi:10.18739/A2DB7VR9J

(One dataset/DOI per year; cite the specific year(s) a run consumes. The full
annual series 2016-2025 is listed under "Annual series" below. Lead author and
publisher are stable across the series; the author list is confirmed per year
from each dataset's EML.)

## Role in SPADE

The US permafrost-observatory network (Romanovsky group, UAF) reporting **borehole
ground-temperature profiles**, the US contribution to GTN-P. In SPADE this is:

1. **A second, independent provider of `GROUND_TEMPERATURE`** alongside
   [gtnp.md](gtnp.md) (`gtnp_magt`). Ground temperature is both a SPADE variable in
   its own right and a strong covariate/predictor for active layer thickness
   (the ALT-first target). Having two providers enables the **cross-source
   consistency check** (`e2sa/qc/cross_source.py`) for ground temperature, the way
   CALM + ABoVE do for ALT.
2. **Deep thermal profiles** (to ~75 m at some sites), covering the North Slope and
   interior Alaska, extending into adjacent Canada.
3. **Directly cross-linkable to GTN-P**: the site roster carries a `GTNP_ID` column,
   so co-located sites match exactly (both drive cross-source comparison and
   dedup, since many TSP sites *are* GTN-P sites in the same network).

## Access

| Field | Value |
|---|---|
| Data center | NSF Arctic Data Center (DataONE member node) |
| Connector | `arctic_data_center` (exists; live DataONE Solr search + BagIt fetch) |
| Package format | BagIt (MD5 manifest), EML 2.2.0 metadata XML + CSVs |
| License | **CC0 1.0** (public domain dedication) |
| Auth | Open (no credentials for download or search) |
| Versioning | One DOI **per year** (a series, not versions of one dataset) |

## Summary

Each annual dataset is a field campaign that re-reads a network of permafrost
observatory boreholes across Alaska. A dataset delivers:

- a **site roster** CSV (`TSP_NorthAmerica_occasional_<year>_SitesRoster.csv`) with
  one row per borehole: `SiteCountry, SiteCode, SiteCodeHistorical, GTNP_ID,
  SiteName, SiteEquipment, Depth, Latitude, Longitude, Elevation, SiteVegetation,
  ObservationDate, Filename`;
- one **per-borehole** CSV per site, header `Depth_m,Temperature_C`, a single-date
  temperature-vs-depth **snapshot** taken at the annual visit (not a continuous
  time series).

2023 example: 18 Alaska sites, 448 depth readings, depth 2.0-74.7 m, temperatures
-9.5 to +0.86 degC, no missing-value sentinels, all files a uniform
`Depth_m,Temperature_C` schema.

## Variables

| Source field | SPADE mapping |
|---|---|
| `Temperature_C` (per depth) | `Variable.GROUND_TEMPERATURE` (canonical unit `degC`) |
| `Depth_m` | `Observation.depth_m` (subsurface, depth-resolved) |
| `Latitude`, `Longitude` | coordinates (WGS84, EML-stated -> CRS Tier 1) |
| `Elevation`, `SiteVegetation`, `Depth` (total) | site metadata |
| `GTNP_ID`, `SiteCode`, `ObservationDate` | provenance / cross-source keys (carry into `Observation.extra`) |

## Format

- BagIt package; EML 2.2.0 XML; roster CSV + N per-borehole CSVs.
- Per-borehole CSVs are **UTF-8 with BOM** (open with `encoding="utf-8-sig"`).
- `ObservationDate` in the roster is `MM/DD/YY`; the borehole filename encodes the
  same date as `YYYY_MM_DD`.

## Coverage

- **Spatial:** bbox W-165.30 S62.20 E-145.50 N78.80 (Alaska + adjacent Canada).
- **Depth:** 2.0-74.7 m (2023); deep boreholes reach the near-isothermal zone.
- **Temporal:** annual snapshots, **2016-2025** (10 datasets).

## Known gotchas

1. **UTF-8 BOM** on every per-borehole CSV. Parse with `utf-8-sig` or the first
   `Depth_m` header cell carries a leading BOM.
2. **Snapshot, not a series.** Each per-borehole file is one profile from the annual
   visit; the timestamp is the roster `ObservationDate` / the filename date, not a
   column. Do not treat successive rows as time.
3. **Depth-resolved.** Every reading has a depth; populate `Observation.depth_m`
   (a ground temperature without its depth is incomplete).
4. **Roster `Filename` is authoritative for linkage, not `SiteCode`.** Observed
   mismatch: roster `SiteCode=US_BRW_102` points to `Filename=US_BRW_201_2023_07_27.csv`.
   Join roster rows to data files by the `Filename` column (and verify against the
   BagIt MD5 manifest), never by reconstructing a name from `SiteCode`.
5. **One DOI per year (2016-2025).** This is a series; ingest all years to get the
   time axis. The "latest version" rule does not collapse them (they are distinct
   years, not supersessions).
6. **GTN-P overlap.** Many sites carry a `GTNP_ID` and are the same boreholes as
   [gtnp.md](gtnp.md). Use for cross-source consistency, and dedupe/flag co-located
   site-years at the `assemble()` / harmonization stage rather than dropping in the
   adapter (faithful-adapter policy).
7. **Not Alaska-only.** The bbox extends into Canada; keep the non-Alaska rows
   (training-useful) and region-scope downstream via `RunConfig.bbox`.

## Adapter design notes

- **Connector-backed (Option C).** `data_center = "arctic_data_center"`; the adapter
  inherits `fetch` from the existing connector and owns `parse_to_schema` + `serves`.
  Build via `e2sa-add-adapter` (connector already exists, so skip `e2sa-add-connector`).
- **`serves = frozenset({Variable.GROUND_TEMPERATURE})`.**
- **`dataset_id` per year:** `tsp_<year>_ground_temperature` (raw already staged at
  `raw/arctic_data_center/tsp_2023_ground_temperature/`). `list_available()` returns
  all 10 annual `DatasetInfo`s; register the 10 DOIs for fetch (connector
  `_KNOWN_DATASETS` or an adapter-level DOI map).
- **`parse_to_schema`:** read the roster (key by `Filename`) for coords + metadata,
  then each borehole CSV (`utf-8-sig`) -> one `Observation` per (site, depth):
  `value=Temperature_C`, `unit="degC"`, `depth_m=Depth_m`, `time=ObservationDate`,
  `ObservationType.PROFILE`. Carry `GTNP_ID` + `SiteCode` into `extra` for
  cross-source matching/dedup.
- **`obs_id` uniqueness:** site + observation date + depth.
- **QC:** `validate_observations` should pass clean (range -60..40 degC, depth
  present, real CC0 citation, self-describing folder).

## Annual series (all DOIs)

| Year | DOI | Year | DOI |
|---|---|---|---|
| 2016 | 10.18739/A2W08WG7P | 2021 | 10.18739/A29G5GF7P |
| 2017 | 10.18739/A20R9M42C | 2022 | 10.18739/A2H70823W |
| 2018 | 10.18739/A2HX15Q8V | 2023 | 10.18739/A2DB7VR9J |
| 2019 | 10.18739/A20R9M47S | 2024 | 10.18739/A2X05XF3W |
| 2020 | 10.18739/A2MW28G02 | 2025 | 10.18739/A2SF2MD87 |

Enumerated live from the Arctic Data Center DataONE Solr index (current versions,
`-obsoletedBy:*`) on 2026-07-06. Verify each year's exact author list + title from
its EML when the adapter ingests it.
