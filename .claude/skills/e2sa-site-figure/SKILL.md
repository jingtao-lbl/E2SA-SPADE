---
name: e2sa-site-figure
description: Produce a publication-quality study-site / watershed / regional map figure for an E2SA project, from public-data download through layered matplotlib rendering. Use when the user wants to "make a site/study-area/watershed map", "plot a DEM map with sites overlaid and labeled", "download a DEM and plot it", "stage HUC-8 boundaries", "build the overview/region figure", or "add/rescope a study site". The config-driven reference scripts live in projects/spade/tools/site_figure/. The report agent's mapping step (E2SA S9) is a downstream consumer. NOT for conceptual/architecture diagrams (use proposal-figure), data/time-series plots, or slides.
allowed-tools: [Read, Glob, Grep, Write, Edit, Bash]
---

# e2sa-site-figure

A reproducible pipeline that turns "we want a study-site / map figure" into a
publication-ready geospatial figure, from public-data download. Config-driven and
project-agnostic. Reference scripts: `projects/spade/tools/site_figure/` (run them;
this skill is the spec + conventions). Distilled from the DOE ECRP AlaskaHUC figure
set, genericized.

## When to fire

- Build/rebuild a study-area / watershed / regional map figure that layers real
  geospatial data (boundaries, terrain, point networks, infrastructure, events).
- Add, rename, or rescope a study site in an existing figure set.
- The E2SA ReportAgent (S9) needs a site/region map.

Do NOT use for conceptual/architecture figures (`proposal-figure`), model-output or
time-series plots, or slides. For a one-line tweak (font, one marker), edit the
affected script directly.

## Environment

Geospatial venv: `geopandas`, `rasterio`, `shapely`, `pyproj`, `matplotlib`, `numpy`
(the `[geo]` extra in `pyproject.toml`). Run scripts from the repo root.

## Coordinate reference systems (read before plotting)

Work in **one CRS end to end: geographic EPSG:4326 (lon/lat degrees)**.
1. **Reproject every vector layer to 4326 on load** — `geo_helpers.to_4326(gdf)` (the
   defensive idiom: convert only if `crs is None or to_epsg() != 4326`).
2. **DEM rasters**: 3DEP tiles are 4326; plot via `imshow(dem, extent=(W,E,S,N))` so
   the raster lands in the same lon/lat axes as the vectors. Bbox, `total_bounds`,
   centroids, `within()` filters are all computed in 4326.
3. **Plain lon/lat matplotlib axes — no projected cartopy CRS** — keeps annotation
   offsets, label placement, arc geometry in simple data coordinates.

**Tradeoff to caption:** plain lon/lat axes stretch horizontally at high latitude
(a degree of longitude is ~0.4x a degree of latitude at 68N). Fine for a context
figure. For true-shape distances or a north-up conic look, switch to a cartopy
projection (Alaska Albers EPSG:3338 / `ccrs.AlbersEqualArea`) and transform layers
with `transform=ccrs.PlateCarree()`, at the cost of the simpler annotation math.

## What goes into a "site" (define before any script runs)

