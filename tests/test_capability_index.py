"""Tests for the Variable-keyed capability index in e2sa/data/registry.py.

Covers: index correctness, the soil/ground-temperature equivalence, unserved
variables, the no-empty-serves guard, a regression lock on each adapter's
declared serves, and a live serves-subset-of-emitted consistency check against
the single-file fixtures. See docs/design/14 and the scoping log
memory/dev_logs/20260622b_*.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from e2sa.data.adapters.above_stdm import ABoVEAdapter
from e2sa.data.adapters.calm_alt import CALMAdapter
from e2sa.data.adapters.gtnp_magt import GTNPAdapter
from e2sa.data.base import FetchResult
from e2sa.data.registry import (
    ADAPTER_REGISTRY,
    CAPABILITY_INDEX,
    adapter_capabilities,
    sources_for_variables,
)
from e2sa.schema import Variable

FIXTURES = Path(__file__).parent / "fixtures"


def _fr(fixture: str) -> FetchResult:
    p = FIXTURES / fixture
    return FetchResult(
        dataset_id="test",
        local_path=p,
        bytes_downloaded=p.stat().st_size,
        access_timestamp=datetime(2026, 4, 12, tzinfo=UTC),
        content_checksum="fixture_checksum",
        source_url="https://test.invalid",
    )


# Regression lock: the serves each adapter declares today. Changing an adapter's
# serves must be a conscious update here too.
EXPECTED_SERVES = {
    "calm_alt": frozenset({Variable.ACTIVE_LAYER_THICKNESS}),
    "gtnp_magt": frozenset({Variable.GROUND_TEMPERATURE}),
    "webb_2026_alaska_thaw_db": frozenset({Variable.THAW_EVENT_LABEL}),
    "above_stdm": frozenset(
        {
            Variable.ACTIVE_LAYER_THICKNESS,
            Variable.VOLUMETRIC_WATER_CONTENT,
        }
    ),
    "sloan_2014_barrow_soil": frozenset({Variable.SOIL_TEMPERATURE}),
    "kanevskiy_2024_cryostratigraphy": frozenset({Variable.EXCESS_ICE_CONTENT}),
    "tsp_north_america_ground_temperature": frozenset({Variable.GROUND_TEMPERATURE}),
}


class TestDeclarations:
    def test_every_registered_adapter_declares_nonempty_serves(self) -> None:
        empty = [sid for sid, cls in ADAPTER_REGISTRY.items() if not cls.serves]
        assert empty == [], f"adapters with empty serves (invisible to discovery): {empty}"

    def test_serves_members_are_valid_variables(self) -> None:
        for sid, cls in ADAPTER_REGISTRY.items():
            for v in cls.serves:
                assert isinstance(v, Variable), f"{sid} declares non-Variable {v!r}"

    def test_serves_matches_expected_regression(self) -> None:
        assert adapter_capabilities() == EXPECTED_SERVES


class TestCapabilityIndex:
    def test_index_built_at_import_and_nonempty(self) -> None:
        # Built from class attrs only (no adapter instantiation / no I/O).
        assert CAPABILITY_INDEX
        assert CAPABILITY_INDEX[Variable.ACTIVE_LAYER_THICKNESS] == ["above_stdm", "calm_alt"]

    def test_sources_for_a_served_variable(self) -> None:
        got = sources_for_variables([Variable.THAW_EVENT_LABEL])
        assert got == {Variable.THAW_EVENT_LABEL: ["webb_2026_alaska_thaw_db"]}

    def test_unserved_variable_maps_to_empty(self) -> None:
        # No adapter serves air temperature or ice content yet.
        got = sources_for_variables([Variable.AIR_TEMPERATURE, Variable.VOLUMETRIC_ICE_CONTENT])
        assert got == {Variable.AIR_TEMPERATURE: [], Variable.VOLUMETRIC_ICE_CONTENT: []}


class TestSoilGroundEquivalence:
    def test_soil_query_includes_ground_temperature_sources(self) -> None:
        # SOIL_TEMPERATURE query must also surface GTN-P (ground temperature).
        got = sources_for_variables([Variable.SOIL_TEMPERATURE])
        assert got[Variable.SOIL_TEMPERATURE] == [
            "gtnp_magt", "sloan_2014_barrow_soil", "tsp_north_america_ground_temperature"
        ]

    def test_ground_query_includes_soil_temperature_sources(self) -> None:
        got = sources_for_variables([Variable.GROUND_TEMPERATURE])
        assert got[Variable.GROUND_TEMPERATURE] == [
            "gtnp_magt", "sloan_2014_barrow_soil", "tsp_north_america_ground_temperature"
        ]


class TestServesSubsetOfEmitted:
    """A declared serves must be a subset of what the adapter actually emits.

    Covered here for the adapters whose parse runs on a single fixture file.
    `alaska_thaw_db` (parse expects the Zenodo zip package) and `ess_dive` (parse
    expects the multi-file BagIt-style package + pyproj) are covered by their
    own tests + the EXPECTED_SERVES regression lock above, not re-parsed here.
    """

    def _emitted(self, adapter, fixture: str) -> set[Variable]:
        obs = adapter.parse_to_schema(_fr(fixture))
        return {o.variable for o in obs}

    def test_calm(self) -> None:
        a = CALMAdapter(raw_dir=Path("/tmp/test_calm_cap"))
        assert a.serves <= self._emitted(a, "calm_sample.tsv")

    def test_gtnp(self) -> None:
        a = GTNPAdapter(raw_dir=Path("/tmp/test_gtnp_cap"))
        assert a.serves <= self._emitted(a, "gtnp_sample.tsv")

    def test_above(self) -> None:
        a = ABoVEAdapter(raw_dir=Path("/tmp/test_above_cap"))
        assert a.serves <= self._emitted(a, "above_stdm_sample.csv")
