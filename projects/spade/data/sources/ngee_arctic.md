# Data Source: NGEE-Arctic

**Date:** May 21, 2026
**Purpose:** Reference document for the Next-Generation Ecosystem Experiments - Arctic (NGEE-Arctic) project as a SPADE data source. NGEE-Arctic is a DOE BER long-running project (FY 2012 to present) studying Arctic terrestrial ecosystems at multiple Alaska sites. Its primary data host is ESS-DIVE (the DOE BER repository at LBNL), with some legacy data on ORNL DAAC and NSIDC. Per the SPADE convention, source docs are named by project and the data-center access mechanisms are documented inline under "Access" below.

---

## Role in SPADE

Authoritative ground truth across a small set of intensively-instrumented Alaska sites where SPADE's predictions must be defensible. Same DOE BER ecosystem as SPADE (ESS-DIVE is hosted at LBNL), so provenance, licensing, and longevity are aligned. Many datasets directly cover SPADE variables (soil temperature profiles, active layer thickness, snow, soil moisture, vegetation composition, fluxes) at sites with multi-year continuous records.

Key sites for SPADE specifically: **Kougarok, Council, Teller, Barrow / Utqiagvik, Atqasuk** (Seward Peninsula and North Slope).

This is a **portal**, not a single dataset. Hundreds of individual datasets live under the NGEE-Arctic project on ESS-DIVE, each with its own DOI, file format, and variable list. Tasks against this source should target specific dataset DOIs after a discovery step, not "download all of NGEE-Arctic."

## What it is

**NGEE-Arctic** (Next-Generation Ecosystem Experiments - Arctic): DOE BER project at ORNL, LBNL, LANL, BNL, and UAF. Goal is to improve predictive understanding of Arctic terrestrial ecosystem evolution under environmental change, with a focus on permafrost-vegetation-hydrology coupling. Field campaigns at multiple Alaska sites since 2012. Outputs include in-situ observations, geophysical surveys, airborne remote sensing, and ELM / ELM-FATES model output.

**ESS-DIVE** (Environmental System Science Data Infrastructure for a Virtual Ecosystem): DOE BER's data repository, hosted at LBNL. Replaces the older ESS-DIVE PI Dashboard. All datasets carry a persistent DOI, a license (typically CC-BY 4.0), and a metadata record following DataONE / ESS-DIVE reporting formats. Search via web UI; programmatic access via REST API.

## Access

| Resource | URL |
|---|---|
| ESS-DIVE portal | https://ess-dive.lbl.gov/ |
| NGEE-Arctic project page on ESS-DIVE | https://data.ess-dive.lbl.gov/portals/ngeearctic |
| ESS-DIVE REST API root | https://api.ess-dive.lbl.gov/ |
| API documentation | https://docs.ess-dive.lbl.gov/ |
| Project home (DOE) | https://ngee-arctic.ornl.gov/ |

**Authentication.** Most NGEE-Arctic datasets on ESS-DIVE are openly published and downloadable without authentication. The REST API for programmatic search and metadata access requires an ORCID-authenticated bearer token; sign in once via ess-dive.lbl.gov to generate a personal token. The token is then passed as `Authorization: Bearer <token>` on API calls.

**License.** Per-dataset; the strong majority are CC-BY 4.0. Adapter must record the per-dataset license, not a portal-wide default.

## Variable categories present

NGEE-Arctic data on ESS-DIVE spans roughly the following categories (each backed by multiple datasets across the sites and years). The exact dataset count per category varies as new releases land; agent should query the API for current counts rather than relying on this list for completeness.

| Category | Examples |
|---|---|
| Soil and ground temperature profiles | Continuous multi-depth probe records, borehole thermistor chains, freeze / thaw timing |
| Active layer thickness | Annual probe surveys at NGEE plots; depth-of-thaw repeat surveys |
| Soil moisture | TDR, time-domain reflectometry probes, calibrated to site-specific equations |
| Snow | Snow depth, density, SWE, snow-off / snow-on dates |
| Vegetation | Species composition by plot, PFT cover fractions, NDVI, LAI, biomass, leaf-level traits |
| Hydrology | Water-table depth, surface-water extent, runoff at instrumented catchments |
| Fluxes | Eddy covariance towers (CO2, CH4, H2O) at select sites; chamber-based GHG flux |
| Geophysics | ERT (electrical resistivity tomography), GPR (ground-penetrating radar), seismic; used for subsurface stratigraphy and ice content inference |
| Remote sensing | Airborne LiDAR, hyperspectral, UAV imagery; site-scale gridded products |
| Modeled output | ELM, ELM-FATES, and ATS model output for NGEE sites; calibration target data |
| Synthesis products | Cross-site harmonized datasets (e.g. Kougarok plot-scale soil and vegetation synthesis) |

