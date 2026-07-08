"""Cross-source consistency check (e2sa/qc).

The per-dataset checks in `checks.py` look at one source in isolation. This one
looks ACROSS sources: for any variable served by more than one provider, it
co-locates observations from different sources within a great-circle radius and
compares their values. Disagreement between independent sources is informative,
not a data-integrity error (the data may both be real, e.g. a genuine
process/definition difference), so findings are `warning` severity and the strong
disagreements are surfaced as candidate "map-disagreement" study sites
(`projects/spade/CLAUDE.md` Section 4).

Generalizes the manual CALM-vs-ABoVE ALT comparison into a reusable check
(`memory/knowledge/findings/20260626-calm-above-alt-cross-source-consistency.md`):
that analysis co-located the 12 CALM sites with ABoVE cells, found a median
ABoVE/CALM ratio of 1.0, and flagged the 40-50% underestimates as candidates.
This check reproduces that method for any multi-provider variable. Never mutates
data.
"""
from __future__ import annotations

from collections import defaultdict
from statistics import median

import numpy as np

from e2sa.qc.checks import Finding
from e2sa.schema import CANONICAL_UNITS, Observation, Variable

EARTH_RADIUS_KM = 6371.0


def _is_interval_scale(var: Variable) -> bool:
    """True for interval-scale variables (temperatures) where agreement is a
    DIFFERENCE, not a ratio. A ratio is meaningless when values cross zero
    (a -8 degC vs -6 degC pair has no sensible ratio); their difference does.
    Detected via the canonical unit (degC) so it needs no hand-maintained list."""
    return CANONICAL_UNITS.get(var) == "degC"


def _haversine_km(
    lat0: float, lon0: float, lats: np.ndarray, lons: np.ndarray
) -> np.ndarray:
    """Great-circle distance (km) from one point to arrays of points."""
    rlat0, rlon0 = np.radians(lat0), np.radians(lon0)
    rlats, rlons = np.radians(lats), np.radians(lons)
    dlat = rlats - rlat0
    dlon = rlons - rlon0
    a = np.sin(dlat / 2) ** 2 + np.cos(rlat0) * np.cos(rlats) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def _by_source(
    obs: list[Observation],
) -> dict[str, list[Observation]]:
    out: dict[str, list[Observation]] = defaultdict(list)
    for o in obs:
        if o.latitude is None or o.longitude is None:
            continue
        out[o.provenance.source_id].append(o)
    return out


def _colocate(
    anchor: list[Observation],
    other: list[Observation],
    radius_km: float,
    *,
    interval: bool,
    depth_tol_m: float,
) -> tuple[list[float], list[dict], int]:
    """Co-locate each anchor obs with same-depth other-source obs within
    radius_km, and record an agreement metric per co-located anchor point.

    Depth-aware: a subsurface anchor only matches other obs within `depth_tol_m`
    of its depth (so a 2 m reading is never compared to a 50 m one); a
    surface/None-depth anchor matches only None-depth others. For interval-scale
    variables (temperature) the metric is the DIFFERENCE (other - anchor); for
    ratio-scale variables it is the (other/anchor) ratio, computed only for
    positive-valued pairs. Returns (metric_values, per-pair detail, n_spatial),
    where n_spatial counts anchor points that co-located AT ALL (independent of
    whether the metric was computable) so "no spatial overlap" is distinguished
    from "overlapped but ratio-inapplicable"."""
    olat = np.array([o.latitude for o in other], dtype=float)
    olon = np.array([o.longitude for o in other], dtype=float)
    oval = np.array([o.value for o in other], dtype=float)
    # Normalize depth: None and 0.0 both mean "surface" (a surface-referenced
    # quantity like ALT has no depth axis; CALM emits 0.0, ABoVE emits None, and
    # they must still co-locate). Only genuine subsurface depths (>0) that differ
    # exclude a pair.
    odep = np.array(
        [o.depth_m if o.depth_m is not None else 0.0 for o in other], dtype=float
    )
    dlat = radius_km / 111.0  # cheap bbox prefilter before the haversine
    values: list[float] = []
    pairs: list[dict] = []
    n_spatial = 0
    for a in anchor:
        if a.value is None:
            continue
        a_depth = a.depth_m if a.depth_m is not None else 0.0
        coslat = max(np.cos(np.radians(a.latitude)), 1e-6)
        dlon = radius_km / (111.0 * coslat)
        box = (
            (olat >= a.latitude - dlat) & (olat <= a.latitude + dlat)
            & (olon >= a.longitude - dlon) & (olon <= a.longitude + dlon)
        )
        if not box.any():
            continue
        d = _haversine_km(a.latitude, a.longitude, olat[box], olon[box])
        depth_ok = np.abs(odep[box] - a_depth) <= depth_tol_m
        near = oval[box][(d <= radius_km) & depth_ok]
        if near.size == 0:
            continue
        n_spatial += 1
        other_mean = float(np.mean(near))
        detail = {
            "lat": round(a.latitude, 4), "lon": round(a.longitude, 4),
            "depth_m": a.depth_m,
            "anchor": round(a.value, 4), "other": round(other_mean, 4),
            "n_near": int(near.size),
        }
        if interval:
            diff = other_mean - a.value
            values.append(diff)
            detail["diff"] = round(diff, 3)
            pairs.append(detail)
        elif a.value > 0 and other_mean > 0:
            ratio = other_mean / a.value
            values.append(ratio)
            detail["ratio"] = round(ratio, 3)
            pairs.append(detail)
    return values, pairs, n_spatial


