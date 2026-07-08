"""Data-quality + adapter-contract checks (the QC layer).

Distilled from the 2026-06-23 `above_stdm` failures (reflection `memory/dev_logs/
20260623s`): fabricated citations, an invented variable, and values/depths ingested
without checking ranges or missing-value sentinels. Each check turns one of those
lessons into a runnable guard. Checks return `Finding`s and never mutate data;
filtering/repair is the adapter's or a human's job, not these functions'.

The entry points are `validate_observations` (run on a real parse, not a fixture) and
`validate_staged_folder`. `summarize_distributions` is the "look at the numbers before
calling it done" habit, surfaced as data rather than pass/fail.
"""
from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from e2sa.schema import VALID_RANGE, Observation, Variable

#: Physical bounds per variable (inclusive), in each variable's CANONICAL_UNITS. These
#: now come straight from the schema's VALID_RANGE so units and QC thresholds share one
#: source of truth (an adapter emitting canonical units lands inside these bounds; a unit
#: mislabel like VWC=47 in a [0,1] fraction, or a -999 sentinel, falls outside and is
#: reported -- never dropped here). `DEFAULT_RANGES` is kept as a back-compat alias.
DEFAULT_RANGES: dict[Variable, tuple[float, float]] = VALID_RANGE

#: Variables measured below the surface; each Observation must carry a depth.
SUBSURFACE_VARIABLES: frozenset[Variable] = frozenset({
    Variable.SOIL_TEMPERATURE,
    Variable.GROUND_TEMPERATURE,
    Variable.VOLUMETRIC_WATER_CONTENT,
    Variable.VOLUMETRIC_ICE_CONTENT,
    Variable.EXCESS_ICE_CONTENT,
})

#: Missing-value sentinels seen in permafrost archives. A value equal to one of these
#: is almost certainly missing, not data.
COMMON_SENTINELS: tuple[float, ...] = (-9999.0, -999.0, -99.9)


@dataclass
class Finding:
    """One issue from a check. `error` blocks "validated"; `warning` is advisory."""

    check: str
    severity: str  # "error" | "warning"
    message: str
    detail: dict = field(default_factory=dict)


def check_serves_subset_emitted(
    serves: frozenset[Variable], emitted: set[Variable]
) -> list[Finding]:
    """serves must be a subset of what parse_to_schema actually emits (real data).

    Catches the invented-variable failure: `above_stdm` declared SOIL_TEMPERATURE in
    `serves` but emitted none. Run `emitted` from a REAL parse, not a fixture.
    """
    extra = set(serves) - set(emitted)
    if extra:
        names = sorted(v.value for v in extra)
        return [Finding(
            "serves_subset_emitted", "error",
            f"serves declares variables never emitted from real data: {names}",
            {"declared_not_emitted": names},
        )]
    return []


def check_value_ranges(
    observations: list[Observation],
    ranges: dict[Variable, tuple[float, float]] | None = None,
) -> list[Finding]:
    """Flag values outside their plausible range. One check, three failure modes:
    sentinel leaks (-999), unit mislabels (VWC 47 in a [0,1] "fraction"), and
    negatives in non-negative quantities. Reports counts + examples; drops nothing.
    """
    ranges = ranges if ranges is not None else DEFAULT_RANGES
    findings: list[Finding] = []
    by_var: dict[Variable, list[float]] = {}
    for o in observations:
        by_var.setdefault(o.variable, []).append(o.value)
    for var, vals in by_var.items():
        rng = ranges.get(var)
        if rng is None:
            continue
        lo, hi = rng
        bad = [v for v in vals if v < lo or v > hi]
        if bad:
            findings.append(Finding(
                "value_range", "error",
                f"{var.value}: {len(bad)}/{len(vals)} values outside [{lo}, {hi}] "
                f"(min={min(vals)}, max={max(vals)}) — sentinel/unit/sign bug?",
                {"variable": var.value, "n_bad": len(bad), "n_total": len(vals),
                 "min": min(vals), "max": max(vals), "range": [lo, hi],
                 "examples": sorted(set(bad))[:5]},
            ))
    return findings