1. **Site ID + label** — filename token (`example_site`) + human label.
2. **Boundary codes** — HUC-8 (or the dataset's polygon key). **Confirm against the
   real shapefile**; planning guesses are usually wrong.
3. **Bbox** — `[west, south, east, north]` EPSG:4326, polygon extent + ~0.2-0.4 deg
   buffer. From `gdf.total_bounds`, rounded.
4. **Theme tag** — one phrase reused in caption + log.
5. **Point-feature targets** — what the map must show (infra, gauges, field sites, events).
6. **(Optional) observation anchor** — an existing monitoring network the site hangs on.

These live in `sites.json` (copy `sites.example.json`); curated/infra/event features in
an optional `layers.json`.

## The pipeline (numbered scripts in `projects/spade/tools/site_figure/`)

Staging scripts (01-04) are **idempotent** (skip work on disk).

```
geo_helpers.py            shared: download, to_4326, write_geojson, manual_hillshade,
                          terrain_trunc, ZORDER convention
01_download_boundaries.py boundary polygons (WBD HU2 zip -> shapefiles; config URL)
02_confirm_codes.py       bbox spatial query -> confirmed codes CSV (log corrections)
03_stage_dems.py          3DEP tiles -> mosaic -> clip per site bbox
04_stage_layers.py        NWIS gauges (live) + curated/infra/event layers (layers.json) -> GeoJSON
05_figure_template.py     generic per-site labeled + _nolabels figure
```

Add **derived-geometry builders** (e.g. event tracks, transport axes synthesized from
metadata rather than downloaded) when a figure needs a computed overlay with no
public-data source; write GeoJSON the figure scripts consume.

### Staging notes
- **01**: `download_with_progress` skips if present + non-empty, then extract + list shapefiles.
- **02**: spatial-query each site bbox, tighten by name keyword, write confirmed codes; verify every site has >=1 match; log every correction vs. the guess.
- **03**: `required_tiles(bbox)` (integer 1x1-deg tiles); unauthenticated S3 XML prefix listing; current->historical fallback; `rasterio.merge` then `rasterio.mask.mask(..., crop=True)`. Cache tiles, reuse across sites; `[miss]` for ocean-only tiles is expected. 3DEP ~30 m is figure-grade; ArcticDEM (PGC, 2 m) is the high-latitude upgrade.
- **04**: EPSG:4326 GeoJSON, one file per layer class; each feature carries `name`/`type`/`source`/`site_assoc`. NWIS gauges fetched live (statewide), filtered per site at render via `geometry.within(box(*bbox))`. **Remap `site_assoc` whenever sites are renamed.**

### Per-site figure — the zorder layer convention (bottom -> top)

| z | layer | style |
|---|---|---|
| 0 | hillshade | `Greys_r`, alpha 0.85 |
| 1 | DEM elevation | `terrain_trunc()`, alpha 0.40, vmin 0 vmax ~2500 |
| 2 | other boundaries | black, lw 0.7 |
| 2.5 | sub-watershed | black, lw 0.3, alpha 0.5 |
| 3 | site boundary | black, lw 2.4 (single) / 3.2 (multi-panel) |
| 4 | dashed routes | barge / ferry |
| 5 | linear infrastructure | lw 3.5 |
| 6 | gauges | bright cyan `^`, black edge |
| 7 | curated obs | per-type marker/size/color |
| 8 | facilities / labels | stars; white-bg label boxes |
| 10 | event markers | role-coded color/shape/size |
| 12 | event labels | annotation boxes |

The two reusable helpers (`terrain_trunc` drops the gray->white tail; `manual_hillshade`
dodges the `LightSource.hillshade` np.gradient TypeError) are in `geo_helpers.py`.
Other conventions: `font.size=13`; per-feature `(dx,dy,ha)` text-offset dicts for dense
clusters; bright fill + contrasting edge so markers pop above hillshade; downsample the
DEM (`[::4]`) for speed. **Always render a `_nolabels` companion** (same geometry, no
title/axes/annotations/legend) for manual annotation.

### Manifest + caption
Write a layer-manifest JSON + a ~100-word caption per figure with inline citations
(captions double as narrative source text).

## Refinement passes (expect several)

| Trigger | Fix |
|---|---|
| Labels stack/collide | per-feature `(dx,dy,ha)` offset dict |
| "Can barely see X" | font 13, markers 2-3x, terser tokens |
| "Where does this sit?" | add other-boundary overlay, consistent black |
| Watershed clipped at edge | recompute `total_bounds` + buffer, re-stage DEM (03) |
| Elevation ramp reads as gray noise | `terrain_trunc()` |
| Marker invisible on hillshade | bright fill + contrasting edge + larger + alpha 0.95 |

## Renaming / rescoping (single edit pass, or intermediate states render mixed)

- [ ] confirmed-codes CSV `site_id`
- [ ] each `*.geojson` `site_assoc`
- [ ] `sites.json` keys + DEM filenames
- [ ] figure script titles + output names
- [ ] caption + narrative cross-references
- [ ] back up old outputs `*_v<N>_YYYYMMDD.{png,pdf}` (don't overwrite)

## Verification checklist

1. Every site has confirmed boundary codes in the CSV.
2. Every DEM opens with rasterio at the expected bounds.
3. Every GeoJSON loads with valid geometry + expected count.
4. Each PNG shows the required classes (terrain, observations, infra, events).
5. Labeled variant: consistent fonts, marker sizes, truncated colormap.
6. `_nolabels` variant matches geometry, strips all text.
7. Each figure has a layer manifest + caption.

## Data-source catalog

| Dataset | What | Access |
|---|---|---|
| USGS WBD (HUC-2…12) | watershed boundary polygons | TNM staged S3 `prd-tnm.s3.amazonaws.com/StagedProducts/Hydrography/WBD/...` |
| USGS 3DEP 1-arcsec | ~30 m national DEM | TNM S3 `StagedProducts/Elevation/1/TIFF/current/<tile>/` |
| ArcticDEM (PGC/UMN) | 2 m Arctic DEM + strips | https://www.pgc.umn.edu/data/arcticdem/ — high-latitude upgrade |
| USGS NWIS | live streamflow gauge inventory | `waterservices.usgs.gov` RDB |
| (per-domain) | infrastructure, monitoring networks | curate from published sources; store provenance per feature |

## Cross-links

- Reference scripts + README: `projects/spade/tools/site_figure/`.
- Consumers: the ReportAgent (S9 maps, `docs/design/11`); harmonization (`docs/design/06`) reuses the CRS-to-4326 + DEM staging machinery.
- Companions: `proposal-figure` (conceptual figures); the global `geospatial-site-figure` skill is the proposal-side origin.

## Changelog
- 2026-06-22: Initial E2SA version. Copied from the global `geospatial-site-figure` skill and genericized (no site locations / project specifics); reference scripts genericized into `projects/spade/tools/site_figure/` (config-driven `sites.json`/`layers.json`, shared `geo_helpers.py`, one figure template instead of per-region scripts).
