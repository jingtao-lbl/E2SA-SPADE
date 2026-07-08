"""Tests for unit harmonization (e2sa/harmonize/units.py) and the schema's
CANONICAL_UNITS / VALID_RANGE contract.

Covers: scalar conversion correctness (incl. identity + alias folding), the loud
failure on an unknown conversion, to_canonical's per-variable behavior (convert,
label-only normalize, categorical pass-through), the canonical-unit validator, and
that every measured Variable declares both a canonical unit and a valid range.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from e2sa.harmonize.units import (
    canonical_unit,
    convert,
    to_canonical,
    validate_canonical_units,
)
from e2sa.schema import (
    CANONICAL_UNITS,
    VALID_RANGE,
    Observation,
    ObservationType,
    Provenance,
    Variable,
)

#: The one measured-but-categorical variable, excluded from the unit contract on purpose.
CATEGORICAL = {Variable.THAW_EVENT_LABEL}


def _obs(variable: Variable, value: float, unit: str) -> Observation:
    return Observation(
        obs_id=f"{variable.value}-{value}-{unit}",
        obs_type=ObservationType.POINT,
        variable=variable,
        value=value,
        unit=unit,
        latitude=70.0,
        longitude=-150.0,
        provenance=Provenance(
            source_id="t", access_timestamp=datetime(2026, 6, 25, tzinfo=UTC),
            content_checksum="x", adapter_version="0.1.0",
        ),
    )


# --- convert ---


def test_convert_length() -> None:
    assert convert(160.0, "cm", "m") == pytest.approx(1.6)
    assert convert(2500.0, "mm", "m") == pytest.approx(2.5)
    assert convert(1.6, "m", "cm") == pytest.approx(160.0)


def test_convert_temperature_offset() -> None:
    assert convert(273.15, "K", "degC") == pytest.approx(0.0)
    assert convert(0.0, "degC", "K") == pytest.approx(273.15)


def test_convert_percent_to_fraction() -> None:
    assert convert(47.0, "percent", "1") == pytest.approx(0.47)
    assert convert(47.0, "%", "1") == pytest.approx(0.47)


def test_convert_identity_and_aliases() -> None:
    assert convert(5.0, "degC", "degC") == 5.0
    # "fraction" and "1" are the same unit; identity, no scaling.
    assert convert(0.45, "fraction", "1") == 0.45
    assert convert(0.45, "1", "fraction") == 0.45
    # case-insensitive alias folding.
    assert convert(0.0, "celsius", "degC") == 0.0


def test_convert_unknown_pair_raises() -> None:
    with pytest.raises(ValueError, match="no unit conversion"):
        convert(1.0, "m", "degC")


# --- to_canonical ---


def test_to_canonical_converts_value_and_unit() -> None:
    alt = to_canonical(_obs(Variable.ACTIVE_LAYER_THICKNESS, 45.0, "cm"))
    assert alt.unit == "m" and alt.value == pytest.approx(0.45)

    vwc = to_canonical(_obs(Variable.VOLUMETRIC_WATER_CONTENT, 47.0, "percent"))
    assert vwc.unit == "1" and vwc.value == pytest.approx(0.47)


def test_to_canonical_normalizes_label_only_when_numerically_equal() -> None:
    # EIC already a fraction in [0,1]; only the label "fraction" -> "1" should change.
    eic = to_canonical(_obs(Variable.EXCESS_ICE_CONTENT, 0.86, "fraction"))
    assert eic.unit == "1" and eic.value == 0.86


def test_to_canonical_passes_through_categorical() -> None:
    label = _obs(Variable.THAW_EVENT_LABEL, 3.0, "category_index")
    out = to_canonical(label)
    assert out.unit == "category_index" and out.value == 3.0


# --- validator ---


def test_validate_canonical_units_flags_mismatch() -> None:
    obs = [
        _obs(Variable.ACTIVE_LAYER_THICKNESS, 0.45, "m"),    # canonical, ok
        _obs(Variable.ACTIVE_LAYER_THICKNESS, 45.0, "cm"),   # not canonical
        _obs(Variable.THAW_EVENT_LABEL, 3.0, "category_index"),  # categorical, skipped
    ]
    problems = validate_canonical_units(obs)
    assert len(problems) == 1
    assert "cm" in problems[0] and "active_layer_thickness" in problems[0]


def test_validate_canonical_units_clean() -> None:
    obs = [to_canonical(_obs(v, 0.5, u)) for v, u in [
        (Variable.SOIL_TEMPERATURE, "degC"),
        (Variable.EXCESS_ICE_CONTENT, "fraction"),
        (Variable.ELEVATION, "m"),
    ]]
    assert validate_canonical_units(obs) == []


# --- schema contract ---


def test_every_measured_variable_has_canonical_unit_and_range() -> None:
    for v in Variable:
        if v in CATEGORICAL:
            assert v not in CANONICAL_UNITS, f"{v} is categorical, must not have a canonical unit"
            continue
        assert v in CANONICAL_UNITS, f"{v} missing a canonical unit"
        assert v in VALID_RANGE, f"{v} missing a valid range"


def test_valid_ranges_are_ordered() -> None:
    for v, (lo, hi) in VALID_RANGE.items():
        assert lo < hi, f"{v} range not ordered: ({lo}, {hi})"


def test_canonical_unit_helper() -> None:
    assert canonical_unit(Variable.EXCESS_ICE_CONTENT) == "1"
    assert canonical_unit(Variable.SOIL_TEMPERATURE) == "degC"
    assert canonical_unit(Variable.THAW_EVENT_LABEL) is None
