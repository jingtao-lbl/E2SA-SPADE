"""Temporal alignment to a canonical grain (docs/design/06 §5).

- `aggregate_to_annual`: collapse sub-annual records (monthly LST, etc.) to one
  value per (group, year) by mean / max / end-of-season, depending on variable.
- `broadcast_static`: repeat a single-snapshot layer across a set of years.
- Event-based data (Alaska Thaw DB) has no time axis; treat as time-independent
  labels — `is_time_independent` flags that so callers skip alignment.

Works on lists of `Observation` (the unified schema) or on pandas frames. Annual
grain is SPADE's P3 default; the grain is a parameter, not hardcoded.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from statistics import mean
from typing import Any

from e2sa.schema import Observation, ObservationType

_REDUCERS: dict[str, Callable[[list[float]], float]] = {
    "mean": lambda xs: mean(xs),
    "max": max,
    "min": min,
    "sum": sum,
    "last": lambda xs: xs[-1],   # end-of-season when records are time-ordered
}


def is_time_independent(obs: Observation) -> bool:
    """True for event/label observations that carry no meaningful time axis."""
    return obs.obs_type == ObservationType.EVENT or obs.time_start is None


def aggregate_to_annual(
    observations: Iterable[Observation],
    *,
    method: str = "mean",
    group_key: Callable[[Observation], Any] | None = None,
) -> dict[tuple[Any, int], float]:
    """Aggregate sub-annual observations to one value per (group, year).

    `group_key` defaults to (variable, rounded lat/lon, depth) so a site's monthly
    series collapses per year. Time-independent observations are skipped (use them
    as-is). `method` in {mean, max, min, sum, last}; "last" is end-of-season when the
    input is time-ordered.
    """
    if group_key is None:
        def group_key(o: Observation):  # noqa: ANN202
            return (o.variable.value, round(o.latitude, 3), round(o.longitude, 3),
                    None if o.depth_m is None else round(o.depth_m, 2))

    buckets: dict[tuple[Any, int], list[float]] = defaultdict(list)
    for o in observations:
        if is_time_independent(o):
            continue
        buckets[(group_key(o), o.time_start.year)].append(o.value)

    reducer = _REDUCERS[method]
    return {k: reducer(v) for k, v in buckets.items()}


def broadcast_static(value: Any, years: Iterable[int]) -> dict[int, Any]:
    """Repeat a single-snapshot value (e.g. a thermokarst map, a DEM) across `years`."""
    return {y: value for y in years}
