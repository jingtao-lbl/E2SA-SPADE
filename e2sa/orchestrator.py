"""E2SA orchestrator: top-level pipeline driver and the minimal acquire() entry point.

`acquire()` is the minimal driver tying Phase A (catalog index) and Phase B
(adapter fetch) together. Both the interactive (offline) agent and the
autonomous (online) agent dispatch acquisition through this single function —
that's the "one substrate, two drivers" guarantee from docs/design/07.

`run()` is the full top-level orchestrator (S0 -> S10), a Phase 7 deliverable.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from e2sa.catalog import (
    DEFAULT_CATALOG_PATH,
    ingest_observations,
    open_catalog,
    register_dataset,
    register_download,
)
from e2sa.config import RunConfig, project_paths
from e2sa.data.indexing import index_package
from e2sa.data.metadata_bundle import write_metadata_bundle
from e2sa.data.registry import get_adapter
from e2sa.qc import Finding, validate_observations, validate_staged_folder
from e2sa.schema import Observation

logger = logging.getLogger(__name__)


@dataclass
class AcquireResult:
    """Summary of a single acquire() call.

    Returned to the caller (CLI, interactive agent, or autonomous loop) so
    the same downstream code can reason over what landed on disk and what's
    now queryable in the catalog.
    """

    source_id: str
    dataset_id: str
    dataset_dir: Path
    n_files_downloaded: int
    bytes_downloaded: int
    n_indexed_files: int
    n_indexed_variables: int
    package_checksum: str
    md5_mismatches: list[str] = field(default_factory=list)
    n_observations_ingested: int = 0  # 0 unless parse=True
    #: Data-quality + staged-folder QC findings (docs/design/19 V1). Advisory
    #: (warn, non-fatal) for now; the caller decides what to do with them.
    qc_findings: list[Finding] = field(default_factory=list)
    #: The parsed Observation objects (full provenance), populated ONLY when
    #: acquire(..., return_observations=True). Empty otherwise, so ingest-only
    #: callers (the CLI) do not retain the whole parse. The data_assembly agent
    #: consumes this to avoid a second fetch+parse (docs/design/21 F-b).
    observations: list[Observation] = field(default_factory=list)


def acquire(
    source_id: str,
    dataset_id: str,
    project: str | None = None,
    catalog_path: Path | None = None,
    raw_dir: Path | None = None,
    parse: bool = False,
    return_observations: bool = False,
) -> AcquireResult:
    """Fetch a dataset end-to-end, index it, optionally parse + ingest observations.

    Steps:
        1. Resolve source_id -> adapter via e2sa.data.registry.
        2. Register the dataset row in the catalog (idempotent upsert).
        3. Call adapter.fetch(dataset_id) (idempotent; checksum skip on disk).
        4. Record the download row in the catalog.
        5. Walk the package via index_package -> populate package_files
           and dataset_variables.
        6. If parse=True: call adapter.parse_to_schema(fr) and ingest the
           resulting Observation records into the observations table.
        7. Run QC: validate_staged_folder always, validate_observations when
           parse=True; attach findings to the result (advisory warn, non-fatal).
        8. Return an AcquireResult summarizing fetch, index, parse, and QC.

    Destination resolution (docs/design/17): an explicit `raw_dir`/`catalog_path`
    always wins; else `project` resolves both from `projects/<project>/data/`; else
    the framework defaults (`data/raw`, `data/catalog.duckdb`) for project-less use.
    The connector then appends `<data_center>/<dataset_id>/` under `raw_dir`.

    Args:
        source_id: A key registered in ADAPTER_REGISTRY (e.g. 'sloan_2014_barrow_soil').
        dataset_id: A dataset key the adapter knows (e.g. 'sloan_2014_barrow_soil').
        project: Project name; resolves raw_dir + catalog from projects/<project>/data/
            when those are not given explicitly. E.g. 'spade'.
        catalog_path: DuckDB catalog file. Overrides the project/framework default.
        raw_dir: Top-level raw dir. Overrides the project/framework default.
        parse: If True, also parse the downloaded data into Observation records
            and ingest them into the catalog's observations table. Defaults
            False (per docs/design/04: "parse is on-demand").
        return_observations: If True (and parse=True), include the parsed
            Observation objects on AcquireResult.observations so a caller (the
            data_assembly agent) can consume them without a second fetch+parse
            (docs/design/21 F-b). Defaults False so ingest-only callers do not
            retain the full parse in memory.
    """
    pp = project_paths(project) if project else None
    if raw_dir is None:
        raw_dir = pp.raw_dir if pp else Path("data/raw")
    if catalog_path is None:
        catalog_path = pp.catalog_path if pp else DEFAULT_CATALOG_PATH

    adapter = get_adapter(source_id, raw_dir=raw_dir)
    info = next(
        (d for d in adapter.list_available() if d.dataset_id == dataset_id),
        None,
    )

    n_obs_ingested = 0
    observations: list[Observation] = []
    qc_findings: list[Finding] = []
    conn = open_catalog(catalog_path)
    try:
        register_dataset(
            conn,
            dataset_id=dataset_id,
            source_id=source_id,
            name=info.name if info else dataset_id,
            description=info.description if info else "",
            source_url=(info.url or "") if info else "",
            license=(info.license or "") if info else "",
            adapter_version=adapter.adapter_version,
            schema_version="0.1.0",
        )
        fr = adapter.fetch(dataset_id)
        register_download(conn, fr)
        idx = index_package(conn, dataset_id, fr.local_path)
        # Make the staged folder self-describing: PROVENANCE.json + CITATION.cff
        # + README.md alongside the data (PI requirement; docs/design/18). Written
        # AFTER indexing so the generated sidecars are not catalogued as data; the
        # source's native metadata is captured by the connector during fetch.
        write_metadata_bundle(fr, source_id, info)
        # V1 (docs/design/19): QC the staged folder now that the bundle is written.
        qc_findings += validate_staged_folder(fr.local_path)
        n_vars_row = conn.execute(
            "SELECT COUNT(*) FROM dataset_variables WHERE dataset_id = ?",
            [dataset_id],
        ).fetchone()
        n_vars = n_vars_row[0] if n_vars_row else 0
        if parse:
            observations = adapter.parse_to_schema(fr)
            n_obs_ingested = ingest_observations(conn, observations, dataset_id)
            # V1 (docs/design/19): data-quality checks on the real parse (advisory).
            qc_findings += validate_observations(adapter.serves, observations)
    finally:
        conn.close()

    if qc_findings:
        n_err = sum(1 for f in qc_findings if f.severity == "error")
        n_warn = sum(1 for f in qc_findings if f.severity == "warning")
        # Per-finding detail, each at its own severity (error-severity = a
        # contract break like serves-not-emitted; warning = an outlier/range/
        # staging flag), so the actual failing check is visible without
        # inspecting AcquireResult.qc_findings. Non-blocking -- the data still
        # ingested above. The summary line below rolls these up for the driver.
        for f in qc_findings:
            log = logger.error if f.severity == "error" else logger.warning
            log(
                "QC %s [%s] for %s/%s: %s",
                f.severity,
                f.check,
                source_id,
                dataset_id,
                f.message,
            )
        logger.warning(
            "acquire(%s/%s): QC found %d error(s), %d warning(s); "
            "see AcquireResult.qc_findings (advisory, non-fatal)",
            source_id,
            dataset_id,
            n_err,
            n_warn,
        )

    # Older single-file adapters don't populate fr.files; the fetch still
    # produced one file, so report 1 rather than the literal len([]).
    n_downloaded = len(fr.files) if fr.files else 1
    return AcquireResult(
        source_id=source_id,
        dataset_id=dataset_id,
        dataset_dir=fr.local_path,
        n_files_downloaded=n_downloaded,
        bytes_downloaded=fr.bytes_downloaded,
        n_indexed_files=idx.n_files,
        n_indexed_variables=n_vars,
        package_checksum=fr.content_checksum,
        md5_mismatches=idx.md5_mismatches,
        n_observations_ingested=n_obs_ingested,
        qc_findings=qc_findings,
        observations=observations if return_observations else [],
    )


def run(config: RunConfig) -> None:
    """Top-level orchestrator (S0 -> S10). Stub; full P7 deliverable."""
    raise NotImplementedError("Orchestrator is a Phase 7 deliverable.")
