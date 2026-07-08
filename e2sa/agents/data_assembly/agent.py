"""DataAssemblyAgent: assemble analysis-ready data for a research question.

The framework's data-assembly agent (E2SA pipeline stage S2-S6), consolidating
what the architecture (CLAUDE.md Section 5) originally split across the
SourceDiscovery, Retrieval, Harmonizer, and QC agents into one coherent agent.
This is the capability SPADE has been building out in concrete form: given a
research question, discover relevant datasets, fetch and organize them, screen,
harmonize, QC, post-process, and write to a target format.

It is an ORCHESTRATOR over existing implementation modules, not new machinery:

- discovery   -> the source registry (`e2sa.data.registry`) capability index
- fetch+index -> `e2sa.orchestrator.acquire` (fetch + index + per-dataset QC)
- harmonize   -> `e2sa.harmonize` (canonical units; CRS/time helpers)
- QC          -> `e2sa.qc` (per-dataset checks in acquire; cross-source here)

SPADE supplies the domain-specific pieces (permafrost source cards + adapters);
the agent itself is framework-general.

Design + build order: `docs/design/13_data_assembly_agent.md` +
`docs/design/11_agent_pipeline.md` Section 4. The `assemble()` step wires the
built harmonize + qc layers over the acquisition core.

Region-scoping note (meeting 2026-07-06): `assemble()` does NOT geographically
drop observations. The model trains on the full faithful set (more terrain->thaw
examples generalize better); a bbox scopes only the prediction domain + eval.
So out-of-bbox rows are TAGGED (`extra["in_bbox"]`) and kept, never filtered here.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

from e2sa.catalog import DEFAULT_CATALOG_PATH
from e2sa.config import RunConfig, project_paths
from e2sa.data.registry import get_adapter, sources_for_variables
from e2sa.harmonize.units import to_canonical, validate_canonical_units
from e2sa.orchestrator import acquire
from e2sa.qc.checks import summarize_distributions
from e2sa.qc.cross_source import check_cross_source_consistency
from e2sa.schema import Observation, Variable

from .models import (
    AssemblyRequest,
    AssemblyResult,
    DatasetCandidate,
    ScreeningDecision,
    TargetFormat,
)

logger = logging.getLogger(__name__)


def _in_bbox(lat: float, lon: float, bbox: tuple[float, float, float, float]) -> bool:
    """True if (lat, lon) falls inside bbox = (west, south, east, north)."""
    west, south, east, north = bbox
    return west <= lon <= east and south <= lat <= north


def _request_from_config(config: RunConfig) -> AssemblyRequest:
    """Build an AssemblyRequest from a RunConfig (strings -> Variable enums)."""
    variables: list[Variable] = []
    for v in config.variables or []:
        try:
            variables.append(Variable(v))
        except ValueError:
            logger.warning("config variable %r is not a known Variable; skipping", v)
    return AssemblyRequest(
        question=config.question or "",
        variables=variables,
        bbox=config.bbox,
        time_range=config.time_range,
    )


def _to_canonical_safe(obs: Observation) -> Observation:
    """to_canonical, but a non-convertible unit is left as-is (flagged later by
    validate_canonical_units) rather than crashing the whole assembly."""
    try:
        return to_canonical(obs)
    except ValueError as exc:
        logger.warning("unit not convertible for %s: %s", obs.obs_id, exc)
        return obs


def _parse_time_bound(s: str, *, upper: bool) -> datetime:
    """Parse a time_range bound to a datetime.

    Accepts a full ISO date/datetime, or a partial 'YYYY' / 'YYYY-MM'. For a
    partial bound, `upper` pads to the end of the period (else the start), so a
    'YYYY' range covers the whole year.
    """
    s = s.strip()
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        pass
    parts = [int(p) for p in s.split("-")]
    year = parts[0]
    if len(parts) == 1:
        return datetime(year, 12, 31, 23, 59, 59) if upper else datetime(year, 1, 1)
    month = parts[1]
    if not upper:
        return datetime(year, month, 1)
    nxt = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
    return nxt - timedelta(seconds=1)


def _in_time_range(obs: Observation, lo: datetime, hi: datetime) -> bool | None:
    """Whether an observation's time falls in [lo, hi]; None if it carries no time."""
    t = obs.time_start or obs.time_end
    if t is None:
        return None
    return lo <= t <= hi


