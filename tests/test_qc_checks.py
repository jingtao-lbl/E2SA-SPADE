"""Tests for the QC checks (e2sa/qc/checks.py).

Each test reproduces one of the 2026-06-23 above_stdm mistakes (reflection
20260623s) and asserts the matching check would have caught it.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from e2sa.qc import (
    check_citation_not_synthesized,
    check_depth_for_subsurface,
    check_self_describing,
    check_serves_subset_emitted,
    check_value_ranges,
    summarize_distributions,
    validate_observations,
    validate_staged_folder,
)
from e2sa.schema import Observation, ObservationType, Provenance, Variable


def _obs(variable: Variable, value: float, depth_m: float | None = None) -> Observation:
    return Observation(
        obs_id=f"{variable.value}-{value}-{depth_m}",
        obs_type=ObservationType.POINT,
        variable=variable,
        value=value,
        unit="x",
        latitude=70.0,
        longitude=-150.0,
        depth_m=depth_m,
        provenance=Provenance(
            source_id="t", access_timestamp=datetime(2026, 6, 23, tzinfo=UTC),
            content_checksum="x", adapter_version="0.1.0",
        ),
    )


def test_serves_subset_catches_invented_variable() -> None:
    # above_stdm declared SOIL_TEMPERATURE but emitted only ALT.
    serves = frozenset({Variable.ACTIVE_LAYER_THICKNESS, Variable.SOIL_TEMPERATURE})
    emitted = {Variable.ACTIVE_LAYER_THICKNESS}
    findings = check_serves_subset_emitted(serves, emitted)
    assert [f.check for f in findings] == ["serves_subset_emitted"]
    assert "soil_temperature" in findings[0].detail["declared_not_emitted"]


def test_serves_subset_clean_when_matched() -> None:
    serves = frozenset({Variable.ACTIVE_LAYER_THICKNESS})
    assert check_serves_subset_emitted(serves, {Variable.ACTIVE_LAYER_THICKNESS}) == []


def test_value_range_catches_sentinel_and_unit_mislabel() -> None:
    # VWC as percent (47) + the -999 sentinel, in a [0,1] "fraction" range.
    obs = [
        _obs(Variable.VOLUMETRIC_WATER_CONTENT, 0.45),
        _obs(Variable.VOLUMETRIC_WATER_CONTENT, 47.0),    # percent mislabel
        _obs(Variable.VOLUMETRIC_WATER_CONTENT, -999.0),  # sentinel
    ]
    findings = check_value_ranges(obs)
    assert len(findings) == 1
    d = findings[0].detail
    assert d["variable"] == "volumetric_water_content"
    assert d["n_bad"] == 2 and d["max"] == 47.0 and d["min"] == -999.0


def test_value_range_clean_for_in_range() -> None:
    obs = [_obs(Variable.VOLUMETRIC_WATER_CONTENT, 0.3), _obs(Variable.EXCESS_ICE_CONTENT, 0.8)]
    assert check_value_ranges(obs) == []


def test_depth_check_catches_missing_and_negative() -> None:
    obs = [
        _obs(Variable.VOLUMETRIC_WATER_CONTENT, 0.3, depth_m=None),   # depth lost
        _obs(Variable.SOIL_TEMPERATURE, -2.0, depth_m=-9.99),          # sentinel depth
        _obs(Variable.SOIL_TEMPERATURE, -1.0, depth_m=0.1),           # fine
    ]
    checks = {f.check for f in check_depth_for_subsurface(obs)}
    assert checks == {"subsurface_depth_missing", "subsurface_depth_negative"}


def test_depth_check_ignores_surface_variables() -> None:
    # ALT is a thickness, not a subsurface point; no depth required.
    assert check_depth_for_subsurface([_obs(Variable.ACTIVE_LAYER_THICKNESS, 40.0)]) == []


def test_citation_synthesized_is_flagged() -> None:
    prov = {"citation": "CALM ALT (PANGAEA). https://doi.org/10.x",
            "title": "CALM ALT (PANGAEA)", "source_url": "https://doi.org/10.x"}
    assert [f.check for f in check_citation_not_synthesized(prov)] == ["citation_synthesized"]


def test_real_citation_and_null_pass() -> None:
    real = {"citation": "Schaefer, K. et al. (2021). ABoVE ... ORNL DAAC. https://doi.org/10.x",
            "title": "ABoVE", "source_url": "https://doi.org/10.x"}
    assert check_citation_not_synthesized(real) == []
    assert check_citation_not_synthesized({"citation": None, "title": "X", "source_url": "u"}) == []


def test_self_describing_flags_missing_sidecar(tmp_path: Path) -> None:
    (tmp_path / "data.csv").write_text("a,b\n1,2\n")
    (tmp_path / "PROVENANCE.json").write_text("{}")
    (tmp_path / "metadata.json").write_text("{}")
    # CITATION.cff + README.md missing
    checks = [f.check for f in check_self_describing(tmp_path)]
    assert checks.count("self_describing_missing") == 2


def test_summarize_distributions_reports_numbers() -> None:
    obs = [
        _obs(Variable.VOLUMETRIC_WATER_CONTENT, 0.1, depth_m=0.1),
        _obs(Variable.VOLUMETRIC_WATER_CONTENT, 0.5, depth_m=0.3),
    ]
    s = summarize_distributions(obs)["volumetric_water_content"]
    assert s["n"] == 2 and s["min"] == 0.1 and s["max"] == 0.5 and s["n_with_depth"] == 2


def test_runner_catches_the_above_stdm_style_failure() -> None:
    # serves over-declares; values carry the -999 sentinel; subsurface depth lost.
    serves = frozenset({Variable.ACTIVE_LAYER_THICKNESS, Variable.VOLUMETRIC_WATER_CONTENT,
                        Variable.SOIL_TEMPERATURE})
    obs = [
        _obs(Variable.ACTIVE_LAYER_THICKNESS, 40.0),
        _obs(Variable.VOLUMETRIC_WATER_CONTENT, -999.0, depth_m=None),
    ]
    checks = {f.check for f in validate_observations(serves, obs)}
    assert "serves_subset_emitted" in checks   # SOIL_TEMPERATURE never emitted
    assert "value_range" in checks             # -999 out of range
    assert "subsurface_depth_missing" in checks


def test_validate_staged_folder_flags_synthesized_citation(tmp_path: Path) -> None:
    import json
    (tmp_path / "PROVENANCE.json").write_text(json.dumps(
        {"citation": "T. u", "title": "T", "source_url": "u"}))
    (tmp_path / "CITATION.cff").write_text("cff-version: 1.2.0\n")
    (tmp_path / "README.md").write_text("# T\n")
    (tmp_path / "metadata.json").write_text("{}")
    checks = {f.check for f in validate_staged_folder(tmp_path)}
    assert "citation_synthesized" in checks
