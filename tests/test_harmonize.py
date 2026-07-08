"""Tests for e2sa.harmonize (geospatial harmonization, docs/design/06).

Synthetic fixtures only — no network, no large files. Covers the TargetGrid,
CRS reprojection, point-to-grid binning, vector-to-raster (fraction / area-weighted
/ categorical), and temporal aggregation.
"""
from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest

# harmonize imports pyproj at module load (grid.py); skip the whole module cleanly
# on a base install without the [geo] extra rather than erroring at collection.
pytest.importorskip("pyproj")

from e2sa.harmonize import SPADE_GRID_1KM, TargetGrid
from e2sa.harmonize import crs as hcrs
from e2sa.harmonize import rasterize as hr
from e2sa.harmonize import regrid as hg
from e2sa.harmonize import temporal as ht
from e2sa.schema import Observation, ObservationType, Provenance, Variable

# A small projected (EPSG:3338) grid: 10 km square at 1 km resolution.
GRID = TargetGrid(bbox=(0.0, 0.0, 10_000.0, 10_000.0), resolution_m=1000.0, crs="EPSG:3338")


def _prov() -> Provenance:
    return Provenance(
        source_id="test", access_timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        content_checksum="x", adapter_version="0",
    )


class TestTargetGrid:
    def test_shape_and_transform(self) -> None:
        assert GRID.shape == (10, 10)
        assert GRID.transform.a == 1000.0 and GRID.transform.e == -1000.0

    def test_rejects_geographic_crs(self) -> None:
        with pytest.raises(ValueError, match="projected"):
            TargetGrid(bbox=(0, 0, 1, 1), resolution_m=0.1, crs="EPSG:4326")

    def test_spade_grid_is_albers_1km(self) -> None:
        assert SPADE_GRID_1KM.crs == "EPSG:3338"
        assert SPADE_GRID_1KM.resolution_m == 1000.0
        assert SPADE_GRID_1KM.shape[0] > 1000  # Alaska-wide


class TestCRS:
    def test_transform_points_roundtrip(self) -> None:
        lon, lat = -149.9, 61.2  # Anchorage-ish
        x, y = hcrs.transform_points([lon], [lat], "EPSG:4326", "EPSG:3338")
        lon2, lat2 = hcrs.transform_points(x, y, "EPSG:3338", "EPSG:4326")
        assert lon2[0] == pytest.approx(lon, abs=1e-6)
        assert lat2[0] == pytest.approx(lat, abs=1e-6)

    def test_reproject_vector_warns_without_crs(self) -> None:
        gpd = pytest.importorskip("geopandas")
        from shapely.geometry import Point

        g = gpd.GeoDataFrame({"v": [1]}, geometry=[Point(-150, 61)], crs=None)
        with pytest.warns(UserWarning, match="no CRS"):
            out = hcrs.reproject_vector(g, "EPSG:3338")
        assert out.crs.to_epsg() == 3338


class TestPointToGrid:
    def test_mean_and_count_binning(self) -> None:
        # Two points in the same SW cell (in 3338 == grid CRS, passed as src_crs).
        lons = [500.0, 600.0, 5500.0]
        lats = [500.0, 400.0, 5500.0]
        vals = [10.0, 20.0, 99.0]
        mean_grid = hg.point_to_grid(lons, lats, vals, GRID, method="mean", src_crs="EPSG:3338")
        cnt_grid = hg.point_to_grid(lons, lats, vals, GRID, method="count", src_crs="EPSG:3338")
        # SW cell is the bottom row (row 9), col 0.
        assert mean_grid[9, 0] == pytest.approx(15.0)
        assert cnt_grid[9, 0] == 2
        assert np.isnan(mean_grid[0, 0])  # empty cell


class TestRasterize:
    def _square(self, x0, y0, x1, y1, val):
        gpd = pytest.importorskip("geopandas")
        from shapely.geometry import box

        return gpd.GeoDataFrame({"v": [val]}, geometry=[box(x0, y0, x1, y1)], crs="EPSG:3338")

    def test_fraction_full_and_half(self) -> None:
        pytest.importorskip("rasterio")
        full = self._square(0, 0, 10_000, 10_000, 1)  # covers everything
        frac = hr.rasterize_fraction(full, GRID, subpixel=5)
        assert frac.min() == pytest.approx(1.0)
        half = self._square(0, 0, 10_000, 5_000, 1)  # covers southern half
        fh = hr.rasterize_fraction(half, GRID, subpixel=5)
        assert fh[9, 5] == pytest.approx(1.0)   # southern row fully covered
        assert fh[0, 5] == pytest.approx(0.0)   # northern row empty

    def test_categorical_majority(self) -> None:
        pytest.importorskip("rasterio")
        gpd = pytest.importorskip("geopandas")
        from shapely.geometry import box

        g = gpd.GeoDataFrame(
            {"zone": ["A", "B"]},
            geometry=[box(0, 0, 10_000, 6_000), box(0, 6_000, 10_000, 10_000)],
            crs="EPSG:3338",
        )
        codes, code_map = hr.rasterize_categorical(g, "zone", GRID, subpixel=5)
        inv = {v: k for k, v in code_map.items()}
        assert codes[9, 5] == inv["A"]   # southern cell -> A
        assert codes[0, 5] == inv["B"]   # northern cell -> B


class TestTemporal:
    def test_aggregate_to_annual_mean(self) -> None:
        obs = [
            Observation(obs_id=f"o{m}", obs_type=ObservationType.POINT,
                        variable=Variable.SOIL_TEMPERATURE, value=float(m), unit="degC",
                        latitude=61.0, longitude=-150.0, depth_m=0.1,
                        time_start=datetime(2020, m, 1, tzinfo=UTC), provenance=_prov())
            for m in range(1, 13)
        ]
        agg = ht.aggregate_to_annual(obs, method="mean")
        # one group, year 2020, mean of 1..12 = 6.5
        (val,) = agg.values()
        assert val == pytest.approx(6.5)

    def test_event_is_time_independent(self) -> None:
        e = Observation(obs_id="e", obs_type=ObservationType.EVENT,
                        variable=Variable.THAW_EVENT_LABEL, value=1.0, unit="1",
                        latitude=61.0, longitude=-150.0,
                        time_start=datetime(2020, 1, 1, tzinfo=UTC), provenance=_prov())
        assert ht.is_time_independent(e) is True
        assert ht.aggregate_to_annual([e]) == {}  # skipped

    def test_broadcast_static(self) -> None:
        assert ht.broadcast_static("dem", [2019, 2020]) == {2019: "dem", 2020: "dem"}
