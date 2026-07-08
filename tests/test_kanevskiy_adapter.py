"""Tests for KanevskiyCryostratigraphyAdapter.

Covers: list_available, fetch (on-disk verify + missing-package error),
parse_to_schema with three schema variants (standard, Canadian Arctic site,
positional lat/lon fallback), and the gotchas the parse logic handles
(EIC=0 kept, blank EIC skipped, depth range midpoint, obs_id uniqueness).
Geographic filtering is downstream (RunConfig.bbox), not in-adapter: the
adapter emits all sites faithfully (PI ruling 2026-06-30, F3/A3).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from e2sa.data.adapters.kanevskiy_2024_cryostratigraphy import (
    DATASET_ID,
    KanevskiyCryostratigraphyAdapter,
    _parse_coord,
)
from e2sa.data.base import BaseAdapter
from e2sa.data.registry import ADAPTER_REGISTRY, sources_for_variables
from e2sa.schema import ObservationType, Variable

FIXTURE = Path(__file__).parent / "fixtures" / "kanevskiy_pkg"


def _adapter(tmp_path: Path) -> KanevskiyCryostratigraphyAdapter:
    """Build an adapter whose raw_dir points at the fixture package."""
    # The adapter computes self.raw_dir = raw_dir / source_id, so to land it
    # on the fixture pkg we pass the fixture's parent.
    return KanevskiyCryostratigraphyAdapter(raw_dir=FIXTURE.parent.parent / "fixtures_root_alias")


class TestParseCoord:
    """Degree-symbol coordinate parsing (real Tuktoyaktuk/Canadian files write
    coords like '69.015 ' decorated with a degree mark; a bare float() would
    drop every such row). Regression for the 2026-06-30 faithful-policy finding."""

    def test_plain_float(self) -> None:
        assert _parse_coord("69.015") == pytest.approx(69.015)

    def test_degree_symbol_and_trailing_space(self) -> None:
        assert _parse_coord("69.015° ") == pytest.approx(69.015)

    def test_negative_with_degree(self) -> None:
        assert _parse_coord("-133.279°") == pytest.approx(-133.279)

    def test_masculine_ordinal_variant(self) -> None:
        assert _parse_coord("69.015º") == pytest.approx(69.015)

    def test_blank_and_garbage_return_none(self) -> None:
        assert _parse_coord("") is None
        assert _parse_coord("n/a") is None


class TestRegistration:
    def test_registered_in_adapter_registry(self) -> None:
        assert "kanevskiy_2024_cryostratigraphy" in ADAPTER_REGISTRY
        assert (
            ADAPTER_REGISTRY["kanevskiy_2024_cryostratigraphy"]
            is KanevskiyCryostratigraphyAdapter
        )

    def test_is_subclass_of_base_adapter(self) -> None:
        assert issubclass(KanevskiyCryostratigraphyAdapter, BaseAdapter)

    def test_serves_declared(self) -> None:
        assert KanevskiyCryostratigraphyAdapter.serves == frozenset(
            {Variable.EXCESS_ICE_CONTENT}
        )

    def test_capability_index_routes_to_kanevskiy(self) -> None:
        # The capability index must surface Kanevskiy for EXCESS_ICE_CONTENT queries.
        index = sources_for_variables([Variable.EXCESS_ICE_CONTENT])
        assert "kanevskiy_2024_cryostratigraphy" in index[Variable.EXCESS_ICE_CONTENT]


class TestListAvailable:
    def test_returns_one_dataset_serving_eic(self, tmp_path: Path) -> None:
        adapter = KanevskiyCryostratigraphyAdapter(raw_dir=tmp_path)
        datasets = adapter.list_available()
        assert len(datasets) == 1
        ds = datasets[0]
        assert ds.dataset_id == DATASET_ID
        assert "excess_ice_content" in ds.variables
        assert ds.url and "10.18739/A2H12V928" in ds.url


class TestFetch:
    def test_delegates_to_connector_and_surfaces_fallback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # No package on disk: the adapter delegates fetch to the connector, which
        # tries a live download. With the network mocked to fail, the connector's
        # manual-download fallback must surface through the adapter (proving the
        # delegation path). The connector layer is tested directly in
        # test_connector.py; here we only assert the adapter routes through it.
        import urllib.error

        from e2sa.data.connectors import arctic_data_center

        def fail(*a, **k):
            raise urllib.error.URLError("no network")

        monkeypatch.setattr(arctic_data_center.urllib.request, "urlopen", fail)
        adapter = KanevskiyCryostratigraphyAdapter(raw_dir=tmp_path)
        with pytest.raises(FileNotFoundError) as exc_info:
            adapter.fetch(DATASET_ID)
        msg = str(exc_info.value)
        assert "10.18739/A2H12V928" in msg
        assert "bagit.txt" in msg

    def test_unknown_dataset_id_raises_key_error(self, tmp_path: Path) -> None:
        adapter = KanevskiyCryostratigraphyAdapter(raw_dir=tmp_path)
        with pytest.raises(KeyError):
            adapter.fetch("not_a_real_dataset")

    def test_on_disk_package_returns_fetch_result(self, tmp_path: Path) -> None:
        # Symlink/copy the fixture into the expected raw_dir layout, then fetch.
        adapter = _build_fixture_adapter(tmp_path)
        result = adapter.fetch(DATASET_ID)
        assert result.dataset_id == DATASET_ID
        assert result.local_path.exists()
        assert result.bytes_downloaded > 0
        assert result.content_checksum
        assert len(result.files) >= 4  # bagit.txt + manifest + 3 csvs


class TestParseToSchema:
    def test_emits_expected_observations(self, tmp_path: Path) -> None:
        adapter = _build_fixture_adapter(tmp_path)
        result = adapter.fetch(DATASET_ID)
        obs = adapter.parse_to_schema(result)

        # Itkillik file: 4 rows of which 3 are real (blank EIC skipped on row 5);
        # Bylot file: 1 row, EMITTED faithfully (Canadian Arctic, not filtered);
        # Teshekpuk 2023 file: 1 row, positional lat/lon fallback used.
        # Total expected: 3 (Itkillik) + 1 (Bylot) + 1 (Teshekpuk) = 5.
        assert len(obs) == 5

    def test_all_observations_are_excess_ice_content(self, tmp_path: Path) -> None:
        adapter = _build_fixture_adapter(tmp_path)
        obs = adapter.parse_to_schema(adapter.fetch(DATASET_ID))
        assert all(o.variable == Variable.EXCESS_ICE_CONTENT for o in obs)
        assert all(o.unit == "1" for o in obs)  # canonical dimensionless (was "fraction")
        assert all(o.obs_type == ObservationType.PROFILE for o in obs)

    def test_eic_percent_converted_to_fraction(self, tmp_path: Path) -> None:
        adapter = _build_fixture_adapter(tmp_path)
        obs = adapter.parse_to_schema(adapter.fetch(DATASET_ID))
        # Raw EIC values in fixture: 13.4, 0, 5.0 (Itkillik), 8.5 (Teshekpuk),
        # 25.0 (Bylot, now emitted faithfully). After /100: 0.134, 0, 0.05,
        # 0.085, 0.25.
        values = sorted(o.value for o in obs)
        assert values == pytest.approx([0.0, 0.05, 0.085, 0.134, 0.25])

    def test_zero_eic_is_kept(self, tmp_path: Path) -> None:
        # EIC=0 means "no excess ice" — real data, must NOT be treated as missing.
        adapter = _build_fixture_adapter(tmp_path)
        obs = adapter.parse_to_schema(adapter.fetch(DATASET_ID))
        zeros = [o for o in obs if o.value == 0.0]
        assert len(zeros) == 1

    def test_canadian_sites_emitted_faithfully(self, tmp_path: Path) -> None:
        # Faithful adapter (PI ruling 2026-06-30): the Bylot (Canadian Arctic)
        # row, EIC=25.0, IS emitted; region scoping is downstream via
        # RunConfig.bbox, not in-adapter.
        adapter = _build_fixture_adapter(tmp_path)
        obs = adapter.parse_to_schema(adapter.fetch(DATASET_ID))
        assert any("Bylot" in o.extra["source_file"] for o in obs)
        assert any(o.value == pytest.approx(0.25) for o in obs)

    def test_depth_range_midpoint_in_meters(self, tmp_path: Path) -> None:
        # "76-87" should become midpoint 81.5 cm = 0.815 m.
        adapter = _build_fixture_adapter(tmp_path)
        obs = adapter.parse_to_schema(adapter.fetch(DATASET_ID))
        depths = {o.depth_m for o in obs}
        assert 0.815 in depths

    def test_positional_lat_lon_fallback(self, tmp_path: Path) -> None:
        # Teshekpuk 2023 file has blank Latitude/Longitude sub-row labels.
        # Must still recover lat=71.27718, lon=-156.45657 positionally.
        adapter = _build_fixture_adapter(tmp_path)
        obs = adapter.parse_to_schema(adapter.fetch(DATASET_ID))
        teshekpuk = [o for o in obs if o.extra["source_file"].startswith("Teshekpuk")]
        assert len(teshekpuk) == 1
        assert teshekpuk[0].latitude == pytest.approx(71.27718)
        assert teshekpuk[0].longitude == pytest.approx(-156.45657)

    def test_obs_ids_unique(self, tmp_path: Path) -> None:
        adapter = _build_fixture_adapter(tmp_path)
        obs = adapter.parse_to_schema(adapter.fetch(DATASET_ID))
        ids = [o.obs_id for o in obs]
        assert len(set(ids)) == len(ids)

    def test_obs_id_includes_required_components(self, tmp_path: Path) -> None:
        # obs_id must include borehole + lat + lon + depth + date (collision guard).
        adapter = _build_fixture_adapter(tmp_path)
        obs = adapter.parse_to_schema(adapter.fetch(DATASET_ID))
        for o in obs:
            assert "kanevskiy" in o.obs_id
            assert "cm" in o.obs_id
            # date YYYYMMDD at end
            assert o.obs_id.split("_")[-1].isdigit()

    def test_serves_is_subset_of_emitted(self, tmp_path: Path) -> None:
        # Skill guardrail: declared serves MUST be a subset of what we actually emit.
        adapter = _build_fixture_adapter(tmp_path)
        obs = adapter.parse_to_schema(adapter.fetch(DATASET_ID))
        emitted = {o.variable for o in obs}
        assert KanevskiyCryostratigraphyAdapter.serves.issubset(emitted)

    def test_full_provenance_attached(self, tmp_path: Path) -> None:
        adapter = _build_fixture_adapter(tmp_path)
        obs = adapter.parse_to_schema(adapter.fetch(DATASET_ID))
        for o in obs:
            p = o.provenance
            assert p.source_id == "kanevskiy_2024_cryostratigraphy"
            assert p.adapter_version
            assert p.content_checksum
            assert p.license == "CC0 1.0 Universal Public Domain Dedication"


def _build_fixture_adapter(tmp_path: Path) -> KanevskiyCryostratigraphyAdapter:
    """Copy the fixture into the Option C layout so the connector finds it.

    Connector-backed adapter: data lands at raw_dir/<data_center>/<dataset_id>/.
    The adapter's raw_dir is the top-level raw dir; fetch delegates to the
    arctic_data_center connector, which reads raw_dir/arctic_data_center/<slug>/.
    """
    import shutil

    raw_dir = tmp_path / "raw"
    target = raw_dir / "arctic_data_center" / DATASET_ID
    shutil.copytree(FIXTURE, target)
    return KanevskiyCryostratigraphyAdapter(raw_dir=raw_dir)