def check_depth_for_subsurface(
    observations: list[Observation],
    subsurface: frozenset[Variable] = SUBSURFACE_VARIABLES,
) -> list[Finding]:
    """Subsurface measurements must carry a non-negative depth_m. Catches both the
    depth-from-wrong-column bug (all None) and a sentinel depth (negative).
    """
    findings: list[Finding] = []
    missing: dict[Variable, int] = {}
    negative: dict[Variable, int] = {}
    totals: dict[Variable, int] = {}
    for o in observations:
        if o.variable not in subsurface:
            continue
        totals[o.variable] = totals.get(o.variable, 0) + 1
        if o.depth_m is None:
            missing[o.variable] = missing.get(o.variable, 0) + 1
        elif o.depth_m < 0:
            negative[o.variable] = negative.get(o.variable, 0) + 1
    for var, n in missing.items():
        findings.append(Finding(
            "subsurface_depth_missing", "error",
            f"{var.value}: {n}/{totals[var]} subsurface readings have no depth_m",
            {"variable": var.value, "n_missing": n, "n_total": totals[var]},
        ))
    for var, n in negative.items():
        findings.append(Finding(
            "subsurface_depth_negative", "error",
            f"{var.value}: {n}/{totals[var]} readings have negative depth_m (sentinel?)",
            {"variable": var.value, "n_negative": n, "n_total": totals[var]},
        ))
    return findings


def check_citation_not_synthesized(prov: dict) -> list[Finding]:
    """A staged PROVENANCE citation must be real or null, never the synthesized
    "<title>. <source_url>" signature the old metadata bundle produced.
    """
    cit = prov.get("citation")
    if not cit:
        return []
    title = (prov.get("title") or "").strip()
    url = (prov.get("source_url") or prov.get("landing_page") or "").strip()
    synthesized = f"{title}. {url}".strip()
    if title and url and cit.strip() == synthesized:
        return [Finding(
            "citation_synthesized", "error",
            "citation looks synthesized ('<title>. <url>'); use the source's official "
            "citation (verbatim) or leave it null and point to the landing page",
            {"citation": cit},
        )]
    return []


def check_self_describing(folder: Path) -> list[Finding]:
    """A staged dataset folder must carry the self-describing bundle + native metadata,
    not just the data file (doc 18).
    """
    folder = Path(folder)
    findings: list[Finding] = []
    for required in ("PROVENANCE.json", "CITATION.cff", "README.md"):
        if not (folder / required).is_file():
            findings.append(Finding(
                "self_describing_missing", "error",
                f"staged folder missing {required}", {"folder": str(folder)},
            ))
    has_native = any(
        (folder / n).is_file() for n in ("metadata.json", "metadata.txt")
    ) or any(folder.glob("**/*.xml"))  # EML inside a BagIt package
    if not has_native:
        findings.append(Finding(
            "self_describing_no_native", "warning",
            "no native source metadata (metadata.json/txt or EML) captured",
            {"folder": str(folder)},
        ))
    return findings


def summarize_distributions(observations: list[Observation]) -> dict[str, dict]:
    """Per-variable count / min / median / max / depth coverage. Not pass/fail — the
    'look at the numbers' habit, so a parse is inspected, not just counted.
    """
    by_var: dict[Variable, list[Observation]] = {}
    for o in observations:
        by_var.setdefault(o.variable, []).append(o)
    out: dict[str, dict] = {}
    for var, obs in by_var.items():
        vals = [o.value for o in obs]
        depths = [o.depth_m for o in obs if o.depth_m is not None]
        out[var.value] = {
            "n": len(obs),
            "min": min(vals), "median": statistics.median(vals), "max": max(vals),
            "n_with_depth": len(depths),
            "depth_min": min(depths) if depths else None,
            "depth_max": max(depths) if depths else None,
        }
    return out


def validate_observations(
    serves: frozenset[Variable],
    observations: list[Observation],
    ranges: dict[Variable, tuple[float, float]] | None = None,
) -> list[Finding]:
    """Run the observation-level checks against a REAL parse. Returns all findings."""
    emitted = {o.variable for o in observations}
    findings = check_serves_subset_emitted(serves, emitted)
    findings += check_value_ranges(observations, ranges)
    findings += check_depth_for_subsurface(observations)
    return findings


def validate_staged_folder(folder: Path) -> list[Finding]:
    """Run the staged-folder checks (self-describing bundle + citation not synthesized)."""
    folder = Path(folder)
    findings = check_self_describing(folder)
    prov_path = folder / "PROVENANCE.json"
    if prov_path.is_file():
        try:
            prov = json.loads(prov_path.read_text())
        except json.JSONDecodeError:
            findings.append(Finding(
                "provenance_unreadable", "error",
                "PROVENANCE.json is not valid JSON", {"folder": str(folder)},
            ))
        else:
            findings += check_citation_not_synthesized(prov)
    return findings
