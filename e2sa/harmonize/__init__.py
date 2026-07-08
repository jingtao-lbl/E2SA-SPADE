"""e2sa.harmonize: geospatial harmonization (docs/design/06).

Align heterogeneous data (point, polygon, raster, time series) to a common spatial
and temporal reference before analysis or modeling. Two-CRS strategy: EPSG:4326 for
storage/exchange, EPSG:3338 (Alaska Albers, equal-area) for the analysis grid.

- `grid`: `TargetGrid` + `SPADE_GRID_1KM` (the canonical raster).
- `crs`: detect / reproject (vector + raster) / transform points; `to_storage`/`to_analysis`.
- `rasterize`: vector -> raster (coverage fraction, area-weighted mean, majority category).
- `regrid`: point-to-grid aggregation; raster up/down-sample onto a `TargetGrid`.
- `temporal`: aggregate sub-annual -> annual, broadcast static, flag event/time-independent.
- `units`: convert source units to the per-Variable canonical unit; validate the contract.

Heavy deps (rasterio/geopandas/shapely/scipy) are imported lazily inside functions,
so importing this package is cheap. They are the `[geo]` extra in pyproject.
"""
from __future__ import annotations

from e2sa.harmonize.grid import (
    ANALYSIS_CRS,
    SPADE_GRID_1KM,
    STORAGE_CRS,
    TargetGrid,
)
from e2sa.harmonize.units import (
    canonical_unit,
    convert,
    to_canonical,
    validate_canonical_units,
)

__all__ = [
    "TargetGrid",
    "SPADE_GRID_1KM",
    "STORAGE_CRS",
    "ANALYSIS_CRS",
    "convert",
    "to_canonical",
    "canonical_unit",
    "validate_canonical_units",
]
