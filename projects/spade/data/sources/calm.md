# CALM (Circumpolar Active Layer Monitoring) Network

Pan-Arctic curated-subset evaluation reference: **Tao, J., Riley, W. J., and Zhu, Q.** (2024). Evaluating the impact of peat soils and snow schemes on simulated active layer thickness at pan-Arctic permafrost sites. *Environmental Research Letters* 19(5):054027. doi:10.1088/1748-9326/ad38ce.

## Role in SPADE

Bootstrap source 1. Primary in-situ active layer thickness (ALT) observations across Alaska. Long time series (1991-present) at standardized grid sites.


## Access

| Method | URL | Format |
|---|---|---|
| PANGAEA (recommended) | https://doi.pangaea.de/10.1594/PANGAEA.972777 | Tab-delimited text, CC-BY 4.0 |
| GWU website | https://www2.gwu.edu/~calm/ | HTML summary table + per-site Excel files |
| GTN-P database | https://gtnpdatabase.org/activelayers/view/2 | Web interface |
| Arctic Data Center | https://arcticdata.io/catalog/portals/CALM | Individual datasets |
| NSIDC (GGD313) | https://nsidc.org/data/ggd313/versions/1 | Redirects to GWU |

No authentication required. No API exists.

## Summary

240+ field installations across 15 countries. About 60 Alaska sites (U-codes U1 through U60), of which ~40 are currently active. Primary variable is end-of-season maximum thaw depth (ALT) in centimeters, measured annually in late August to mid-September. Some sites also record soil temperature profiles, soil moisture, snow depth, and frost heave.

## Key Alaska sites (longest records)

| Code | Name | Lat | Lon | Grid (m) | Years |
|---|---|---|---|---|---|
| U1 | Barrow (Utqiagvik) | 71.317 | -156.600 | 1000 | 1993-2025 |
| U2 | Barrow CRREL Plots | 71.317 | -156.583 | 10 | 1991-2025 |
| U3 | Atqasuk | 70.450 | -157.400 | 1000 | 1996-2025 |
| U5 | West Dock (1 km) | 70.367 | -148.567 | 1000 | 1993-2025 |
| U11A | Imnavait Creek | 68.611 | -149.310 | 1000 | 1992-2025 |
| U12A | Toolik | 68.622 | -149.606 | 1000 | 1996-2025 |
| U27 | Council Grid | 64.844 | -163.720 | 1000 | 2000-2025 |
| U28 | Kougarok | 65.454 | -164.627 | 1000 | 2000-2025 |

Sites span Arctic Coastal Plain (71.3N) to interior Alaska (61.5N) along the Dalton Highway transect, Seward Peninsula, and interior boreal sites.

## Data format

**PANGAEA dataset** (Streletskiy et al. 2025). 22,587 records, 263 time series, 1990-2024. 12 columns: Event label, Site code, Site name, GTN-P ID, Country, Area/locality, Latitude, Longitude, DATE/TIME (ISO 8601), Active layer depth (cm), Sample comment, Comment. This is the cleanest path for site-average annual ALT.

**GWU HTML summary table** (north_files/sheet001.htm). Wide format: sites as rows, years 1990-2025 as columns. Values are site-average ALT in cm. Missing data indicated by dashes, not NaN.

**Per-site Excel files**. One per site, grid-node-level measurements (up to 121 nodes per 11x11 grid). Layout varies by site.

## Measurement methods (mixed in the dataset)

- **P** (mechanical probing): primary method, most common
- **TT** (thaw tubes): permanently installed frost tubes
- **T/B##** (temperature-inferred from borehole): depth in meters

Methods are not directly comparable for trend analysis. Probing grids yield spatially resolved data, thaw tubes and boreholes yield single-point time series.

## Known gotchas

1. **No API.** Must download files from GWU website or PANGAEA. No bulk endpoint.
2. **Format inconsistency.** Excel files vary in structure across sites. No standardized column names.
3. **Missing data coded as dashes** in the HTML table, not standard NaN or -999.
4. **Right-censored values.** If thaw exceeds probe length (150-185 cm), reported value is a minimum bound, not true depth. No explicit flag in summary data.
5. **Coordinate inconsistency.** Older metadata uses degrees-minutes format. Summary table uses decimal degrees. Precision varies (e.g., 71.317 vs 71.31667).
6. **CRS not explicitly stated.** WGS84 assumed but not declared in most files.
7. **Measurement timing varies.** Probing date is not fixed across or within years. Assumes late-season maximum but early/late seasons introduce bias.
8. **Sub-sites.** Some locations have sub-sites (U7A, U7B, U7C; U9A, U9B) representing different vegetation or grid sizes.
9. **~20 Alaska sites are inactive** but still listed in the tables.

## Adapter design notes

**Recommended parsing strategy (start here).** Use the PANGAEA dataset (DOI: 10.1594/PANGAEA.972777). Clean tab-delimited file. Filter by Country = "US" for Alaska. Maps directly to our schema.

**Schema mapping.**
- obs_type: `ObservationType.POINT`
- variable: `Variable.ACTIVE_LAYER_THICKNESS`
- value: Active layer depth in cm (convert to meters for SI, or keep cm and record unit)
- unit: "cm"
- latitude/longitude: decimal degrees, WGS84
- depth_m: 0.0 (surface measurement)
- time_start/time_end: DATE/TIME from PANGAEA (single annual measurement, time_end = time_start)
- provenance.source_id: "calm"
- extra: site_code, site_name, gtnp_id, measurement_method, grid_size_m

**Fetch strategy.** Single download from PANGAEA. File is small (~1 MB for 22K records). Compute sha256 checksum. No pagination needed.

**Unit test fixture.** A 15-row TSV with representative Alaska sites including one with a dash (missing data), one with a high value near probe refusal depth, and sites from different ecoregions.