def check_cross_source_consistency(
    observations: list[Observation],
    *,
    radius_km: float = 5.0,
    ratio_tol: float = 0.2,
    diff_tol: float = 2.0,
    depth_tol_m: float = 1.0,
    max_examples: int = 8,
) -> list[Finding]:
    """Cross-check every variable that has more than one source provider.

    For each multi-provider variable, the source with fewer observations anchors
    (the in-situ network in the CALM/ABoVE case); for each anchor point the
    other source's same-depth values within `radius_km` (great-circle) are
    averaged and an agreement metric recorded. The metric is variable-aware:
    a **ratio** (other/anchor) for positive ratio-scale quantities (ALT, ice,
    moisture), a **difference** (other - anchor) for interval-scale temperatures
    (a ratio is meaningless when values cross zero). One `warning` Finding per
    variable summarizes agreement and lists the strongest-disagreeing sites as
    candidate map-disagreement targets. "No spatial overlap" (`n_spatial == 0`)
    is reported distinctly from "overlapped but the metric was uncomputable", so
    a co-located temperature pair is never misreported as non-overlapping (the
    2026-07-06 GTN-P/TSP bug). Single-provider variables are skipped.

    PROPOSED DEFAULTS pending PI review: `ratio_tol` (0.2), `diff_tol` (2.0, in
    the variable's canonical unit, i.e. degC for temperature), `depth_tol_m`
    (1.0), `radius_km` (5.0). These thresholds are judgment calls; expose them so
    they can be tuned per study without editing the check.
    """
    by_var: dict[Variable, list[Observation]] = defaultdict(list)
    for o in observations:
        by_var[o.variable].append(o)

    findings: list[Finding] = []
    for var, obs in by_var.items():
        srcs = _by_source(obs)
        if len(srcs) < 2:
            continue  # single provider: nothing to cross-check

        interval = _is_interval_scale(var)
        all_values: list[float] = []
        all_pairs: list[dict] = []
        pair_labels: list[str] = []
        n_spatial_total = 0
        for i, (sa, oa) in enumerate(sorted(srcs.items())):
            for sb, ob in sorted(srcs.items())[i + 1:]:
                # Anchor on the smaller set (the in-situ network, usually).
                if len(oa) <= len(ob):
                    anchor, other, a_id, o_id = oa, ob, sa, sb
                else:
                    anchor, other, a_id, o_id = ob, oa, sb, sa
                values, pairs, n_spatial = _colocate(
                    anchor, other, radius_km,
                    interval=interval, depth_tol_m=depth_tol_m,
                )
                n_spatial_total += n_spatial
                if pairs:
                    for p in pairs:
                        p["anchor_source"], p["other_source"] = a_id, o_id
                    all_values.extend(values)
                    all_pairs.extend(pairs)
                    pair_labels.append(f"{a_id} vs {o_id}")

        if n_spatial_total == 0:
            depth_clause = f" and {depth_tol_m} m depth" if interval else ""
            findings.append(Finding(
                "cross_source_no_overlap", "warning",
                f"{var.value}: {len(srcs)} providers ({', '.join(sorted(srcs))}) "
                f"but none co-locate within {radius_km} km{depth_clause}; "
                f"cannot cross-check.",
                {"variable": var.value, "sources": sorted(srcs),
                 "radius_km": radius_km},
            ))
            continue

        if not all_values:
            # Spatially co-located but no comparable metric (a ratio-scale
            # variable whose co-located values were non-positive).
            findings.append(Finding(
                "cross_source_metric_uncomputable", "warning",
                f"{var.value}: {n_spatial_total} co-located pairs across "
                f"{', '.join(sorted(srcs))} but no comparable metric "
                f"(non-positive values on a ratio-scale variable).",
                {"variable": var.value, "n_colocated": n_spatial_total,
                 "sources": sorted(srcs)},
            ))
            continue

        med = median(all_values)
        if interval:
            disagreements = [p for p in all_pairs if abs(p["diff"]) > diff_tol]
            worst = sorted(disagreements, key=lambda p: abs(p["diff"]),
                           reverse=True)[:max_examples]
            findings.append(Finding(
                "cross_source_consistency", "warning",
                f"{var.value}: {len(all_values)} co-located pairs across "
                f"{', '.join(pair_labels)}; median difference {med:+.2f} "
                f"(other - anchor); {len(disagreements)} differ by >{diff_tol} "
                f"(candidate map-disagreement sites).",
                {"variable": var.value, "n_colocated": len(all_values),
                 "metric": "difference", "median_difference": round(med, 3),
                 "diff_tol": diff_tol, "radius_km": radius_km,
                 "depth_tol_m": depth_tol_m,
                 "n_disagreements": len(disagreements), "worst_sites": worst},
            ))
        else:
            disagreements = [p for p in all_pairs if abs(p["ratio"] - 1.0) > ratio_tol]
            worst = sorted(disagreements, key=lambda p: abs(p["ratio"] - 1.0),
                           reverse=True)[:max_examples]
            findings.append(Finding(
                "cross_source_consistency", "warning",
                f"{var.value}: {len(all_values)} co-located pairs across "
                f"{', '.join(pair_labels)}; median ratio {med:.2f}; "
                f"{len(disagreements)} disagree by >{int(ratio_tol * 100)}% "
                f"(candidate map-disagreement sites).",
                {"variable": var.value, "n_colocated": len(all_values),
                 "metric": "ratio", "median_ratio": round(med, 3),
                 "ratio_tol": ratio_tol, "radius_km": radius_km,
                 "n_disagreements": len(disagreements), "worst_sites": worst},
            ))
    return findings
