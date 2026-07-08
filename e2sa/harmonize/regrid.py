"""Resolution harmonization: point-to-grid aggregation and raster resampling.

Per docs/design/06: never resample silently — the caller picks the method.
- `point_to_grid`: assign points to the grid cell they fall in; aggregate when
  several land in one cell (mean / median / count / first).
- `regrid_raster`: up/down-sample a source raster onto a `TargetGrid` (delegates
  to crs.reproject_raster_to_grid; bilinear/average for continuous, nearest/mode
  for categorical).

Points come in as parallel lon/lat arrays in STORAGE_CRS (4326) and are transformed
to the grid CRS before binning, so binning is done in equal-area space.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from e2sa.harmonize.crs import reproject_raster_to_grid, transform_points
from e2sa.harmonize.grid import STORAGE_CRS, TargetGrid

_AGG = {
    "mean": np.nanmean,
    "median": np.nanmedian,
    "max": np.nanmax,
    "min": np.nanmin,
    "sum": np.nansum,
}


def point_to_grid(
    lons: Any,
    lats: Any,
    values: Any,
    grid: TargetGrid,
    *,
    method: str = "mean",
    src_crs: str = STORAGE_CRS,
) -> np.ndarray:
    """Bin scattered points onto `grid`; aggregate multiple points per cell.

    Returns a float array of shape `grid.shape`, NaN where no point falls.
    `method` in {mean, median, max, min, sum, count}. Points are transformed from
    `src_crs` to the grid CRS first (binning happens in equal-area space).
    """
    lons = np.asarray(lons, dtype="float64")
    lats = np.asarray(lats, dtype="float64")
    values = np.asarray(values, dtype="float64")
    xs, ys = transform_points(lons, lats, src_crs, grid.crs)
    xs, ys = np.asarray(xs), np.asarray(ys)

    w, s, e, n = grid.bbox
    col = np.floor((xs - w) / grid.resolution_m).astype(int)
    row = np.floor((n - ys) / grid.resolution_m).astype(int)
    inside = (col >= 0) & (col < grid.width) & (row >= 0) & (row < grid.height)

    out = np.full(grid.shape, np.nan, dtype="float64")
    if method == "count":
        out[:] = 0.0
    flat = row[inside] * grid.width + col[inside]
    vals = values[inside]

    # group values by flat cell index
    order = np.argsort(flat)
    flat_s, vals_s = flat[order], vals[order]
    for cell, start, stop in _group_spans(flat_s):
        r, c = divmod(cell, grid.width)
        chunk = vals_s[start:stop]
        out[r, c] = len(chunk) if method == "count" else _AGG[method](chunk)
    return out


def regrid_raster(
    src_array: Any,
    src_transform: Any,
    src_crs: str,
    grid: TargetGrid,
    *,
    categorical: bool = False,
    upsample: bool | None = None,
) -> np.ndarray:
    """Resample a source raster onto `grid`.

    Method follows doc 06: continuous -> bilinear (upsample) / average (downsample);
    categorical -> nearest (upsample) / mode (downsample). Pass `upsample=True` when
    going coarse->fine and `upsample=False` when going fine->coarse. The default
    (`upsample=None`) treats it as upsampling (continuous->bilinear, categorical->nearest).
    """
    if categorical:
        method = "nearest" if upsample is not False else "mode"
    else:
        method = "bilinear" if upsample is not False else "average"
    return reproject_raster_to_grid(src_array, src_transform, src_crs, grid, resampling=method)


def _group_spans(sorted_keys: np.ndarray):
    """Yield (key, start, stop) spans over a sorted integer key array."""
    if len(sorted_keys) == 0:
        return
    boundaries = np.flatnonzero(np.diff(sorted_keys)) + 1
    starts = np.concatenate(([0], boundaries))
    stops = np.concatenate((boundaries, [len(sorted_keys)]))
    for st, sp in zip(starts, stops, strict=True):
        yield int(sorted_keys[st]), int(st), int(sp)
