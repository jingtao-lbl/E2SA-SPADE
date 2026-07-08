"""Target-grid definition for geospatial harmonization.

A `TargetGrid` is the canonical raster a project harmonizes everything onto:
a bbox, a resolution, and a CRS. Per `docs/design/06`, SPADE uses a two-CRS
strategy — an equal-area *analysis* CRS (EPSG:3338, Alaska Albers) for the grid
on which areas/distances/regridding are computed, and EPSG:4326 for storage and
the unified-schema/catalog exchange. `SPADE_GRID_1KM` is the project default.

This module is light (numpy + pyproj only); the heavier reproject/rasterize/
regrid operations live in the sibling modules and take a `TargetGrid`.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from pyproj import CRS, Transformer

STORAGE_CRS = "EPSG:4326"   # unified schema / catalog / exchange
ANALYSIS_CRS = "EPSG:3338"  # Alaska Albers Equal Area; areas, distances, regridding


@dataclass(frozen=True)
class TargetGrid:
    """A regular raster grid in a projected (equal-area) CRS.

    bbox is in the grid's own CRS units (metres for EPSG:3338), ordered
    (west, south, east, north). `resolution_m` is the pixel size in metres.
    """

    bbox: tuple[float, float, float, float]
    resolution_m: float
    crs: str = ANALYSIS_CRS

    def __post_init__(self) -> None:
        w, s, e, n = self.bbox
        if not (e > w and n > s):
            raise ValueError(
                f"bbox must be (west, south, east, north) with e>w, n>s; got {self.bbox}"
            )
        if self.resolution_m <= 0:
            raise ValueError(f"resolution_m must be positive; got {self.resolution_m}")
        if CRS.from_user_input(self.crs).is_geographic:
            raise ValueError(
                f"TargetGrid CRS should be projected (metre units), not geographic; "
                f"got {self.crs}. Use an equal-area CRS such as EPSG:3338."
            )

    @property
    def width(self) -> int:
        w, _, e, _ = self.bbox
        return int(np.ceil((e - w) / self.resolution_m))

    @property
    def height(self) -> int:
        _, s, _, n = self.bbox
        return int(np.ceil((n - s) / self.resolution_m))

    @property
    def shape(self) -> tuple[int, int]:
        """(rows, cols) = (height, width)."""
        return (self.height, self.width)

    @property
    def transform(self):
        """Affine transform (top-left origin, north-up) for rasterio/rioxarray."""
        from affine import Affine

        w, _, _, n = self.bbox
        return Affine(self.resolution_m, 0.0, w, 0.0, -self.resolution_m, n)

    def cell_centers(self) -> tuple[np.ndarray, np.ndarray]:
        """1-D arrays of cell-center x (cols) and y (rows) coordinates, in the grid CRS."""
        w, s, e, n = self.bbox
        xs = w + (np.arange(self.width) + 0.5) * self.resolution_m
        ys = n - (np.arange(self.height) + 0.5) * self.resolution_m
        return xs, ys

    def bbox_in(self, crs: str) -> tuple[float, float, float, float]:
        """This grid's bbox transformed into another CRS (e.g. STORAGE_CRS for a 4326 extent)."""
        w, s, e, n = self.bbox
        t = Transformer.from_crs(self.crs, crs, always_xy=True)
        xs, ys = t.transform([w, e, w, e], [s, n, n, s])
        return (min(xs), min(ys), max(xs), max(ys))


# SPADE default: 1 km Alaska-wide grid in Alaska Albers (docs/design/06).
# The 4326 extent (-168, 54, -130, 72) is transformed to EPSG:3338 and rounded
# out to the nearest km so the grid origin is clean.
def _spade_1km() -> TargetGrid:
    t = Transformer.from_crs(STORAGE_CRS, ANALYSIS_CRS, always_xy=True)
    lons = [-168.0, -130.0, -168.0, -130.0]
    lats = [54.0, 54.0, 72.0, 72.0]
    xs, ys = t.transform(lons, lats)
    west = np.floor(min(xs) / 1000.0) * 1000.0
    east = np.ceil(max(xs) / 1000.0) * 1000.0
    south = np.floor(min(ys) / 1000.0) * 1000.0
    north = np.ceil(max(ys) / 1000.0) * 1000.0
    return TargetGrid(bbox=(west, south, east, north), resolution_m=1000.0, crs=ANALYSIS_CRS)


SPADE_GRID_1KM = _spade_1km()
