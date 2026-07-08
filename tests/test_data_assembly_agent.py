"""Tests for DataAssemblyAgent (the assemble() engine, SPADE P2).

discover() runs against the REAL registry capability index (no I/O). assemble()
mocks `acquire` (fetch/index/catalog + the parsed observations it returns, F-b)
so the harmonize + cross-source + tagging logic is tested without network or
DuckDB. `get_adapter` is mocked for discover()'s list_available only.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import e2sa.agents.data_assembly.agent as agent_mod
from e2sa.agents.data_assembly.agent import (
    DataAssemblyAgent,
    _in_bbox,
    _in_time_range,
    _parse_time_bound,
    _request_from_config,
)
from e2sa.agents.data_assembly.models import (
    AssemblyRequest,
    DatasetCandidate,
    TargetFormat,
)
from e2sa.config import RunConfig
from e2sa.data.base import DatasetInfo
from e2sa.orchestrator import AcquireResult
from e2sa.qc.checks import Finding
from e2sa.schema import Observation, ObservationType, Provenance, Variable

AK_BBOX = (-170.0, 54.0, -140.0, 72.0)


def _prov(source_id: str) -> Provenance:
    return Provenance(
        source_id=source_id,
        source_url="https://example.org",
        access_timestamp=datetime(2026, 7, 6),
        content_checksum="deadbeef",
        license="CC0",
        adapter_version="0.1.0",
    )


def _obs(source_id: str, dataset_id: str, var: Variable, value: float,
         lat: float, lon: float, unit: str = "cm", n: int = 1,
         time_start: datetime | None = None) -> list[Observation]:
    out = []
    for i in range(n):
        out.append(Observation(
            obs_id=f"{source_id}_{i}",
            obs_type=ObservationType.POINT,
            variable=var,
            value=value,
            unit=unit,
            latitude=lat,
            longitude=lon,
            time_start=time_start,
            provenance=_prov(source_id),
            extra={"dataset_id": dataset_id},
        ))
    return out


class _FakeAdapter:
    """Stand-in for a registered adapter: fixed serves + parse output."""

    def __init__(self, serves: frozenset[Variable], obs: list[Observation],
                 dataset_id: str = "ds") -> None:
        self.serves = serves
        self._obs = obs
        self._dataset_id = dataset_id

    def list_available(self) -> list[DatasetInfo]:
        return [DatasetInfo(
            dataset_id=self._dataset_id, name=self._dataset_id, description="",
            variables=[v.value for v in self.serves], spatial_coverage="AK",
            temporal_coverage="2020", format="csv", url=None, license="CC0",
        )]

    def fetch(self, dataset_id: str):  # noqa: ANN201 - value is ignored by parse
        return object()

    def parse_to_schema(self, fetch_result) -> list[Observation]:  # noqa: ANN001
        return list(self._obs)


def _agent(tmp_path: Path) -> DataAssemblyAgent:
    cfg = RunConfig(project=None, question="q", variables=["active_layer_thickness"],
                    bbox=AK_BBOX)
    agent = DataAssemblyAgent(cfg, catalog_path=tmp_path / "catalog.duckdb")
    agent.processed_dir = tmp_path / "processed"
    return agent


# --------------------------------------------------------------------- helpers
class TestHelpers:
    def test_in_bbox(self) -> None:
        assert _in_bbox(68.6, -149.6, AK_BBOX) is True
        assert _in_bbox(69.0, -133.0, AK_BBOX) is False  # NWT Canada, east of bbox

    def test_request_from_config_maps_variable_strings(self) -> None:
        cfg = RunConfig(question="q", variables=["ground_temperature", "not_a_var"],
                        bbox=AK_BBOX, time_range=("2016-01-01", "2023-12-31"))
        req = _request_from_config(cfg)
        assert req.variables == [Variable.GROUND_TEMPERATURE]  # unknown dropped
        assert req.bbox == AK_BBOX
        assert req.time_range == ("2016-01-01", "2023-12-31")

    def test_parse_time_bound_year_pads_to_period(self) -> None:
        # 'YYYY' lower bound = Jan 1; upper bound = Dec 31 end-of-day.
        assert _parse_time_bound("2016", upper=False) == datetime(2016, 1, 1)
        assert _parse_time_bound("2016", upper=True) == datetime(2016, 12, 31, 23, 59, 59)
        # 'YYYY-MM' upper bound pads to the last instant of that month.
        assert _parse_time_bound("2020-02", upper=True) == datetime(2020, 2, 29, 23, 59, 59)
        # full ISO passes through.
        assert _parse_time_bound("2018-06-15", upper=False) == datetime(2018, 6, 15)

    def test_in_time_range(self) -> None:
        lo, hi = datetime(2016, 1, 1), datetime(2020, 12, 31, 23, 59, 59)
        in_obs = _obs("s", "d", Variable.GROUND_TEMPERATURE, 1.0, 68.0, -149.0,
                      time_start=datetime(2018, 7, 1))[0]
        out_obs = _obs("s", "d", Variable.GROUND_TEMPERATURE, 1.0, 68.0, -149.0,
                       time_start=datetime(2025, 7, 1))[0]
        no_time = _obs("s", "d", Variable.GROUND_TEMPERATURE, 1.0, 68.0, -149.0)[0]
        assert _in_time_range(in_obs, lo, hi) is True
        assert _in_time_range(out_obs, lo, hi) is False
        assert _in_time_range(no_time, lo, hi) is None


# --------------------------------------------------------------------- discover
class TestDiscover:
    def test_discover_uses_real_capability_index(self, tmp_path: Path) -> None:
        agent = _agent(tmp_path)
        req = AssemblyRequest(question="ground temp", variables=[Variable.GROUND_TEMPERATURE])
        cands = agent.discover(req)
        sources = {c.source_id for c in cands}
        # gtnp + tsp both serve GROUND_TEMPERATURE; sloan via soil/ground equivalence.
        assert "gtnp_magt" in sources
        assert "tsp_north_america_ground_temperature" in sources

    def test_discover_expands_multi_dataset_source(self, tmp_path: Path) -> None:
        agent = _agent(tmp_path)
        req = AssemblyRequest(question="q", variables=[Variable.GROUND_TEMPERATURE])
        cands = agent.discover(req)
        tsp = [c for c in cands if c.source_id == "tsp_north_america_ground_temperature"]
        assert len(tsp) == 10  # the annual series 2016-2025
        assert {c.dataset_id for c in tsp} >= {"tsp_2016_ground_temperature",
                                               "tsp_2025_ground_temperature"}


# --------------------------------------------------------------------- screen
class TestScreen:
    def test_screen_accepts_all(self, tmp_path: Path) -> None:
        agent = _agent(tmp_path)
        cands = [DatasetCandidate(source_id="a", dataset_id="a", license="CC0"),
                 DatasetCandidate(source_id="b", dataset_id="b")]
        decisions = agent.screen(cands)
        assert all(d.accepted for d in decisions)
        assert "license not recorded" in decisions[1].reason  # b has no license


# --------------------------------------------------------------------- assemble
def _wire_mocks(monkeypatch, source_obs: dict[str, list[Observation]],
                failing: set[str] | None = None,
                findings: list[Finding] | None = None) -> None:
    failing = failing or set()

    def fake_acquire(source_id, dataset_id, **kw):  # noqa: ANN001, ANN202
        if dataset_id in failing:
            raise RuntimeError("simulated acquire failure")
        # F-b: assemble() consumes res.observations (no second fetch+parse), so
        # the parsed obs ride back on the result when return_observations=True.
        obs = source_obs.get(source_id, []) if kw.get("return_observations") else []
        return AcquireResult(
            source_id=source_id, dataset_id=dataset_id, dataset_dir=Path("."),
            n_files_downloaded=1, bytes_downloaded=1, n_indexed_files=1,
            n_indexed_variables=1, package_checksum="x",
            qc_findings=findings or [], observations=obs,
        )

    def fake_get_adapter(source_id, raw_dir=None):  # noqa: ANN001, ANN202
        obs = source_obs.get(source_id, [])
        serves = frozenset({o.variable for o in obs}) or frozenset(
            {Variable.ACTIVE_LAYER_THICKNESS}
        )
        return _FakeAdapter(serves, obs, dataset_id=source_id)

    monkeypatch.setattr(agent_mod, "acquire", fake_acquire)
    monkeypatch.setattr(agent_mod, "get_adapter", fake_get_adapter)


class TestAssemble:
    def test_pools_and_tags_bbox(self, tmp_path: Path, monkeypatch) -> None:
        # Two ALT providers, one point in-bbox (Alaska) and one out (NWT Canada).
        src = {
            "calm_alt": _obs("calm_alt", "calm_alt", Variable.ACTIVE_LAYER_THICKNESS,
                             50.0, 68.6, -149.6),
            "above_stdm": _obs("above_stdm", "above_stdm", Variable.ACTIVE_LAYER_THICKNESS,
                               51.0, 69.0, -133.0),  # NWT Canada, out of bbox
        }
        _wire_mocks(monkeypatch, src)
        agent = _agent(tmp_path)
        agent._request = AssemblyRequest(
            question="q", variables=[Variable.ACTIVE_LAYER_THICKNESS], bbox=AK_BBOX)
        accepted = [DatasetCandidate(source_id=s, dataset_id=s) for s in src]
        result = agent.assemble(accepted)

        assert result.n_observations == 2
        assert set(result.datasets_assembled) == {"calm_alt", "above_stdm"}
        tags = {o.extra["in_bbox"] for o in agent._assembled_obs}
        assert tags == {True, False}  # non-Alaska kept + tagged, not dropped

    def test_cross_source_check_runs(self, tmp_path: Path, monkeypatch) -> None:
        # Two ALT providers co-located (<5 km) with positive values -> one
        # multi-provider variable -> a cross-source warning is produced.
        src = {
            "calm_alt": _obs("calm_alt", "calm_alt", Variable.ACTIVE_LAYER_THICKNESS,
                             50.0, 68.60, -149.60),
            "above_stdm": _obs("above_stdm", "above_stdm", Variable.ACTIVE_LAYER_THICKNESS,
                               52.0, 68.61, -149.61),
        }
        _wire_mocks(monkeypatch, src)
        agent = _agent(tmp_path)
        agent._request = AssemblyRequest(
            question="q", variables=[Variable.ACTIVE_LAYER_THICKNESS], bbox=AK_BBOX)
        result = agent.assemble([DatasetCandidate(source_id=s, dataset_id=s) for s in src])
        assert result.qc_flags["cross_source_warnings"] >= 1

    def test_tags_time_range_when_present(self, tmp_path: Path, monkeypatch) -> None:
        # F-a: with a time_range, obs are tagged in_time_range (kept, not dropped).
        src = {
            "gtnp_magt": _obs("gtnp_magt", "gtnp_magt", Variable.GROUND_TEMPERATURE,
                              -5.0, 68.6, -149.6, unit="degC",
                              time_start=datetime(2018, 7, 1)),
            "tsp_north_america_ground_temperature": _obs(
                "tsp_north_america_ground_temperature", "tsp_2025_ground_temperature",
                Variable.GROUND_TEMPERATURE, -4.0, 68.6, -149.6, unit="degC",
                time_start=datetime(2025, 7, 1)),
        }
        _wire_mocks(monkeypatch, src)
        agent = _agent(tmp_path)
        agent._request = AssemblyRequest(
            question="q", variables=[Variable.GROUND_TEMPERATURE], bbox=AK_BBOX,
            time_range=("2016", "2020"))
        result = agent.assemble([DatasetCandidate(source_id=s, dataset_id=s) for s in src])
        assert result.n_observations == 2  # both kept
        tags = {o.extra["in_time_range"] for o in agent._assembled_obs}
        assert tags == {True, False}  # 2018 in range, 2025 out of range

    def test_no_time_range_leaves_obs_untagged(self, tmp_path: Path, monkeypatch) -> None:
        # F-a / D2: no time_range = fetch/keep everything, no in_time_range tag.
        src = {"gtnp_magt": _obs("gtnp_magt", "gtnp_magt", Variable.GROUND_TEMPERATURE,
                                 -5.0, 68.6, -149.6, unit="degC",
                                 time_start=datetime(2018, 7, 1))}
        _wire_mocks(monkeypatch, src)
        agent = _agent(tmp_path)
        agent._request = AssemblyRequest(
            question="q", variables=[Variable.GROUND_TEMPERATURE], bbox=AK_BBOX)
        agent.assemble([DatasetCandidate(source_id="gtnp_magt", dataset_id="gtnp_magt")])
        assert all("in_time_range" not in o.extra for o in agent._assembled_obs)

    def test_consumes_acquire_obs_without_reparse(self, tmp_path: Path, monkeypatch) -> None:
        # F-b: assemble reads res.observations; it must NOT re-fetch/re-parse the
        # adapter. Wire get_adapter to blow up if assemble touches it.
        src = {"calm_alt": _obs("calm_alt", "calm_alt",
                                Variable.ACTIVE_LAYER_THICKNESS, 50.0, 68.6, -149.6)}
        _wire_mocks(monkeypatch, src)

        def exploding_get_adapter(*a, **k):  # noqa: ANN002, ANN003, ANN202
            raise AssertionError("assemble() must not call get_adapter (no re-parse)")

        monkeypatch.setattr(agent_mod, "get_adapter", exploding_get_adapter)
        agent = _agent(tmp_path)
        agent._request = AssemblyRequest(
            question="q", variables=[Variable.ACTIVE_LAYER_THICKNESS], bbox=AK_BBOX)
        result = agent.assemble([DatasetCandidate(source_id="calm_alt", dataset_id="calm_alt")])
        assert result.n_observations == 1  # came from res.observations, no re-parse

    def test_acquire_findings_counted(self, tmp_path: Path, monkeypatch) -> None:
        findings = [Finding("value_range", "error", "out of range"),
                    Finding("gap", "warning", "a gap")]
        src = {"calm_alt": _obs("calm_alt", "calm_alt",
                                Variable.ACTIVE_LAYER_THICKNESS, 50.0, 68.6, -149.6)}
        _wire_mocks(monkeypatch, src, findings=findings)
        agent = _agent(tmp_path)
        result = agent.assemble([DatasetCandidate(source_id="calm_alt", dataset_id="calm_alt")])
        assert result.qc_flags["acquire_qc_errors"] == 1
        assert result.qc_flags["acquire_qc_warnings"] == 1

    def test_failing_dataset_does_not_sink_run(self, tmp_path: Path, monkeypatch) -> None:
        src = {"calm_alt": _obs("calm_alt", "calm_alt",
                                Variable.ACTIVE_LAYER_THICKNESS, 50.0, 68.6, -149.6)}
        _wire_mocks(monkeypatch, src, failing={"above_stdm"})
        agent = _agent(tmp_path)
        accepted = [DatasetCandidate(source_id="calm_alt", dataset_id="calm_alt"),
                    DatasetCandidate(source_id="above_stdm", dataset_id="above_stdm")]
        result = agent.assemble(accepted)
        assert result.datasets_assembled == ["calm_alt"]
        assert result.qc_flags["datasets_failed"] == 1
        assert "above_stdm" in result.notes


# --------------------------------------------------------------------- write
class TestWriteFormat:
    def _assembled(self, tmp_path: Path, monkeypatch):
        src = {"calm_alt": _obs("calm_alt", "calm_alt",
                                Variable.ACTIVE_LAYER_THICKNESS, 50.0, 68.6, -149.6, n=3)}
        _wire_mocks(monkeypatch, src)
        agent = _agent(tmp_path)
        result = agent.assemble([DatasetCandidate(source_id="calm_alt", dataset_id="calm_alt")])
        return agent, result

    def test_writes_parquet(self, tmp_path: Path, monkeypatch) -> None:
        import pandas as pd
        agent, result = self._assembled(tmp_path, monkeypatch)
        paths = agent.write_format(result, "parquet")
        assert len(paths) == 1 and paths[0].endswith(".parquet")
        df = pd.read_parquet(paths[0])
        assert len(df) == 3
        assert {"obs_id", "source_id", "variable", "value", "depth_m", "in_bbox"} <= set(df.columns)

    def test_writes_csv(self, tmp_path: Path, monkeypatch) -> None:
        agent, result = self._assembled(tmp_path, monkeypatch)
        paths = agent.write_format(result, "csv")
        assert paths and Path(paths[0]).exists()

    def test_none_writes_nothing(self, tmp_path: Path, monkeypatch) -> None:
        agent, result = self._assembled(tmp_path, monkeypatch)
        assert agent.write_format(result, "none") == []

    def test_unsupported_format_skips(self, tmp_path: Path, monkeypatch) -> None:
        agent, result = self._assembled(tmp_path, monkeypatch)
        assert agent.write_format(result, "geotiff") == []


# --------------------------------------------------------------------- run
class TestRun:
    def test_full_loop(self, tmp_path: Path, monkeypatch) -> None:
        src = {
            "calm_alt": _obs("calm_alt", "calm_alt",
                             Variable.ACTIVE_LAYER_THICKNESS, 50.0, 68.6, -149.6),
        }
        _wire_mocks(monkeypatch, src)
        # discover() hits the real registry, but calm_alt serves ALT so it is found;
        # get_adapter is mocked, so only the fake obs flow through.
        agent = _agent(tmp_path)
        req = AssemblyRequest(question="q", variables=[Variable.ACTIVE_LAYER_THICKNESS],
                              bbox=AK_BBOX, target_format=TargetFormat.PARQUET)
        result = agent.run(req)
        assert result.n_observations >= 1
        assert result.output_paths and result.output_paths[0].endswith(".parquet")
