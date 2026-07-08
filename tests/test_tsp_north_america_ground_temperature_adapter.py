"""Tests for TSPNorthAmericaGroundTemperatureAdapter.

Covers: registration + capability routing (a second GROUND_TEMPERATURE provider),
list_available (the 10-year series), fetch delegation, and parse_to_schema with
the real gotchas the parse handles (UTF-8 BOM data CSVs, roster `Filename`
authoritative over `SiteCode`, blank-temperature rows skipped, roster rows with
no data file skipped, depth in metres, obs_id uniqueness). The fixture mirrors
the real source units (degC + metres) and the real BagIt shape.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from e2sa.data.adapters.tsp_north_america_ground_temperature import (
    SOURCE_ID,
    YEAR_DOI,
    TSPNorthAmericaGroundTemperatureAdapter,
    _parse_coord,
    _parse_date,
    dataset_id_for_year,
)
from e2sa.data.base import BaseAdapter
from e2sa.data.registry import ADAPTER_REGISTRY, sources_for_variables
from e2sa.qc.checks import validate_observations
from e2sa.schema import CANONICAL_UNITS, ObservationType, Variable

FIXTURE = Path(__file__).parent / "fixtures" / "tsp_pkg"
DATASET_ID = dataset_id_for_year(2023)


def _build_fixture_adapter(tmp_path: Path) -> TSPNorthAmericaGroundTemperatureAdapter:
    """Copy the fixture into the Option C layout (raw/<data_center>/<dataset_id>/)."""
    raw_dir = tmp_path / "raw"
    target = raw_dir / "arctic_data_center" / DATASET_ID
    shutil.copytree(FIXTURE, target)
    return TSPNorthAmericaGroundTemperatureAdapter(raw_dir=raw_dir)


class TestRegistration:
    def test_registered(self) -> None:
        assert ADAPTER_REGISTRY[SOURCE_ID] is TSPNorthAmericaGroundTemperatureAdapter

    def test_is_base_adapter_subclass(self) -> None:
        assert issubclass(TSPNorthAmericaGroundTemperatureAdapter, BaseAdapter)

    def test_serves_ground_temperature(self) -> None:
        assert TSPNorthAmericaGroundTemperatureAdapter.serves == frozenset(
            {Variable.GROUND_TEMPERATURE}
        )

    def test_capability_index_routes_ground_temperature(self) -> None:
        idx = sources_for_variables([Variable.GROUND_TEMPERATURE])
        assert SOURCE_ID in idx[Variable.GROUND_TEMPERATURE]
        # gtnp is the first provider; TSP makes two (the cross-source pair).
        assert "gtnp_magt" in idx[Variable.GROUND_TEMPERATURE]

    def test_soil_temperature_equivalence_also_routes_to_tsp(self) -> None:
        # SOIL_TEMPERATURE == GROUND_TEMPERATURE routing (VARIABLE_EQUIVALENCE).
        idx = sources_for_variables([Variable.SOIL_TEMPERATURE])
        assert SOURCE_ID in idx[Variable.SOIL_TEMPERATURE]


class TestListAvailable:
    def test_returns_full_annual_series(self, tmp_path: Path) -> None:
        adapter = TSPNorthAmericaGroundTemperatureAdapter(raw_dir=tmp_path)
        datasets = adapter.list_available()
        assert len(datasets) == len(YEAR_DOI) == 10
        ids = {d.dataset_id for d in datasets}
        assert dataset_id_for_year(2016) in ids
        assert dataset_id_for_year(2025) in ids
        assert all(d.variables == ["ground_temperature"] for d in datasets)

    def test_2023_has_verified_citation_and_doi(self, tmp_path: Path) -> None:
        adapter = TSPNorthAmericaGroundTemperatureAdapter(raw_dir=tmp_path)
        ds = next(d for d in adapter.list_available() if d.dataset_id == DATASET_ID)
        assert ds.url and "10.18739/A2DB7VR9J" in ds.url
        assert ds.citation and "Romanovsky" in ds.citation

    def test_unverified_years_leave_citation_none(self, tmp_path: Path) -> None:
        # Never fabricate authors: only the inspected 2023 year carries a citation.
        adapter = TSPNorthAmericaGroundTemperatureAdapter(raw_dir=tmp_path)
        ds = next(
            d for d in adapter.list_available()
            if d.dataset_id == dataset_id_for_year(2016)
        )
        assert ds.citation is None


class TestFetch:
    def test_unknown_dataset_id_raises(self, tmp_path: Path) -> None:
        adapter = TSPNorthAmericaGroundTemperatureAdapter(raw_dir=tmp_path)
        with pytest.raises(KeyError):
            adapter.fetch("not_a_real_year")

    def test_on_disk_package_returns_fetch_result(self, tmp_path: Path) -> None:
        adapter = _build_fixture_adapter(tmp_path)
        fr = adapter.fetch(DATASET_ID)
        assert fr.dataset_id == DATASET_ID
        assert fr.local_path.exists()
        assert fr.content_checksum


class TestParseToSchema:
    def _obs(self, tmp_path: Path):
        adapter = _build_fixture_adapter(tmp_path)
        return adapter.parse_to_schema(adapter.fetch(DATASET_ID))

    def test_expected_observation_count(self, tmp_path: Path) -> None:
        # BRW_101: 3 rows; BRW_201: 3 rows but 1 blank temp skipped -> 2;
        # US_XXX: roster row whose file is truly absent -> 0;
        # CPT: roster Filename wrong (_101) but _001 file recovered -> 2. Total = 7.
        assert len(self._obs(tmp_path)) == 7

    def test_recovers_misnamed_roster_filename(self, tmp_path: Path) -> None:
        # Real 2023 trap: roster row US_CPT_101 declares US_CPT_101_..._.csv but the
        # on-disk file is US_CPT_001_..._.csv. Must recover by site-prefix + date,
        # not silently drop the site.
        obs = self._obs(tmp_path)
        cpt = [o for o in obs if o.extra["site_code"] == "US_CPT_101"]
        assert len(cpt) == 2
        assert all(o.extra["source_file"] == "US_CPT_001_2023_10_03.csv" for o in cpt)

    def test_all_ground_temperature_profiles_canonical_unit(self, tmp_path: Path) -> None:
        obs = self._obs(tmp_path)
        assert all(o.variable == Variable.GROUND_TEMPERATURE for o in obs)
        assert all(o.obs_type == ObservationType.PROFILE for o in obs)
        assert all(o.unit == "degC" for o in obs)
        assert all(o.unit == CANONICAL_UNITS[Variable.GROUND_TEMPERATURE] for o in obs)

    def test_depth_in_metres_and_populated(self, tmp_path: Path) -> None:
        obs = self._obs(tmp_path)
        assert all(o.depth_m is not None and o.depth_m > 0 for o in obs)
        assert 12.0 in {o.depth_m for o in obs}  # BRW_101 shallowest reading

    def test_temperature_values_preserved(self, tmp_path: Path) -> None:
        obs = self._obs(tmp_path)
        assert any(o.value == pytest.approx(-6.966) for o in obs)

    def test_blank_temperature_row_skipped(self, tmp_path: Path) -> None:
        # BRW_201's 10 m row has a blank temperature -> not emitted.
        obs = self._obs(tmp_path)
        brw201 = [o for o in obs if o.extra["source_file"] == "US_BRW_201_2023_07_27.csv"]
        assert len(brw201) == 2
        assert 10.0 not in {o.depth_m for o in brw201}

    def test_filename_authoritative_over_site_code(self, tmp_path: Path) -> None:
        # Roster SiteCode US_BRW_102 points at Filename US_BRW_201_...csv (real
        # mismatch). Join must follow `Filename`, and carry GTNP_ID US49.
        obs = self._obs(tmp_path)
        site102 = [o for o in obs if o.extra["site_code"] == "US_BRW_102"]
        assert site102, "US_BRW_102 site not parsed (Filename linkage failed)"
        assert all(
            o.extra["source_file"] == "US_BRW_201_2023_07_27.csv" for o in site102
        )
        assert all(o.extra["gtnp_id"] == "US49" for o in site102)

    def test_roster_row_without_file_skipped(self, tmp_path: Path) -> None:
        obs = self._obs(tmp_path)
        assert not any(o.extra["site_code"] == "US_XXX_001" for o in obs)

    def test_obs_ids_unique(self, tmp_path: Path) -> None:
        obs = self._obs(tmp_path)
        ids = [o.obs_id for o in obs]
        assert len(set(ids)) == len(ids)

    def test_serves_subset_of_emitted(self, tmp_path: Path) -> None:
        obs = self._obs(tmp_path)
        emitted = {o.variable for o in obs}
        assert TSPNorthAmericaGroundTemperatureAdapter.serves.issubset(emitted)

    def test_full_provenance(self, tmp_path: Path) -> None:
        obs = self._obs(tmp_path)
        for o in obs:
            assert o.provenance.source_id == SOURCE_ID
            assert o.provenance.adapter_version
            assert o.provenance.content_checksum
            assert o.provenance.license == "CC0 1.0 Universal Public Domain Dedication"

    def test_qc_clean_by_construction(self, tmp_path: Path) -> None:
        # Skill step 7: validate_observations must return no error-severity findings.
        obs = self._obs(tmp_path)
        findings = validate_observations(
            TSPNorthAmericaGroundTemperatureAdapter.serves, obs
        )
        errors = [f for f in findings if f.severity == "error"]
        assert errors == [], f"QC errors: {[(f.code, f.detail) for f in errors]}"


class TestParseHelpers:
    def test_parse_coord_degree_symbol(self) -> None:
        assert _parse_coord("71.31° ") == pytest.approx(71.31)
        assert _parse_coord("") is None

    def test_parse_date_roster_and_filename_fallback(self) -> None:
        assert _parse_date("07/27/23", "x.csv").strftime("%Y-%m-%d") == "2023-07-27"
        # blank roster date -> recover from the filename YYYY_MM_DD token
        got = _parse_date("", "US_BRW_101_2023_07_27.csv")
        assert got is not None and got.strftime("%Y-%m-%d") == "2023-07-27"
