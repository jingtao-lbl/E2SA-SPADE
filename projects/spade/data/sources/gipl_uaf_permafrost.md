# GIPL UAF Permafrost Lab Soil Temperature Sites

UAF Geophysical Institute Permafrost Laboratory (Romanovsky group). Manually compiled and organized site list and observations from the lab's monitoring network across Alaska and circumpolar permafrost regions.

Post-processing approach for the 161-Alaska-site curated subset documented in: **Tao, J., Reichle, R. H., Koster, R. D., Forman, B. A., and Xue, Y.** (2017). Evaluation and Enhancement of Permafrost Modeling With the NASA Catchment Land Surface Model. *Journal of Advances in Modeling Earth Systems* 9:2771-2795. doi:10.1002/2017MS001019.

## Role in SPADE

Primary in-situ source for soil temperature profiles and borehole measurements in Alaska. Complements CALM (active layer thickness only) and GTN-P (annual MAGT only) by providing higher-frequency, multi-depth thermal profiles. Many sites also include air temperature, soil moisture (VSM), and snow depth.



## Original source

- UAF Permafrost Lab site list: https://permafrost.gi.alaska.edu/sites_list
- Lead investigator: Vladimir Romanovsky
- The lab maintains 200+ boreholes in Alaska and Russia. A curated subset is used for SPADE.


## Variables

| Code | Variable |
|---|---|
| Ts | Soil temperature (profile, multiple depths) |
| BHTs | Borehole temperatures (deep) |
| airT | Air temperature |
| VSM | Volumetric soil moisture |
| SnowDepth | Snow depth |


Example Alaska sites:

| Code | Name | Lat | Lon | Elev (m) | Variables | Profile depth |
|---|---|---|---|---|---|---|
| AKR | Akulik River | 64.918 | -160.728 | 62 | Ts | 1.5 m (4 depths) |
| BL1 | Birch Lake | 64.324 | -146.688 | 262 | BHTs | 62.0 m borehole |
| BZ1 | Bonanza Creek 1 (LTER) | 64.707 | -148.291 | 125 | Ts, BHTs, airT, VSM, SnowDepth | 0.54-1 m profile + 37.6 m borehole |
| BR1 | Barrow 1 (NML-1) | 71.311 | -156.654 | 5 | BHTs | 45.0 m borehole |
| AG1 | Atigun Pass 1 | 68.134 | -149.463 | 1345 | (limited) | shallow |

## Spatial coverage

344 sites total, with the densest coverage in Alaska (Brooks Range, North Slope, Interior, Seward Peninsula). The site list also includes some circumpolar sites outside Alaska (e.g., Abisko in Sweden).

## Temporal coverage

Varies by site. Many sites have records spanning 2007-2019; some go back to the 1970s in the Romanovsky lab archives.

## Known gotchas

1. **Manually curated processing.** The L1/L2 processed files in the local archive reflect a curated organization, not an official UAF archive. Reproducing the processing requires MATLAB scripts (`ProcessInsitu_*.m`).
2. **Heterogeneous depth conventions.** Profile depths range from 1.5 m (shallow) to 60+ m (deep boreholes). Different sites have different sensor depths.
3. **Site code to name mapping** lives in the spreadsheet, not in individual data files. Files use codes like `BL1_us34_2015.xls` where the suffix encodes year and source.
4. **Multi-year files.** Each site has one xls file per year. Concatenation needed for time series.
5. **MATLAB processing scripts.** Existing pipeline is in MATLAB (`ProcessInsitu_*.m`). Reproducing the L1/L2 processing in Python is non-trivial.
6. **Not directly downloadable as a single archive.** The original UAF Permafrost Lab site provides per-site downloads; bulk aggregation requires custom assembly.

## Adapter design notes

**Schema mapping.**
- `obs_type`: `PROFILE` for borehole and soil temperature profiles, `POINT` for surface measurements (air temperature, snow depth)
- `variable`: `GROUND_TEMPERATURE` (Ts, BHTs), `AIR_TEMPERATURE` (airT), `VOLUMETRIC_WATER_CONTENT` (VSM), `SNOW_DEPTH`
- `extra`: site_code, site_name, processing_level (L0/L1/L2), measurement_type (borehole vs profile), elevation_m

**Recommended ingestion strategy.**
1. Build a site registry (code, lat, lon, elevation, measurements available) from the upstream UAF site list.
2. For each site, walk the corresponding per-site XLSX files.
3. Parse XLSX files into Observation records, one row per (site, depth, time, variable).
4. Cross-reference site codes against the registry to populate metadata.

**Adapter version tag.** Any custom L1/L2 processing applied during ingestion (e.g., gap-filling, IDW interpolation) should be treated as part of the adapter version (e.g., `0.1.0_L1`) so downstream consumers can pin to a known processing level.

**Unit test fixture.** Two sites: one borehole (BL1) and one profile (AKR), with 5-10 rows each.

## Relationship to other sources

- Some GIPL sites overlap with **GTN-P** (e.g., Romanovsky boreholes in the GTN-P database). When ingesting both, deduplicate by GTN-P ID where available.
- The **CALM** network has ALT measurements at some of the same sites (e.g., Imnavait Creek, Toolik). Cross-reference site codes.
- A curated local compilation may include sites NOT in the public UAF Permafrost Lab list at https://permafrost.gi.alaska.edu/sites_list.