## Coverage summary

| Aspect | Range |
|---|---|
| Primary sites | Kougarok, Council, Teller, Barrow / Utqiagvik, Atqasuk (and others on Seward Peninsula and North Slope) |
| Temporal | Earliest records 2012; ongoing as new field seasons land |
| Spatial resolution | Plot to airborne footprint, varies per dataset |
| Format | NetCDF, CSV, GeoTIFF, shapefile, HDF5, sometimes proprietary geophysical formats |
| Vertical coverage | Surface to several meters depth for soil / borehole records; canopy and snowpack measurements above-ground |


## Adapter design notes (when one lands)

**Observation type.** Mixed; depends on the specific dataset. Plot-scale records map to `ObservationType.POINT` or `PROFILE`; gridded products map to `GRID_CELL`; campaign-style records (e.g. one-time field survey at a site) often best as `EVENT`.

**Variable mapping.** Multi-dataset adapter. The `NgeeArcticAdapter` should accept a dataset DOI as its `dataset_id` and dispatch to per-dataset parsers based on the metadata returned by the ESS-DIVE API. Common variable mappings (per the unified schema): soil temperature -> `Variable.SOIL_TEMPERATURE`, soil moisture -> `Variable.VOLUMETRIC_WATER_CONTENT`, ALT -> `Variable.ACTIVE_LAYER_THICKNESS`, snow depth -> `Variable.SNOW_DEPTH`, etc.

**CRS.** Per-dataset. Most NGEE-Arctic gridded products use polar-stereographic or Alaska Albers; reprojection to WGS84 is required to match the unified schema. Point and plot data carry lat / lon directly, usually in WGS84.

**Provenance.** Each Observation record must carry the per-dataset DOI in `Provenance.source_url`, the dataset's published license (do not assume CC-BY without checking), the per-dataset content checksum (sha256 of the raw file), and the ESS-DIVE-assigned dataset version.

**Fetch strategy.** Per dataset DOI: (1) query the ESS-DIVE API for the dataset record; (2) iterate over the dataset's file list; (3) download each file with checksum verification; (4) cache under `data/raw/ngee_arctic/<dataset_doi_slug>/`. The fetch step is per-DOI, not per-portal; the orchestrator decides which DOIs are needed for a given run.

**Authentication.** The adapter must accept an ORCID-bearer token from the environment (`ESS_DIVE_TOKEN`, the form used in `docs/design/05_agent_credentials.md` and `projects/spade/design/04_credentials_setup.md`). Open datasets work without it for downloads; the search / metadata API typically requires it. The token is short-lived (~18 h TTL), so the adapter must fail loud on an expired/missing token, not silently.

**Discovery flow.** Before any fetch, the agent should use the ESS-DIVE API search endpoint (or scrape the project portal) to enumerate the candidate datasets for the requested variables and site, then surface the candidate DOIs to the human for approval. This is parallel to how `e2sa-discover` is supposed to behave for any multi-product source.

## Gotchas

- **Per-dataset variability.** Each dataset has its own format, units, naming convention, and QC level. A single adapter must dispatch to per-dataset parsers; do not assume one parser fits the portal.
- **Multiple versions per DOI.** ESS-DIVE preserves dataset versions. The adapter must record which version was fetched (the version is part of the DOI metadata, not just the DOI string).
- **Embargo windows.** Some recently-produced datasets carry short embargoes before public release. The API will report this; the adapter should surface it, not silently fail.
- **Variable name collisions.** NGEE-Arctic uses several different naming conventions across PI groups (e.g. soil temperature might be `tsoil`, `soilt`, `T_soil`, `temperature_soil`, etc.). Map to the unified schema explicitly, do not match on substring.
- **Plot vs grid disambiguation.** A dataset may package both plot-scale records (lat / lon per row) and gridded synthesis (lat / lon per pixel) in the same archive. The parser must split them into the right `ObservationType` rather than collapsing both into POINT.
- **Geophysics formats.** ERT, GPR, and seismic outputs sometimes use proprietary formats from the data-acquisition software. Adapter coverage of these is out of scope for the first NGEE-Arctic adapter slice; flag for later.

## Reference downloads (TBD)

When the first NGEE-Arctic task lands, list the specific dataset DOIs that were fetched here with their roles. Example template (fill in per task):

| Dataset DOI | Variable | Site | Used by task |
|---|---|---|---|
| 10.15485/<id> | <variable> | <site> | <task_id> |

