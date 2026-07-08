# SPADE Data Source Index

Datasets are grouped by status. **Bootstrap** sources are the Phase 1 adapter targets. **Additional documented sources** are catalogued with full data cards but scoped to later adapter phases. **Local archives (brief)** are catalogued but not yet documented in full.

**Naming convention.** Source docs (the `.md` cards in this folder) are named by the **project** (NGEE-Arctic, NASA ABoVE, CALM, GTN-P, Kanevskiy, etc.), not by the data center hosting them. The data center (ESS-DIVE, Arctic Data Center, Earthdata / ORNL DAAC, PANGAEA, Zenodo, USGS ScienceBase, etc.) is documented inside each project's source doc under "Access." The **raw-download folder**, by contrast, keys on the data center under Option C (`docs/design/15`-`16`): `data/raw/<data_center>/<dataset_id>/`, where `<data_center>` is the connector key (`arctic_data_center`, `pangaea`, `earthdata`, `ess_dive`, `zenodo`) and `<dataset_id>` is the slug from `docs/design/15` §9 (`<owner>[_<year>]_<descriptor>`). So the source card and the raw folder no longer mirror each other: card by project, raw folder by data center. See `../../CLAUDE.md` §9 for the full folder-naming rule. (Decided 2026-06-23, superseding the earlier "raw folder mirrors the card name, not the data center" rule, which predated Option C. Adapters not yet migrated to a connector temporarily use `raw/<source_id>/<dataset_id>/`.)

## Data centers (registry)

Source docs are named by project, but the **data center** hosting them determines auth, package format, and which metadata standard the indexer must parse. This registry is the cross-reference. The framework-design counterpart (how the indexer dispatches on these) is `docs/design/04_retrieval_and_indexing.md`; keep the two in sync.

| Data center | Metadata standard | Package format | Auth (download / search) | Indexer parser path | Example dataset |
|---|---|---|---|---|---|
| ESS-DIVE (LBNL / DOE BER) | FLMD + per-file `*_dd.csv` + PDF user-file | flat directory | download open / search uses ORCID bearer JWT (18 h TTL) | FLMD + dd-CSV | Sloan 2014 (NGEE-Arctic) |
| NSF Arctic Data Center (DataONE) | EML 2.2.0 single XML | BagIt (MD5 manifest) | open | EML XML | Kanevskiy 2024 |
| NASA Earthdata (ORNL DAAC / NSIDC / ASF) | CMR / UMM-G | varies (CSV, NetCDF, GeoTIFF) | Earthdata Login (`~/.netrc`) | TBD | NASA ABoVE |
| PANGAEA | PANGAEA dataset metadata | tab-delimited + attachments | open | TBD | CALM, GTN-P |
| Zenodo | DataCite | files in archive | open | TBD | Alaska Permafrost Thaw DB |
| Copernicus CDS | request-based (no package) | NetCDF / GRIB | `~/.cdsapirc` | n/a (request API) | ERA5 |
| PGC (Polar Geospatial Center) | strip `mdf.txt` (key=value) per strip; STAC for mosaics | `.tar.gz` bundle of COG GeoTIFFs | open (strips via HTTP file browser; portal + S3 STAC give mosaics only) | TBD (`pgc` connector pending) | ArcticDEM strips |

**Latest-version rule.** When a data center versions datasets (e.g. the NSF Arctic Data Center mints a new DOI per version), always download and cite the **latest** version, and record the exact version DOI and version date in the source card.

## Bootstrap sources (Phase 1 targets)

| Source | Type | Role | Format | Access | Doc |
|---|---|---|---|---|---|
| CALM | in-situ ALT | Bootstrap 1. Site-average annual active layer thickness, 60 Alaska sites, 1991-present | TSV (PANGAEA) | Open, no auth | [calm.md](calm.md) |
| GTN-P | borehole temperatures | Bootstrap 2. Ground temperature profiles at multiple depths, 311 stations globally | TSV (PANGAEA) | Open, no auth | [gtnp.md](gtnp.md) |
| Alaska Permafrost Thaw DB | labeled thaw events | Bootstrap 3. 19,540 thaw locations across Alaska from 44 sources (Webb et al. 2026) | CSV in ZIP (Zenodo) | Open, CC-BY 4.0 | [alaska_thaw_db.md](alaska_thaw_db.md) |
| NASA ABoVE (ORNL DAAC) | multi-product | Bootstrap 4. 17+ permafrost datasets (ALT, InSAR, soil T, soil moisture) | CSV, NetCDF, GeoTIFF | Earthdata Login | [above.md](above.md) |
| NGEE-Arctic | multi-product project | Bootstrap 5. Authoritative ground truth at SPADE Alaska intensive sites (Kougarok, Council, Teller, Barrow/Utqiagvik, Atqasuk). Hundreds of datasets covering soil T profiles, ALT, snow, soil moisture, vegetation, hydrology, fluxes, geophysics, ELM/ELM-FATES model output (FY 2012+) | NetCDF, CSV, GeoTIFF, varies | ESS-DIVE (web + REST API; ORCID token for search, open downloads for most) | [ngee_arctic.md](ngee_arctic.md) |

