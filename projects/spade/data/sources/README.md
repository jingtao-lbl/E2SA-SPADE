# SPADE Data Source Index

Datasets are grouped by status. **Bootstrap** sources are the four targets for Phase 1 adapters. **External portals** are programmatically-accessible multi-dataset projects without a complete local copy. **Local archives (full doc)** are manually downloaded datasets with detailed data cards. **Local archives (brief)** are catalogued but not yet documented in full.

**Naming convention.** Source docs are named by the **project** (NGEE-Arctic, NASA ABoVE, CALM, GTN-P, etc.), not by the data center hosting them. The data center (ESS-DIVE, Earthdata / ORNL DAAC, PANGAEA, Zenodo, USGS ScienceBase, etc.) is documented inside each project's source doc under "Access." Adapters under `e2sa/data/` may be project-scoped (when only one project uses a given upstream) or data-center-scoped (when several projects share an API, auth scheme, and format conventions); that decision is made at adapter-implementation time, not in the source-doc layer.

## Bootstrap sources (Phase 1 targets)

| Source | Type | Role | Format | Access | Doc |
|---|---|---|---|---|---|
| CALM | in-situ ALT | Bootstrap 1. Site-average annual active layer thickness, 60 Alaska sites, 1991-present | TSV (PANGAEA) | Open, no auth | [calm.md](calm.md) |
| GTN-P | borehole temperatures | Bootstrap 2. Ground temperature profiles at multiple depths, 311 stations globally | TSV (PANGAEA) | Open, no auth | [gtnp.md](gtnp.md) |
| Alaska Permafrost Thaw DB | labeled thaw events | Bootstrap 3. 19,540 thaw locations across Alaska from 44 sources (Webb et al. 2026) | CSV in ZIP (Zenodo) | Open, CC-BY 4.0 | [alaska_thaw_db.md](alaska_thaw_db.md) |
| NASA ABoVE (ORNL DAAC) | multi-product | Bootstrap 4. 17+ permafrost datasets (ALT, InSAR, soil T, soil moisture) | CSV, NetCDF, GeoTIFF | Earthdata Login | [above.md](above.md) |

## External portals (programmatic access, no full local copy)

| Source | Type | Role | Access | Doc |
|---|---|---|---|---|
| NGEE-Arctic | multi-product project | DOE BER project archive: hundreds of datasets covering soil T profiles, ALT, snow, soil moisture, vegetation, hydrology, fluxes, geophysics, and ELM/ELM-FATES model output across Kougarok, Council, Teller, Barrow/Utqiagvik, Atqasuk and other Alaska sites (FY 2012 onward). Authoritative ground truth for the SPADE Alaska intensive sites. | Primary: ESS-DIVE (web + REST API, ORCID-bearer token for search, open downloads for most datasets). Some legacy: ORNL DAAC, NSIDC | [ngee_arctic.md](ngee_arctic.md) |

## Additional documented sources

| Source | Type | Role | Doc |
|---|---|---|---|
| GIPL UAF Permafrost Lab | in-situ soil T profiles | 344-site list with multi-level processed soil temperature, borehole, air T, soil moisture, snow depth from UAF Permafrost Lab | [gipl_uaf_permafrost.md](gipl_uaf_permafrost.md) |
| Thermokarst circumpolar map | polygon classification | Spatial prior. Thermokarst wetland, lake, hillslope distribution with SOC (Olefeldt et al. 2016) | [thermokarst_circumpolar.md](thermokarst_circumpolar.md) |
| Circum-Arctic ground ice map | polygon + raster | Baseline comparison. Permafrost extent (5 classes) and ground ice content (4 classes). The map SPADE aims to improve. (Heginbottom et al. 2002) | [permafrost_ground_ice_map.md](permafrost_ground_ice_map.md) |
| CUSP | labeled near-surface permafrost obs | Pan-Arctic synthesis of permafrost presence + active layer thickness + thaw depth from published studies and field work. GitHub-hosted, CSV + BibTeX, LANL-led (Schwenk et al.). Complements [alaska_thaw_db.md](alaska_thaw_db.md) by extending geographic footprint beyond Alaska. ECRP FY26 collaborator: Joel Rowland (LANL). | [cusp.md](cusp.md) |


## Adding a new source

1. Create `<source_name>.md` in this folder following the existing docs as a template (sections: Role, Access, Summary, Variables, Format, Coverage, Gotchas, Adapter design notes).
2. Add a row to the appropriate table above.
3. If the source needs a new adapter, create `e2sa/data/<source_name>.py` extending `BaseAdapter`.

