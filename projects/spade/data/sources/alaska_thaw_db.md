# Alaska Permafrost Thaw Database

**Webb, H., Pierce, E., Abbott, B. W., Bowden, W. B., Chen, Yaping, Chen, Yating, Douglas, T. A., Eklof, J. F., Euskirchen, E. S., Langer, M., Myers-Smith, I. H., Overeem, I., Strauss, J., Walter Anthony, K., Wang, K., Whitley, M. A., and Turetsky, M. R.** (2026). A comprehensive database of thawing permafrost locations across Alaska: version 2.0.0. *Earth System Science Data* 18:3147. doi:10.5194/essd-18-3147-2026. https://essd.copernicus.org/articles/18/3147/2026/

## Role in SPADE

Labeled ground truth. The primary evaluation corpus for ice content predictions and a sparse training signal for the physics-constrained generative model. Also serves as the anchor for comparing existing ground ice maps.

## Access

- Zenodo: https://doi.org/10.5281/zenodo.16996415
- License: CC BY 4.0
- Version: 2.0.0 (described in the paper)
- Format: tabular (point features, likely CSV or GeoPackage)
- No authentication required

## Summary

19,540 permafrost thaw and thermokarst locations across all ecoregions of Alaska, compiled from 44 sources (field observations, remote sensing, published literature). Observations span from 1950 through present. Remotely sensed products range from 1 to 125 m resolution. Statewide coverage.

## Breakdown by feature type

| Category | Count | Requires high ground ice |
|---|---|---|
| Thermokarst lake | 10,625 | Yes |
| Active layer detachment | 5,463 | No |
| Retrogressive thaw slump | 1,450 | Yes |
| Non-abrupt | 1,327 | Never |
| Thermokarst (generic) | 280 | Yes |
| Wildfire-induced thaw | 209 | No |
| Thermokarst wetland | 134 | Yes |
| Thermoerosional gully | 47 | Yes |
| Thaw pond | 5 | Yes |

18,213 points are abrupt thaw, 1,327 are non-abrupt.

## Schema (Table 3 in paper)

| Field | Format | Description |
|---|---|---|
| Authors | text | Author last name et al. (year) |
| DOI | URL or N/A | Source publication DOI |
| DataSourceType | enum | Field-published, Field-unpublished, Remote sensing-published, Remote sensing-unpublished, Photo interpretation-published/unpublished |
| FeatureName | text | Name of feature or site (may be blank) |
| Latitude | decimal degrees | EPSG:4326 |
| Longitude | decimal degrees | EPSG:4326 |
| FeatureType | text | Type as reported by source (free text) |
| FeatureCategory | enum | One of 10 standardized categories (see breakdown above) |
| ThawType | enum | Abrupt or Non-abrupt |
| Imagery | text | Remote sensing instrument(s) used (blank for field data) |
| ImageryDates | text | Date range of imagery |
| ImageryResolution_meters | numeric | Spatial resolution in meters |

## Key findings relevant to SPADE

**Spatial patterns.** Abrupt thaw concentrated in northern Alaska where near-surface ground ice is abundant. Active layer detachments and retrogressive thaw slumps dominate mountainous areas (Brooks Range). Thermokarst lakes dominate lowland regions (Arctic Tundra, Bering Tundra). Abrupt thaw accounts for more than 97% of features in Arctic Tundra, Bering Tundra, and Brooks Range. Interior Alaska has the most diverse array of abrupt thaw types.

**Ground ice map comparison.** The paper compares existing ground ice maps (Jorgenson et al. 2008 for Alaska, Heginbottom et al. 2002 circumpolar) against the thaw database. Found substantial mismatches, highlighting 35 to 40% misclassification in existing maps. This is a primary motivation for SPADE: producing a better ice content map.

**Abrupt vs non-abrupt classification.** A thaw event is classified as "abrupt" if it develops within 30 years AND meets at least one of: involves substrate with high ground ice (>20%) OR results in a major ecosystem impact. Non-abrupt features have low or no ground ice and take longer than 30 years to emerge.

**Environmental variables extracted at each point via GEE.** Elevation (ArcticDEM 2 m), slope (3x3 window, 6 m neighborhood), aspect (degrees), relative elevation (mean elevation within 100 m minus point elevation), solar radiation index (SRI, Eq. 2 in paper).