## Additional documented sources

| Source | Type | Role | Doc |
|---|---|---|---|
| GIPL UAF Permafrost Lab | in-situ soil T profiles | 344-site list with multi-level processed soil temperature, borehole, air T, soil moisture, snow depth from UAF Permafrost Lab | [gipl_uaf_permafrost.md](gipl_uaf_permafrost.md) |
| Thermokarst circumpolar map | polygon classification | Spatial prior. Thermokarst wetland, lake, hillslope distribution with SOC (Olefeldt et al. 2016) | [thermokarst_circumpolar.md](thermokarst_circumpolar.md) |
| Circum-Arctic ground ice map | polygon + raster | Baseline comparison. Permafrost extent (5 classes) and ground ice content (4 classes). The map SPADE aims to improve. (Heginbottom et al. 2002) | [permafrost_ground_ice_map.md](permafrost_ground_ice_map.md) |
| CUSP | labeled near-surface permafrost obs | Pan-Arctic synthesis of permafrost presence + active layer thickness + thaw depth from published studies and field work. GitHub-hosted, CSV + BibTeX, LANL-led (Schwenk et al.). Complements [alaska_thaw_db.md](alaska_thaw_db.md) by extending geographic footprint beyond Alaska. ECRP FY26 collaborator: Joel Rowland (LANL). | [cusp.md](cusp.md) |
| Kanevskiy 2024 cryostratigraphy | in-situ ground-ice cores | **Direct field-measurement labels for excess-ice content (EIC)**, the SPADE ice-content product's primary anchor variable. 22 destructive sampling campaigns 2018-2023 at 8 Alaska sites (Utqiagvik, Teshekpuk, Prudhoe Bay, Anaktuvuk, Point Lay, Toolik, Itkillik, Jago) + 2 Canadian sites (filter at adapter level). Per-borehole EIC + GMC + VMC + cryostratigraphic-unit assignments. CC0 license. Current DOI 10.18739/A2H12V928 (predecessor 10.18739/A2QR4NS3D obsoleted 2025-08-08). | [kanevskiy_cryostratigraphy.md](kanevskiy_cryostratigraphy.md) |
| ArcticDEM (time-stamped strips) | terrain raster / repeat-pass DEM | **Tier-3 terrain source.** Per-acquisition 2 m DEM strips (SETSM s2s041 / V4.1), EPSG:3413, WGS84 ellipsoidal, COG in `.tar.gz` bundles with `mdf.txt` carrying the precise acquisition timestamp + footprint. Use for static terrain features and/or repeat-pass surface-deformation differencing (the latter needs the time stamps). Inspected geocell n69w151: 104 strips / 69 dates, 2010-2022 (Alaska post-2022 EOCL-restricted). CC-BY 4.0 + mandatory PGC NSF-OPP acknowledgement. DOI 10.7910/DVN/C98DVS (Porter et al. 2022). | [arcticdem.md](arcticdem.md) |
| TSP North America (ground temperature) | in-situ borehole ground temperature | **Second `GROUND_TEMPERATURE` provider** (cross-checks GTN-P; roster carries `GTNP_ID`). US permafrost-observatory network (Romanovsky/UAF), the US contribution to GTN-P. Annual borehole temperature-vs-depth snapshots to ~75 m across Alaska + adjacent Canada. Arctic Data Center (connector exists), BagIt/EML, CC0. Series of 10 annual DOIs 2016-2025. | [tsp_north_america.md](tsp_north_america.md) |


## Adding a new source

**Card granularity.** One card per **program/network** (NGEE-Arctic, NASA ABoVE, CALM, GTN-P) or per **standalone dataset** (Kanevskiy 2024 cryostratigraphy, Webb Alaska Thaw DB). A single dataset *within* a program (e.g. Sloan 2014 inside NGEE-Arctic) does **not** get its own card; record its DOI + full citation in the program card's dataset list and in the per-download provenance in the DuckDB catalog. Deciding question: standalone dataset → its own card; one of many in a tracked program → recorded under the program card.

Prefer the `e2sa-add-data-source` skill, which walks every step below. Manually:

1. **Use the latest dataset version.** If the archive versions datasets, download and cite the **latest** version; record the exact version DOI and version date.
2. Create `<project_name>.md` in this folder, named by **project/dataset, not data center** (see the naming convention above), following the existing docs as a template (sections: Role, Access, Summary, Variables, Format, Coverage, Gotchas, Adapter design notes). **Required: the full dataset citation and the landing/download page URL.**
3. Add a row to the appropriate source table above, and a row to the **Data centers** registry if the hosting data center is new.
4. If the source needs code, follow the Option C split (`docs/design/15`-`16`). If the hosting data center has **no connector yet**, write `e2sa/data/connectors/<data_center>.py` with the **`e2sa-add-connector`** skill (auth + search + whole-package fetch), then the dataset adapter `e2sa/data/adapters/<dataset_id>.py` with **`e2sa-add-adapter`** (connector-backed: sets `data_center`, inherits `fetch`, owns `parse_to_schema` + `serves`, registered in `ADAPTER_REGISTRY`). If the center already has a connector, go straight to `e2sa-add-adapter`.