class DataAssemblyAgent:
    """Assemble analysis-ready data for a research question.

    Parameters
    ----------
    config:
        Run config (variables, bbox, time range, project). Reused from
        `e2sa.config.RunConfig`. When `config.project` is set, the agent resolves
        its raw + catalog + processed destinations from `projects/<project>/data/`
        (doc 17), so it knows where to place data without a hand-passed path.
    catalog_path:
        Optional explicit catalog override; otherwise resolved from the project
        (or the framework default for a project-less config).
    """

    def __init__(
        self,
        config: RunConfig,
        catalog_path: Path | str | None = None,
    ) -> None:
        self.config = config
        pp = project_paths(config.project) if config.project else None
        if catalog_path is not None:
            self.catalog_path = Path(catalog_path)
        else:
            self.catalog_path = pp.catalog_path if pp else Path(DEFAULT_CATALOG_PATH)
        #: Top-level raw dir the agent fetches into (connector appends
        #: <data_center>/<dataset_id>/). Resolved from the project.
        self.raw_dir = pp.raw_dir if pp else Path("data/raw")
        #: Where write_format() lands the analysis-ready table.
        self.processed_dir = pp.processed_dir if pp else Path("data/processed")
        #: The request driving the current run (set by run()/discover()).
        self._request: AssemblyRequest | None = None
        #: Harmonized observations stashed by assemble() for write_format().
        self._assembled_obs: list[Observation] = []

    # ------------------------------------------------------------------ S2
    def discover(self, request: AssemblyRequest) -> list[DatasetCandidate]:
        """Surface candidate datasets for the request via the capability index.

        Maps each requested Variable to the source_ids that serve it
        (`sources_for_variables`, which reads each adapter's declared `serves`),
        then expands each source to one candidate per dataset it offers
        (`adapter.list_available()`), so a multi-dataset source like the TSP
        annual series surfaces all its years.
        """
        self._request = request
        var_to_sources = sources_for_variables(request.variables)
        source_ids = sorted({sid for sids in var_to_sources.values() for sid in sids})

        candidates: list[DatasetCandidate] = []
        for sid in source_ids:
            try:
                adapter = get_adapter(sid, raw_dir=self.raw_dir)
            except KeyError:
                logger.warning("no adapter registered for source_id %r; skipping", sid)
                continue
            serves = sorted(adapter.serves, key=lambda v: v.value)
            for info in adapter.list_available():
                candidates.append(
                    DatasetCandidate(
                        source_id=sid,
                        dataset_id=info.dataset_id,
                        variables=serves,
                        coverage=f"{info.spatial_coverage} | {info.temporal_coverage}",
                        license=info.license,
                        landing_page=info.url,
                    )
                )
        logger.info(
            "discover: %d candidate datasets across %d sources for %d variables",
            len(candidates), len(source_ids), len(request.variables),
        )
        return candidates

    # ------------------------------------------------------------------ screen
    def screen(self, candidates: list[DatasetCandidate]) -> list[ScreeningDecision]:
        """Accept/reject candidates (human checkpoint (a), CLAUDE.md Section 5).

        Non-interactive default: accept every discovered candidate. The
        interactive human checkpoint is a config toggle (future); a candidate
        with no license recorded is still accepted but noted.
        """
        decisions: list[ScreeningDecision] = []
        for c in candidates:
            reason = "auto-accepted (non-interactive screen)"
            if not c.license:
                reason += "; license not recorded in DatasetInfo"
            decisions.append(ScreeningDecision(candidate=c, accepted=True, reason=reason))
        return decisions

    # ------------------------------------------------------------------ S3-S5
    def assemble(self, accepted: list[DatasetCandidate]) -> AssemblyResult:
        """Fetch + index + harmonize + QC each accepted dataset into one pool.

        Per dataset: `acquire(..., parse=True, return_observations=True)` (fetch +
        index + ingest + per-dataset QC), consuming the parsed Observations it
        returns instead of a second fetch+parse (F-b; they carry full provenance).
        Harmonize units to canonical, then tag bbox and time-range membership
        (kept, not filtered - see module docstring; F-a). Then cross-source
        consistency across the pooled set. Every record keeps its provenance.
        """
        request = self._request or _request_from_config(self.config)
        requested = set(request.variables)
        bbox = request.bbox
        # F-a (doc 21 D2): a time_range tags observations only when present;
        # absent = keep everything the source has (no filter). Tagged, not
        # dropped, matching the bbox rule (D1); scoping happens downstream.
        time_bounds: tuple[datetime, datetime] | None = None
        if request.time_range is not None:
            time_bounds = (
                _parse_time_bound(request.time_range[0], upper=False),
                _parse_time_bound(request.time_range[1], upper=True),
            )

        all_obs: list[Observation] = []
        assembled: list[str] = []
        failed: list[str] = []
        acq_errors = acq_warnings = 0

        for cand in accepted:
            sid = cand.source_id
            did = cand.dataset_id or sid
            try:
                res = acquire(
                    sid,
                    did,
                    project=self.config.project,
                    catalog_path=self.catalog_path,
                    raw_dir=self.raw_dir,
                    parse=True,
                    return_observations=True,
                )
            except Exception as exc:  # noqa: BLE001 - one dataset failing must not sink the run
                logger.warning("acquire failed for %s/%s: %s", sid, did, exc)
                failed.append(f"{did}: {type(exc).__name__}: {exc}")
                continue

            for f in res.qc_findings:
                if f.severity == "error":
                    acq_errors += 1
                    logger.error("QC[%s] %s: %s", did, f.check, f.detail)
                else:
                    acq_warnings += 1
                    logger.warning("QC[%s] %s: %s", did, f.check, f.detail)

            # F-b (doc 21 D6): consume the Observations acquire already parsed
            # (full provenance), instead of a second fetch+parse.
            obs = [_to_canonical_safe(o) for o in res.observations]
            if requested:
                obs = [o for o in obs if o.variable in requested]
            if bbox is not None:
                for o in obs:
                    o.extra["in_bbox"] = _in_bbox(o.latitude, o.longitude, bbox)
            if time_bounds is not None:
                lo, hi = time_bounds
                for o in obs:
                    o.extra["in_time_range"] = _in_time_range(o, lo, hi)

            all_obs.extend(obs)
            assembled.append(did)
            logger.info("assembled %s: %d observations", did, len(obs))

        cross = check_cross_source_consistency(all_obs) if all_obs else []
        for f in cross:
            logger.info("cross-source[%s]: %s", f.check, f.detail)
        unit_problems = validate_canonical_units(all_obs)
        distributions = summarize_distributions(all_obs)

        self._assembled_obs = all_obs

        qc_flags = {
            "cross_source_warnings": len(cross),
            "unit_contract_problems": len(unit_problems),
            "acquire_qc_errors": acq_errors,
            "acquire_qc_warnings": acq_warnings,
            "datasets_failed": len(failed),
        }
        return AssemblyResult(
            request=request,
            datasets_assembled=assembled,
            catalog_path=str(self.catalog_path),
            n_observations=len(all_obs),
            qc_flags=qc_flags,
            notes=_build_notes(distributions, cross, unit_problems, failed),
        )

    # ------------------------------------------------------------------ S6
    def post_process(self, result: AssemblyResult) -> AssemblyResult:
        """Request-specific transforms past harmonization. v1: passthrough.

        Temporal aggregation (`harmonize.temporal.aggregate_to_annual`) and other
        derived-field steps hook in here when a request asks for them; for now the
        harmonized per-observation table is the analysis-ready product.
        """
        return result

    # ------------------------------------------------------------------ write
    def write_format(self, result: AssemblyResult, target_format: str) -> list[str]:
        """Write the harmonized observations to CSV/Parquet; return output paths.

        `none` leaves the data in the catalog only (no file). NetCDF/GeoTIFF are
        not supported for a point-observation table (they are gridded-product
        formats) and return no path with a warning.
        """
        fmt = target_format.lower()
        if fmt in (TargetFormat.NONE.value, ""):
            return []
        if not self._assembled_obs:
            logger.warning("write_format: no assembled observations to write")
            return []
        if fmt not in (TargetFormat.CSV.value, TargetFormat.PARQUET.value):
            logger.warning("write_format: %r unsupported for a point table; skipping", fmt)
            return []

        import pandas as pd

        rows = [
            {
                "obs_id": o.obs_id,
                "source_id": o.provenance.source_id,
                "dataset_id": o.extra.get("dataset_id"),
                "variable": o.variable.value,
                "value": o.value,
                "unit": o.unit,
                "latitude": o.latitude,
                "longitude": o.longitude,
                "depth_m": o.depth_m,
                "time_start": o.time_start,
                "time_end": o.time_end,
                "in_bbox": o.extra.get("in_bbox"),
            }
            for o in self._assembled_obs
        ]
        df = pd.DataFrame(rows)
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        out = self.processed_dir / f"assembled_observations.{fmt}"
        if fmt == TargetFormat.PARQUET.value:
            df.to_parquet(out, index=False)
        else:
            df.to_csv(out, index=False)
        logger.info("wrote %d observations -> %s", len(df), out)
        return [str(out)]

    # ------------------------------------------------------------------ run
    def run(self, request: AssemblyRequest) -> AssemblyResult:
        """Full loop: discover -> screen -> assemble -> post_process -> write_format."""
        self._request = request
        candidates = self.discover(request)
        decisions = self.screen(candidates)
        accepted = [d.candidate for d in decisions if d.accepted]
        result = self.assemble(accepted)
        result = self.post_process(result)
        result.output_paths = self.write_format(result, request.target_format.value)
        return result


def _build_notes(
    distributions: dict[str, dict],
    cross: list,
    unit_problems: list[str],
    failed: list[str],
) -> str:
    """Human-readable summary: per-variable distributions + QC headlines."""
    lines: list[str] = ["Per-variable distributions:"]
    for var, d in sorted(distributions.items()):
        depth = (
            f", depth {d['depth_min']}-{d['depth_max']} m ({d['n_with_depth']} w/ depth)"
            if d["n_with_depth"]
            else ""
        )
        lines.append(
            f"  {var}: n={d['n']} min={d['min']:.3g} median={d['median']:.3g} "
            f"max={d['max']:.3g}{depth}"
        )
    if cross:
        lines.append("Cross-source consistency:")
        for f in cross:
            lines.append(f"  [{f.severity}] {f.check}: {f.message}")
    if unit_problems:
        lines.append(f"Unit-contract problems: {len(unit_problems)} (see logs)")
    if failed:
        lines.append("Datasets that failed to assemble:")
        lines.extend(f"  - {m}" for m in failed)
    return "\n".join(lines)
