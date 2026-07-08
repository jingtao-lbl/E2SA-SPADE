"""Tests for the cross-source-consistency check (e2sa.qc.cross_source).

Builds two-provider ALT observations (mirroring CALM in-situ vs ABoVE gridded)
and asserts the check co-locates by great-circle radius, reports the median
ratio, flags disagreements as candidate sites, handles single-provider variables
(skipped) and non-overlapping providers (warned).
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from e2sa.qc.cross_source import check_cross_source_consistency
from e2sa.schema import Observation, ObservationType, Provenance, Variable


def _obs(source: str, lat: float, lon: float, value: float,
         var: Variable = Variable.ACTIVE_LAYER_THICKNESS,
         depth_m: float | None = 0.0, unit: str = "m") -> Observation:
    return Observation(
        obs_id=f"{source}_{lat}_{lon}_{value}_{depth_m}",
        obs_type=ObservationType.POINT,
        variable=var,
        value=value,
        unit=unit,
        latitude=lat,
        longitude=lon,
        depth_m=depth_m,
        time_start=datetime(2020, 7, 1, tzinfo=UTC),
        time_end=datetime(2020, 7, 1, tzinfo=UTC),
        provenance=Provenance(
            source_id=source,
            source_url="x",
            access_timestamp=datetime.now(tz=UTC),
            content_checksum="c",
            adapter_version="0.1.0",
        ),
    )


class TestCrossSourceConsistency:
    def test_colocated_agreement_and_disagreement(self) -> None:
        # CALM anchor sites; ABoVE cells ~0.3 km away. Two agree (ratio ~1), one
        # disagrees sharply (ABoVE reads ~half). ABoVE is the denser source (as in
        # reality: ~206k cells vs ~1.2k CALM sites), so CALM anchors and the ratio
        # is ABoVE/CALM, matching the finding's convention. The two extra far ABoVE
        # cells make it the larger set; they are too distant to co-locate.
        obs = [
            _obs("calm_alt", 68.61, -149.31, 0.53),
            _obs("calm_alt", 69.15, -148.85, 0.41),
            _obs("calm_alt", 64.84, -163.72, 0.69),   # the disagreement site
            _obs("above_stdm", 68.612, -149.312, 0.55),  # ~0.3 km -> ratio 1.04
            _obs("above_stdm", 69.151, -148.852, 0.43),  # ~0.2 km -> ratio 1.05
            _obs("above_stdm", 64.842, -163.722, 0.35),  # ~0.3 km -> ratio 0.51
            _obs("above_stdm", 70.10, -148.00, 0.50),    # far, no match
            _obs("above_stdm", 71.20, -156.00, 0.45),    # far, no match
        ]
        findings = check_cross_source_consistency(obs, radius_km=5.0, ratio_tol=0.2)
        assert len(findings) == 1
        f = findings[0]
        assert f.check == "cross_source_consistency"
        assert f.severity == "warning"
        assert f.detail["variable"] == "active_layer_thickness"
        assert f.detail["n_colocated"] == 3
        assert f.detail["median_ratio"] == pytest.approx(1.04, abs=0.05)
        assert f.detail["n_disagreements"] == 1
        worst = f.detail["worst_sites"][0]
        assert worst["lat"] == pytest.approx(64.84, abs=0.01)
        assert worst["ratio"] == pytest.approx(0.51, abs=0.05)

    def test_single_provider_is_skipped(self) -> None:
        obs = [
            _obs("calm_alt", 68.61, -149.31, 0.53),
            _obs("calm_alt", 69.15, -148.85, 0.41),
        ]
        assert check_cross_source_consistency(obs) == []

    def test_two_providers_no_spatial_overlap_warns(self) -> None:
        # Same variable, two sources, but hundreds of km apart -> no co-location.
        obs = [
            _obs("calm_alt", 68.61, -149.31, 0.53),
            _obs("above_stdm", 60.00, -160.00, 0.50),
        ]
        findings = check_cross_source_consistency(obs, radius_km=5.0)
        assert len(findings) == 1
        assert findings[0].check == "cross_source_no_overlap"
        assert findings[0].severity == "warning"

    def test_radius_excludes_far_pairs(self) -> None:
        # The ABoVE cell is ~12 km away; with a 5 km radius it must not match.
        obs = [
            _obs("calm_alt", 68.61, -149.31, 0.53),
            _obs("above_stdm", 68.72, -149.31, 0.50),  # ~12 km north
        ]
        findings = check_cross_source_consistency(obs, radius_km=5.0)
        assert findings[0].check == "cross_source_no_overlap"

    def test_anchors_on_smaller_source(self) -> None:
        # One CALM site, three ABoVE cells nearby -> anchors on CALM (1 pair),
        # not on the 3 ABoVE points.
        obs = [
            _obs("calm_alt", 68.61, -149.31, 0.50),
            _obs("above_stdm", 68.611, -149.311, 0.52),
            _obs("above_stdm", 68.609, -149.309, 0.48),
            _obs("above_stdm", 68.610, -149.312, 0.50),
        ]
        findings = check_cross_source_consistency(obs, radius_km=5.0)
        assert findings[0].detail["n_colocated"] == 1  # one CALM anchor
        # ABoVE mean ~0.50 vs CALM 0.50 -> ratio ~1.0
        assert findings[0].detail["median_ratio"] == pytest.approx(1.0, abs=0.05)


def _temp(source: str, lat: float, lon: float, value: float, depth: float) -> Observation:
    return _obs(source, lat, lon, value, var=Variable.GROUND_TEMPERATURE,
                depth_m=depth, unit="degC")


class TestIntervalScaleDifference:
    """Temperature (interval scale) is cross-checked by DIFFERENCE, not ratio,
    and a co-located temperature pair is never misreported as non-overlapping
    (the 2026-07-06 GTN-P/TSP bug: negatives skipped -> empty ratios -> false
    'no overlap')."""

    def test_temperature_uses_difference_and_agrees(self) -> None:
        # TSP (1 obs, smaller -> anchor) vs GTN-P (2 obs). Co-located, same depth,
        # values -8.0 vs -8.4 -> difference -0.4 degC (agreement, no ratio).
        obs = [
            _temp("tsp", 68.60, -149.60, -8.0, depth=10.0),
            _temp("gtnp_magt", 68.601, -149.601, -8.4, depth=10.0),
            _temp("gtnp_magt", 60.00, -160.00, -1.0, depth=10.0),  # far, no match
        ]
        findings = check_cross_source_consistency(obs, radius_km=5.0, diff_tol=2.0)
        assert len(findings) == 1
        f = findings[0]
        assert f.check == "cross_source_consistency"
        assert f.detail["metric"] == "difference"
        assert f.detail["median_difference"] == pytest.approx(-0.4, abs=0.01)
        assert f.detail["n_disagreements"] == 0
        assert "median_ratio" not in f.detail  # not a ratio for temperature

    def test_temperature_disagreement_flagged(self) -> None:
        obs = [
            _temp("tsp", 68.60, -149.60, -8.0, depth=10.0),
            _temp("gtnp_magt", 68.601, -149.601, -3.0, depth=10.0),  # +5 degC off
        ]
        findings = check_cross_source_consistency(obs, radius_km=5.0, diff_tol=2.0)
        assert findings[0].detail["n_disagreements"] == 1
        # |diff| = 5 degC (sign depends on which equal-size source anchors).
        assert abs(findings[0].detail["worst_sites"][0]["diff"]) == pytest.approx(5.0, abs=0.01)

    def test_depth_mismatch_excludes_pair(self) -> None:
        # Same location, but anchor at 2 m and other at 50 m -> not comparable,
        # so no co-location (a 2 m reading must not be compared to a 50 m one).
        obs = [
            _temp("tsp", 68.60, -149.60, -8.0, depth=2.0),
            _temp("gtnp_magt", 68.601, -149.601, -5.0, depth=50.0),
        ]
        findings = check_cross_source_consistency(obs, radius_km=5.0, depth_tol_m=1.0)
        assert findings[0].check == "cross_source_no_overlap"

    def test_surface_depth_none_and_zero_co_locate(self) -> None:
        # Regression (2026-07-06 full run): a surface quantity where one source
        # emits depth_m=0.0 (CALM) and the other emits None (ABoVE) MUST still
        # co-locate. Depth-awareness must not treat 0.0 and None as different.
        obs = [
            _obs("calm_alt", 68.60, -149.60, 0.53, depth_m=0.0),
            _obs("above_stdm", 68.601, -149.601, 0.55, depth_m=None),
        ]
        findings = check_cross_source_consistency(obs, radius_km=5.0)
        assert findings[0].check == "cross_source_consistency"  # not no_overlap
        assert findings[0].detail["n_colocated"] == 1

    def test_colocated_but_ratio_uncomputable_is_distinct(self) -> None:
        # A ratio-scale variable (ALT) co-located but with non-positive values:
        # spatially overlapping, yet the ratio is uncomputable. Must be reported
        # as its own finding, NOT as 'no overlap'.
        obs = [
            _obs("calm_alt", 68.60, -149.60, 0.0),
            _obs("above_stdm", 68.601, -149.601, 0.0),
        ]
        findings = check_cross_source_consistency(obs, radius_km=5.0)
        assert findings[0].check == "cross_source_metric_uncomputable"
