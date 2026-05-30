# Thermokarst Circumpolar Map (Olefeldt et al. 2016)

Olefeldt, D. et al. 2016. Arctic Circumpolar Distribution and Soil Carbon of Thermokarst Landscapes, 2015. ORNL DAAC.
DOI: 10.3334/ORNLDAAC/1332
Companion paper: Olefeldt et al. 2016, Nature Communications 7, 13043. doi:10.1038/ncomms13043

## Role in SPADE

Spatial prior and feature layer. This circumpolar map of thermokarst landscape distribution provides a polygon-level classification of where thermokarst wetlands, lakes, and hillslope processes occur. For SPADE, it serves as (1) a spatial prior indicating which landscape types are associated with high ground ice, (2) a feature layer for the ice content model, and (3) a comparison dataset for cross-referencing against the Alaska Thaw Database and the predicted ice content map.


## Access

| Field | Value |
|---|---|
| DOI | https://doi.org/10.3334/ORNLDAAC/1332 |
| Format | Shapefile (polygon) |
| Size | ~60 MB |
| License | NASA Earthdata (free, requires Earthdata Login) |
| CMR Concept ID | c2216864090-ornl_cloud |
| Granules | 1 file |
| User guide | Thermokarst_Circumpolar_Map.pdf (companion file) |

Download via `earthaccess`:
```python
import earthaccess
earthaccess.login()
results = earthaccess.search_data(doi="10.3334/ORNLDAAC/1332")
earthaccess.download(results, local_path="./data/raw/thermokarst_circumpolar/")
```

## Summary

Maps the distribution of thermokarst landscapes across boreal and tundra ecoregions within the northern circumpolar permafrost zone as of 2015. Each polygon has attributes for total area and the areal coverage of three thermokarst landscape types, plus soil organic carbon (SOC) storage by type.

## Thermokarst landscape types

| Type | Description | Ground ice relevance |
|---|---|---|
| Thermokarst wetlands | Wetlands formed by permafrost thaw, including bogs, fens, and collapse scars | High ground ice (ice-rich fine-grained sediments) |
| Thermokarst lakes | Lakes formed by thaw of ice-rich permafrost | Very high ground ice (massive ice, ice wedges) |
| Hillslope thermokarst | Retrogressive thaw slumps, active layer detachments, thermal erosion gullies | High ground ice (exposed by slope processes) |

## Shapefile attributes

Based on the dataset description and companion paper, each polygon contains:
- Polygon total area
- Thermokarst wetland area (and percentage)
- Thermokarst lake area (and percentage)
- Hillslope thermokarst area (and percentage)
- Total SOC (0-3 m depth, Pg C)
- SOC stored in each thermokarst landscape type

Exact column names will be confirmed after download and inspection.

## Spatial coverage

- Circumpolar, northern hemisphere
- Bounding box: 45.5N to 83.6N, -180 to 180 longitude
- Covers all permafrost zones (continuous, discontinuous, sporadic, isolated)
- Polygon boundaries follow ecoregion or landscape unit delineations

## Temporal coverage

2015 (single snapshot, based on synthesis of literature and remote sensing up to that year).

## Known gotchas

1. **Shapefile format.** Requires geopandas or fiona to parse. CRS needs to be verified after download (likely a polar projection, will need reprojection to EPSG:4326 for integration).
2. **Coarse resolution.** Polygon-level classification, not pixel-level. The polygons represent landscape units, not individual thermokarst features. Spatial resolution is much coarser than the Alaska Thaw DB point locations.
3. **Circumpolar scope.** Must clip to Alaska bounding box for SPADE use.
4. **SOC units.** Soil organic carbon values may be in Pg C or kg C/m2, need to verify from user guide.
5. **No temporal dynamics.** Single 2015 snapshot. Does not represent temporal change.
6. **Earthdata authentication.** Requires NASA Earthdata Login to download.

## Adapter design notes

**Observation type.** This is a spatial polygon dataset, not a point observation. It does not map directly to the current Observation schema (which expects point/profile/grid_cell/event). Options: (a) convert polygon centroids to GRID_CELL observations with thermokarst percentages as values, (b) use geopandas GeoDataFrame directly as a feature layer without forcing it through the Observation schema, or (c) rasterize to a grid matching the model resolution.

**Recommended approach.** Option (c), rasterize to 1 km grid (matching the baseline model resolution). Each pixel gets three values (wetland %, lake %, hillslope %) from the polygon it falls within. Store as a GeoTIFF feature layer in `projects/spade/data/processed/features/`.

**Fetch strategy.** Single download via earthaccess. SHA256 checksum on the downloaded shapefile.

**Integration with ABoVE adapter.** This dataset is from ORNL DAAC and can be fetched through the same `earthaccess` mechanism as other ABoVE datasets. Could be added to the ABoVE adapter's dataset registry, or kept as a standalone adapter since it is circumpolar (not ABoVE-specific).

## Key reference

Olefeldt, D. et al. (2016). Circumpolar distribution and carbon storage of thermokarst landscapes. Nature Communications 7, 13043. doi:10.1038/ncomms13043
