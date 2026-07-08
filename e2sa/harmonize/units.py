"""Unit harmonization: convert a source unit to the canonical unit per Variable.

docs/design/06 (Unit harmonization). The schema declares CANONICAL_UNITS[variable];
this module is the converter that makes "every Observation.unit == its canonical unit"
real instead of aspirational, plus the validator that asserts it at the harmonize
boundary.

v1 uses a small explicit conversion table, not `pint`: the unit vocabulary is tiny and
explicit (scale, offset) pairs are auditable. Revisit if the table outgrows a screen.

Input contract: `convert(value, from_unit, to_unit)` needs the (from, to) pair to be a
known conversion or an identity (after alias normalization); it raises ValueError
otherwise rather than guessing. Side effects: none.
"""
from __future__ import annotations

from e2sa.schema import CANONICAL_UNITS, Observation, Variable

#: Aliases folded to a single canonical spelling before any lookup. Keeps adapters that
#: emit human-friendly unit strings ("fraction", "%") interoperable with the CF-style
#: canonical vocabulary ("1").
_ALIASES: dict[str, str] = {
    "fraction": "1",
    "dimensionless": "1",
    "percent": "%",
    "deg_c": "degC",
    "degc": "degC",
    "celsius": "degC",
    "degree_celsius": "degC",
}

#: (from_unit, to_unit) -> (scale, offset): to_value = from_value * scale + offset.
#: Units are the alias-normalized spellings. Only pairs we actually need; extend as
#: new source units appear (and add a test alongside).
_LINEAR: dict[tuple[str, str], tuple[float, float]] = {
    ("cm", "m"): (0.01, 0.0),
    ("mm", "m"): (0.001, 0.0),
    ("m", "cm"): (100.0, 0.0),
    ("m", "mm"): (1000.0, 0.0),
    ("K", "degC"): (1.0, -273.15),
    ("degC", "K"): (1.0, 273.15),
    ("%", "1"): (0.01, 0.0),
    ("1", "%"): (100.0, 0.0),
}


def _normalize(unit: str) -> str:
    """Fold a unit string to its canonical spelling for lookup."""
    u = unit.strip()
    return _ALIASES.get(u.lower(), _ALIASES.get(u, u))


def convert(value: float, from_unit: str, to_unit: str) -> float:
    """Convert a scalar from `from_unit` to `to_unit`.

    Identity (after alias normalization) returns the value unchanged. A non-identity
    pair not in the table raises ValueError, so a missing conversion fails loudly
    rather than silently passing a wrong number through.
    """
    src = _normalize(from_unit)
    dst = _normalize(to_unit)
    if src == dst:
        return value
    factor = _LINEAR.get((src, dst))
    if factor is None:
        raise ValueError(
            f"no unit conversion from {from_unit!r} to {to_unit!r} "
            f"(normalized {src!r} -> {dst!r}); add it to e2sa.harmonize.units._LINEAR"
        )
    scale, offset = factor
    return value * scale + offset


def canonical_unit(variable: Variable) -> str | None:
    """The canonical unit for a variable, or None if it has none (categorical)."""
    return CANONICAL_UNITS.get(variable)


def to_canonical(obs: Observation) -> Observation:
    """Return a copy of `obs` with value + unit converted to the variable's canonical.

    A categorical variable (no canonical unit) is returned unchanged. Raises ValueError
    if the source unit cannot be converted to the canonical one.
    """
    target = CANONICAL_UNITS.get(obs.variable)
    if target is None:
        return obs
    if _normalize(obs.unit) == _normalize(target):
        # Already canonical numerically; normalize the label spelling (e.g. "fraction" -> "1").
        return obs if obs.unit == target else obs.model_copy(update={"unit": target})
    new_value = convert(obs.value, obs.unit, target)
    return obs.model_copy(update={"value": new_value, "unit": target})


def validate_canonical_units(observations: list[Observation]) -> list[str]:
    """Return a message per observation whose unit != its canonical unit.

    The harmonize-boundary assertion, as data rather than an exception: an empty list
    means every measured observation is in canonical units. Categorical variables (no
    canonical unit) are skipped. Use after parse/harmonize to confirm the contract.
    """
    problems: list[str] = []
    for o in observations:
        target = CANONICAL_UNITS.get(o.variable)
        if target is None:
            continue
        if o.unit != target:
            problems.append(
                f"{o.obs_id}: {o.variable.value} unit {o.unit!r} != canonical {target!r}"
            )
    return problems
