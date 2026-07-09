"""Tests for Sloan2014BarrowSoilAdapter (e2sa.data.adapters.sloan_2014_barrow_soil).

Adapter side: registration, list_available, fetch-delegation to the ess_dive
connector, and the Sloan-2014 parse (two file shapes, CRS reprojection, AKST/AKDT
-> UTC, sentinel/unknown-plot skipping, provenance). The connector's fetch/auth is
tested in test_ess_dive_connector.py. One opt-in live test runs if ESS_DIVE_TOKEN
is set.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from e2sa.data.adapters.sloan_2014_barrow_soil import Sloan2014BarrowSoilAdapter
from e2sa.data.base import BaseAdapter, FetchResult
from e2sa.data.registry import ADAPTER_REGISTRY, sources_for_variables
from e2sa.schema import Variable

DATASET = "sloan_2014_barrow_soil"
SLOAN_FIXTURE = Path(__file__).parent / "fixtures" / "sloan_30min_pkg"


class TestRegistration:
    def test_registered(self) -> None:
        assert ADAPTER_REGISTRY[DATASET] is Sloan2014BarrowSoilAdapter

    def test_is_subclass_and_connector_backed(self) -> None:
        assert issubclass(Sloan2014BarrowSoilAdapter, BaseAdapter)
        assert Sloan2014BarrowSoilAdapter.data_center == "ess_dive"

    def test_serves_declared(self) -> None:
        assert Sloan2014BarrowSoilAdapter.serves == frozenset(
            {Variable.SOIL_TEMPERATURE}
        )

    def test_capability_index_routes_to_sloan(self) -> None:
        idx = sources_for_variables([Variable.SOIL_TEMPERATURE])
        assert DATASET in idx[Variable.SOIL_TEMPERATURE]


class TestListAvailable:
    def test_returns_sloan(self, tmp_path: Path) -> None:
        adapter = Sloan2014BarrowSoilAdapter(raw_dir=tmp_path)
        datasets = adapter.list_available()
        assert len(datasets) == 1
        sloan = datasets[0]
        assert sloan.dataset_id == DATASET
        assert sloan.url == "https://doi.org/10.5440/1121134"
        assert "Barrow" in sloan.name or "Utqiagvik" in sloan.name
        assert "soil_temperature" in sloan.variables


class TestFetchDelegation:
    def test_fetch_delegates_to_ess_dive_connector(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Warm-cache fast path proves the adapter routes fetch through the
        # ess_dive connector (which reads raw_dir/ess_dive/<dataset_id>/) with
        # no token and no network.
        from e2sa.data.connectors import ess_dive

        dataset_dir = tmp_path / "ess_dive" / DATASET
        dataset_dir.mkdir(parents=True)
        body = b"region,site\nN/A,N/A\n"
        (dataset_dir / "BEO_data.csv").write_bytes(body)
        (dataset_dir / ".essdive_package_id").write_text(json.dumps({
            "id": "cached-id", "files": {"BEO_data.csv": len(body)},
        }))

        def _no_network(*a, **k):
            raise AssertionError("urlopen should not be called (warm cache)")

        monkeypatch.setattr(ess_dive.urllib.request, "urlopen", _no_network)
        monkeypatch.delenv("ESS_DIVE_TOKEN", raising=False)

        adapter = Sloan2014BarrowSoilAdapter(raw_dir=tmp_path)
        result = adapter.fetch(DATASET)
        assert result.local_path == dataset_dir
        assert result.content_checksum == "cached-id"


# ---- parse spec: Sloan 2014 ----


def _sloan_fixture_fetch_result() -> FetchResult:
    return FetchResult(
        dataset_id=DATASET,
        local_path=SLOAN_FIXTURE,
        bytes_downloaded=0,
        access_timestamp=datetime(2026, 6, 18, 12, 0, tzinfo=UTC),
        content_checksum="ess-dive-fixture-pkg-id",
        source_url="https://doi.org/10.5440/1121134",
        files=[],
    )


def _adapter() -> Sloan2014BarrowSoilAdapter:
    return Sloan2014BarrowSoilAdapter(raw_dir=Path("/tmp/test_sloan_adapter"))


class TestParseSloan:
    def test_emits_six_30min_plus_five_perplot_observations(self) -> None:
        obs = _adapter().parse_to_schema(_sloan_fixture_fetch_result())
        n_30min = sum(1 for o in obs if "30min" in o.obs_id)
        n_perplot = sum(1 for o in obs if "perplot" in o.obs_id)
        assert n_30min == 6, f"expected 6 30-min, got {n_30min}"
        assert n_perplot == 5, f"expected 5 per-plot, got {n_perplot}"
        assert len(obs) == 11

    def test_reprojects_to_barrow_area(self) -> None:
        obs = _adapter().parse_to_schema(_sloan_fixture_fetch_result())
        for o in obs:
            assert 71.0 < o.latitude < 71.5, f"lat {o.latitude} not at Barrow"
            assert -156.8 < o.longitude < -156.4, f"lon {o.longitude} not at Barrow"

    def test_depth_cm_converted_to_m(self) -> None:
        obs = _adapter().parse_to_schema(_sloan_fixture_fetch_result())
        assert {o.depth_m for o in obs} == {0.05, 0.15, 0.25}

    def test_akst_converted_to_utc(self) -> None:
        obs = _adapter().parse_to_schema(_sloan_fixture_fetch_result())
        for o in obs:
            assert o.time_start is not None
            assert o.time_start.utcoffset() == timedelta(0)
        earliest = min(o.time_start for o in obs)
        assert earliest == datetime(2012, 6, 24, 4, 0, tzinfo=UTC)

    def test_skips_sentinel_and_unknown_plot_and_malformed(self) -> None:
        obs = _adapter().parse_to_schema(_sloan_fixture_fetch_result())
        assert all(o.value != -9999 for o in obs)
        assert {o.extra["plot_id"] for o in obs} == {"A1C", "A1E"}

    def test_perplot_sentinel_filtered_and_qc_clean(self) -> None:
        # Regression: the per-plot HOBO files carry -9999 error rows (real data:
        # plotB2T_25cm has 6). The per-plot parser must drop them like the 30-min
        # parser does, so no out-of-range soil_temperature leaks into the catalog.
        from e2sa.qc.checks import validate_observations

        obs = _adapter().parse_to_schema(_sloan_fixture_fetch_result())
        perplot = [o for o in obs if "perplot" in o.obs_id]
        assert all(o.value != -9999 for o in perplot)
        findings = validate_observations(Sloan2014BarrowSoilAdapter.serves, obs)
        errors = [f for f in findings if f.severity == "error"]
        assert errors == [], f"expected no QC errors, got {errors}"

    def test_provenance_and_schema_fields(self) -> None:
        obs = _adapter().parse_to_schema(_sloan_fixture_fetch_result())
        for o in obs:
            assert o.variable.value == "soil_temperature"
            assert o.unit == "degC"
            assert o.obs_type.value == "point"
            assert o.provenance.source_id == "sloan_2014_barrow_soil"
            assert o.provenance.content_checksum == "ess-dive-fixture-pkg-id"
            assert o.provenance.source_url == "https://doi.org/10.5440/1121134"
            assert o.provenance.license == "CC-BY-4.0"

    def test_missing_files_raises(self, tmp_path: Path) -> None:
        empty = FetchResult(
            dataset_id=DATASET,
            local_path=tmp_path,
            bytes_downloaded=0,
            access_timestamp=datetime.now(tz=UTC),
            content_checksum="x",
            source_url="https://test.invalid",
        )
        with pytest.raises(FileNotFoundError, match="Sloan 2014 parse expects"):
            _adapter().parse_to_schema(empty)


@pytest.mark.skipif(
    not os.environ.get("ESS_DIVE_TOKEN"),
    reason="ESS_DIVE_TOKEN not set; skip live ESS-DIVE download test.",
)
def test_live_sloan_2014_fetch(tmp_path: Path) -> None:
    """Opt-in: real download against ESS-DIVE prod via the connector."""
    adapter = Sloan2014BarrowSoilAdapter(raw_dir=tmp_path)
    result = adapter.fetch(DATASET)
    assert result.local_path.is_dir()
    assert len(result.files) >= 40  # Sloan 2014 has 47 files