## Data quality notes

- All locations standardized to point features (originals included points, polylines, polygons).
- Filtered to zone of mapped permafrost in Alaska only.
- When multiple years available from one source, only the most recent thaw data kept.
- Duplicates removed by matching identical feature names, keeping first occurrence.
- Source-specific post-processing documented in Table 2 of the paper (for example, 820 drained lakes removed from Jones and Zuck 2016, 4,124 duplicate lakes removed from Nitze et al. 2020a).
- No comprehensive quantitative uncertainty analysis possible due to heterogeneity of input sources. Accuracy assumed from original publications.

## Adapter design notes

**Observation type.** Maps to `ObservationType.EVENT`. Each row is a thaw event location, not a continuous measurement.

**Variable mapping.** Use `Variable.THAW_EVENT_LABEL`. The `value` field stores a numeric encoding of FeatureCategory (0-9) or ThawType (0-1) depending on the use case. Alternatively, store FeatureCategory as a string in `extra`.

**CRS.** Already EPSG:4326 (WGS84). No reprojection needed.

**Provenance.** Each record has its own source attribution (Authors, DOI, DataSourceType). The adapter should preserve this per-record provenance, not just a single provenance for the whole dataset.

**Extra fields.** FeatureType (free text from source), ThawType, FeatureCategory, Imagery, ImageryDates, ImageryResolution_meters, DataSourceType, Authors, DOI all go into the `extra` dict on each Observation.

**Gotchas.**
- FeatureName is often blank (especially for remote-sensing-derived features).
- FeatureType is free text from the original source and may not match FeatureCategory exactly.
- Some entries lack imagery metadata (field-based observations have no Imagery, ImageryDates, or ImageryResolution_meters).
- The dataset includes both "thaw happened here" (abrupt, ground truth for P(H)) and "stable permafrost reference" (non-abrupt, control points). Both are valuable but serve different roles.
- Non-abrupt points are located in areas distinct from abrupt features, serving as comparison/control. They do NOT represent all stable permafrost, just locations identified through the same monitoring programs.

**Fetch strategy.** Single download from Zenodo. Check version against expected (2.0.0). Compute sha256 checksum. File is small enough to download in full (19,540 rows).

**Unit test fixture.** A 20-row CSV with representative samples from each FeatureCategory, including one with missing FeatureName and one non-abrupt.

## Verified fetch (2026-05-20)

First live test of the adapter against the real Zenodo endpoint.

| Field | Value |
|---|---|
| URL | `https://zenodo.org/records/17494851/files/ArcticWebb/Alaska_Permafrost_Thaw_Database-v2.0.0.zip?download=1` |
| Local path | `projects/spade/data/raw/alaska_thaw_db/alaska_thaw_db_v2.zip` |
| Size | 3,968,134 bytes (3.97 MB) |
| SHA256 | `04629e01301c17c7cece88ce9979cc8d44f3ccd88157a40a8586f27e264d5159` |
| Parsed observations | 19,540 (exact match with source doc) |
| ThawType totals | 18,213 abrupt + 1,327 non-abrupt (exact match) |

## Breakdown drift between source doc and v2.0.0 actual

Three categories differ by small amounts from this doc's "Breakdown by feature type" table (net zero, total still 19,540):

| Category | This doc | v2.0.0 actual | Delta |
|---|---|---|---|
| Non-abrupt (FeatureCategory) | 1,327 | 1,323 | -4 |
| Thermokarst (generic) | 280 | 281 | +1 |
| Thermokarst wetland | 134 | 137 | +3 |

Likely explanation. The breakdown table here was transcribed from an earlier draft of the paper; v2.0.0 of the released dataset reflects post-publication reclassifications. Note that `ThawType` still totals 1,327 non-abrupt, meaning 4 records carry `ThawType="Non-abrupt"` but `FeatureCategory != "Non-abrupt"`. Internal inconsistency in v2.0.0, not an adapter bug.

## Adapter quirks discovered during the live test


The zip ships four CSVs across two versions plus topographic-variable companions, so blind alphabetical-first selection picks the wrong file. The main v2.0.0 CSV is cp1252-encoded, not UTF-8. Both fixed in `e2sa/data/alaska_thaw_db.py`.
