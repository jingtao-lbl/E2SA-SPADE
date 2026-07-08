"""Vector-to-raster conversion onto a TargetGrid.

Three modes (docs/design/06 §1), all via fine-subpixel rasterization then block
reduction (each subpixel is equal-area in the grid's equal-area CRS, so a block
mean is an area weighting):

- `rasterize_fraction`   -> fraction of each cell covered by the polygons (e.g.
                            thermokarst wetland % per pixel). Continuous [0, 1].
- `rasterize_area_weighted` -> area-weighted mean of a continuous polygon attribute.
- `rasterize_categorical`   -> majority (mode) category per cell.

Input GeoDataFrames are reprojected to the grid CRS first. `subpixel` (default 5)
trades accuracy for memory: each cell is rasterized as subpixel x subpixel.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from e2sa.harmonize.crs import reproject_vector
from e2sa.harmonize.grid import TargetGrid


def _fine_grid(grid: TargetGrid, subpixel: int) -> TargetGrid:
    return TargetGrid(bbox=grid.bbox, resolution_m=grid.resolution_m / subpixel, crs=grid.crs)


def _block_reduce(arr: np.ndarray, factor: int, func) -> np.ndarray:
    """Reduce a (factor*H, factor*W) array to (H, W) by applying `func` per block."""
    h, w = arr.shape[0] // factor, arr.shape[1] // factor
    arr = arr[: h * factor, : w * factor]
    blocks = arr.reshape(h, factor, w, factor)
    return func(blocks, axis=(1, 3))


def rasterize_fraction(gdf: Any, grid: TargetGrid, *, subpixel: int = 5) -> np.ndarray:
    """Fraction of each cell covered by the polygon union, in [0, 1]; shape grid.shape."""
    from rasterio.features import rasterize

    g = reproject_vector(gdf, grid.crs)
    fine = _fine_grid(grid, subpixel)
    mask = rasterize(
        ((geom, 1) for geom in g.geometry if geom is not None),
        out_shape=fine.shape,
        transform=fine.transform,
        fill=0,
        all_touched=False,
        dtype="uint8",
    ).astype("float64")
    return _block_reduce(mask, subpixel, np.mean)


def rasterize_area_weighted(
    gdf: Any, value_field: str, grid: TargetGrid, *, subpixel: int = 5
) -> np.ndarray:
    """Area-weighted mean of `value_field` per cell; NaN where no polygon covers the cell."""
    from rasterio.features import rasterize

    g = reproject_vector(gdf, grid.crs)
    fine = _fine_grid(grid, subpixel)
    val = rasterize(
        ((geom, float(v)) for geom, v in zip(g.geometry, g[value_field], strict=True)
         if geom is not None),
        out_shape=fine.shape,
        transform=fine.transform,
        fill=np.nan,
        all_touched=False,
        dtype="float64",
    )
    # Block-mean ignoring NaN (uncovered subpixels). Suppress all-NaN-slice warnings.
    with np.errstate(invalid="ignore"):
        h, w = grid.height, grid.width
        blocks = val[: h * subpixel, : w * subpixel].reshape(h, subpixel, w, subpixel)
        return np.nanmean(blocks, axis=(1, 3))


def rasterize_categorical(
    gdf: Any, value_field: str, grid: TargetGrid, *, subpixel: int = 5
) -> tuple[np.ndarray, dict[int, Any]]:
    """Majority-vote category per cell.

    Returns (codes, code_map) where `codes` is an int array of grid.shape (0 = no
    category / no coverage) and `code_map` maps code -> original category value.
    """
    from rasterio.features import rasterize

    g = reproject_vector(gdf, grid.crs)
    cats = list(dict.fromkeys(g[value_field].tolist()))  # stable unique
    code_map = {i + 1: c for i, c in enumerate(cats)}
    cat_to_code = {c: i + 1 for i, c in enumerate(cats)}

    fine = _fine_grid(grid, subpixel)
    coded = rasterize(
        ((geom, cat_to_code[v]) for geom, v in zip(g.geometry, g[value_field], strict=True)
         if geom is not None),
        out_shape=fine.shape,
        transform=fine.transform,
        fill=0,
        all_touched=False,
        dtype="int32",
    )
    h, w, f = grid.height, grid.width, subpixel
    blocks = coded[: h * f, : w * f].reshape(h, f, w, f).transpose(0, 2, 1, 3).reshape(h, w, f * f)
    out = np.zeros((h, w), dtype="int32")
    for r in range(h):
        for c in range(w):
            vals = blocks[r, c]
            vals = vals[vals != 0]
            if vals.size:
                u, counts = np.unique(vals, return_counts=True)
                out[r, c] = u[np.argmax(counts)]
    return out, code_map
