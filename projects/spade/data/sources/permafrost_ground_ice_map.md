# Circum-Arctic Map of Permafrost and Ground-Ice Conditions, Version 2

Brown, J., O.J. Ferrians Jr., J.A. Heginbottom, and E.S. Melnikov. 2002.
Circum-Arctic Map of Permafrost and Ground-Ice Conditions, Version 2. NSIDC.
DOI: 10.7265/skbg-kf16
Also known as: Heginbottom et al. (2002) in the permafrost literature.

## Role in SPADE

Baseline comparison and feature layer. This is one of the two widely used ground ice maps that the Alaska Thaw Database paper (Webb et al. 2026) evaluates against, finding 27% inter-map disagreement and 35-40% misclassification when compared to observed thaw locations. Producing a better ice content map is a primary motivation for SPADE.

For the ice content model, this map provides:
1. A coarse prior on permafrost extent and ground ice abundance per pixel
2. An existing-map baseline to compare SPADE's predictions against
3. A feature layer (permafrost zone classification) for conditioning the generative model


## Access

| Field | Value |
|---|---|
| DOI | https://doi.org/10.7265/skbg-kf16 |
| NSIDC page | https://nsidc.org/data/ggd318/versions/2 |
| FTP | ftp://sidads.colorado.edu/pub/DATASETS/fgdc/ggd318_map_circumarctic/ |
| Formats | ESRI Shapefile (vector) + EASE-Grid (raster, 12.5 km / 25 km / 0.5 deg) |
| License | NSIDC (free, no authentication for FTP) |
| Scale | 1:10,000,000 (derived from 1997 paper map) |

No Earthdata Login required for FTP download.

## Variables

### Permafrost extent (5 classes)

| Class | Description |
|---|---|
| Continuous | 90-100% of area underlain by permafrost |
| Discontinuous | 50-90% |
| Sporadic | 10-50% |
| Isolated | less than 10% |
| None | No permafrost |

### Ground ice content (4 volume-percentage classes, upper 20 m)

| Class | Volume percentage |
|---|---|
| High | greater than 20% |
| Medium | 10-20% |
| Low | less than 10% |
| None | 0% |

### Additional features

- Subsea permafrost locations
- Relict permafrost locations

## Spatial coverage

- Circum-Arctic, Northern Hemisphere (20N to 90N, global longitude)
- Raster grid options at 12.5 km, 25 km, and 0.5 degree resolution
- Shapefile at 1:10,000,000 scale (polygon boundaries)
- EASE-Grid projection for raster versions (NSIDC EASE-Grid North, EPSG:3408 or similar)

## Temporal coverage

Single snapshot. Based on data compiled through the mid-1990s, published as a paper map in 1997, digitized and released as Version 2 in 2002. Represents historical conditions, not current state.

## Known gotchas

1. **Coarse resolution.** 12.5 to 25 km raster, or 1:10M scale polygons. Much coarser than SPADE's target (1 km or 30 m). Useful as a prior, not as ground truth.
2. **Outdated.** Based on pre-2000 data. Permafrost has degraded significantly since, especially in discontinuous and sporadic zones. The map overestimates current permafrost extent in warming regions.
3. **Categorical, not continuous.** Ground ice is in 4 discrete classes, not a continuous fraction. SPADE aims to produce continuous values with uncertainty.
4. **Two formats, different projections.** Shapefile is in geographic coordinates. EASE-Grid raster is in the NSIDC EASE-Grid projection. Need CRS handling for both.
5. **FTP access.** Download via FTP, not HTTPS or earthaccess. Requires `ftplib` or `wget`. FTP may be blocked on some institutional networks.
6. **Webb et al. (2026) findings.** When overlaid with the Alaska Thaw Database, this map shows substantial misclassification. Abrupt thaw points occur in areas mapped as low or no ground ice at rates much higher than expected. This is the gap SPADE is designed to fill.

## Adapter design notes

**Recommended format.** Download the EASE-Grid raster at 12.5 km resolution (smallest available). This avoids the need for vector-to-raster conversion. If finer spatial detail from the polygons is needed, download the shapefile and rasterize using the harmonization module.

**Schema mapping.** This is a raster/polygon dataset, not point observations. Same situation as the thermokarst circumpolar map. Options:
- Rasterize to the SPADE target grid (1 km) and store as a feature layer in `projects/spade/data/processed/features/`
- For the EASE-Grid raster, reproject from EASE-Grid to EPSG:3338 (Alaska Albers) and resample to 1 km

**Two variables per pixel after rasterization.**
- `permafrost_extent_class` (0-4, mapping to none/isolated/sporadic/discontinuous/continuous)
- `ground_ice_class` (0-3, mapping to none/low/medium/high)

**Fetch strategy.** FTP download via `ftplib` or `urllib.request.urlretrieve`. Files are small (a few MB). No authentication.

**Comparison analysis.** After SPADE produces its ice content map, overlay this map to quantify how much SPADE's continuous predictions disagree with the categorical classifications, and whether the disagreement regions coincide with the Webb et al. (2026) misclassification hotspots.
