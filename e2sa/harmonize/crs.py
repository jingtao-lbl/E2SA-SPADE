"""CRS normalization: detect, reproject (vector + raster), datum-aware transforms.

The two-CRS strategy (docs/design/06): reproject to `STORAGE_CRS` (EPSG:4326) for
the unified schema/catalog, and to the `TargetGrid` CRS (`ANALYSIS_CRS`, EPSG:3338
Alaska Albers) for area/distance/regridding. Original CRS is recorded by the caller
in provenance.

Vector ops use geopandas/pyproj; raster ops use rasterio.warp. Heavier deps are
imported lazily so importing this module is cheap.
"""
from __future__ import annotations

from typing import Any

from e2sa.harmonize.grid import ANALYSIS_CRS, STORAGE_CRS, TargetGrid


def detect_vector_crs(gdf: Any) -> str | None:
    """Return the EPSG/authority string of a GeoDataFrame's CRS, or None if absent."""
    return None if gdf.crs is None else gdf.crs.to_string()


def reproject_vector(gdf: Any, dst_crs: str, *, assume_if_missing: str = STORAGE_CRS):
    """Reproject a GeoDataFrame to `dst_crs`.

    If the input has no CRS, assume `assume_if_missing` (default WGS84) with a
    warning rather than silently mislabeling — many legacy shapefiles omit a .prj.
    Reprojects only when needed.
    """
    if gdf.crs is None:
        import warnings

        warnings.warn(
            f"vector layer has no CRS; assuming {assume_if_missing}. "
            "Record this as a low-confidence assumption in provenance.",
            stacklevel=2,
        )
        gdf = gdf.set_crs(assume_if_missing)
    if gdf.crs.to_string() == dst_crs or (gdf.crs.to_epsg() == _epsg(dst_crs)):
        return gdf
    return gdf.to_crs(dst_crs)


def to_storage(gdf: Any):
    """Reproject a GeoDataFrame to the storage CRS (EPSG:4326)."""
    return reproject_vector(gdf, STORAGE_CRS)


def to_analysis(gdf: Any):
    """Reproject a GeoDataFrame to the analysis CRS (EPSG:3338)."""
    return reproject_vector(gdf, ANALYSIS_CRS)


def reproject_raster_to_grid(
    src_array: Any,
    src_transform: Any,
    src_crs: str,
    grid: TargetGrid,
    *,
    resampling: str = "bilinear",
    src_nodata: float | None = None,
    dst_nodata: float | None = None,
):
    """Warp a source raster onto a `TargetGrid` (its CRS, transform, shape).

    `resampling` is a rasterio.warp.Resampling name ("bilinear"/"nearest"/"average"/
    "mode" etc.). Returns a numpy array of shape `grid.shape`. Use "nearest"/"mode"
    for categorical data, "bilinear"/"average" for continuous.
    """
    import numpy as np
    from rasterio.enums import Resampling
    from rasterio.warp import reproject

    dst = np.full(grid.shape, dst_nodata if dst_nodata is not None else np.nan, dtype="float64")
    reproject(
        source=np.asarray(src_array, dtype="float64"),
        destination=dst,
        src_transform=src_transform,
        src_crs=src_crs,
        dst_transform=grid.transform,
        dst_crs=grid.crs,
        resampling=getattr(Resampling, resampling),
        src_nodata=src_nodata,
        dst_nodata=dst_nodata,
    )
    return dst


def transform_points(lons: Any, lats: Any, src_crs: str, dst_crs: str):
    """Transform parallel x/y (lon/lat) arrays from `src_crs` to `dst_crs`. always_xy."""
    from pyproj import Transformer

    t = Transformer.from_crs(src_crs, dst_crs, always_xy=True)
    return t.transform(lons, lats)


def _epsg(crs: str) -> int | None:
    from pyproj import CRS

    return CRS.from_user_input(crs).to_epsg()
