"""E2SA orchestrator: top-level pipeline driver and the minimal acquire() entry point.

`acquire()` is the minimal driver tying Phase A (catalog index) and Phase B
(adapter fetch) together. Both the interactive (offline) agent and the
autonomous (online) agent dispatch acquisition through this single function —
that's the "one substrate, two drivers" guarantee from docs/design/07.

`run()` is the full top-level orchestrator (S0 -> S10), a Phase 7 deliverable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from e2sa.catalog import (
    DEFAULT_CATALOG_PATH,
    ingest_observations,
    open_catalog,
    register_dataset,
    register_download,
)
from e2sa.config import RunConfig
from e2sa.data.indexing import index_package
from e2sa.data.registry import get_adapter


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


def acquire(
    source_id: str,
    dataset_id: str,
    catalog_path: Path | None = None,
    raw_dir: Path = Path("data/raw"),
    parse: bool = False,
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
        7. Return an AcquireResult summarizing fetch, index, and (optional) parse.

    Args:
        source_id: A key registered in ADAPTER_REGISTRY (e.g. 'ess_dive').
        dataset_id: A dataset key the adapter knows (e.g. 'sloan_2014_barrow_soil').
        catalog_path: DuckDB catalog file. Defaults to data/catalog.duckdb.
        raw_dir: Root directory for raw downloads. Adapters write to
            raw_dir/<source_id>/<dataset>/. Defaults to data/raw.
        parse: If True, also parse the downloaded data into Observation records
            and ingest them into the catalog's observations table. Defaults
            False (per docs/design/04: "parse is on-demand").
    """
    if catalog_path is None:
        catalog_path = DEFAULT_CATALOG_PATH

    adapter = get_adapter(source_id, raw_dir=raw_dir)
    info = next(
        (d for d in adapter.list_available() if d.dataset_id == dataset_id),
        None,
    )

    n_obs_ingested = 0
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
        n_vars_row = conn.execute(
            "SELECT COUNT(*) FROM dataset_variables WHERE dataset_id = ?",
            [dataset_id],
        ).fetchone()
        n_vars = n_vars_row[0] if n_vars_row else 0
        if parse:
            observations = adapter.parse_to_schema(fr)
            n_obs_ingested = ingest_observations(conn, observations, dataset_id)
    finally:
        conn.close()

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
    )


def run(config: RunConfig) -> None:
    """Top-level orchestrator (S0 -> S10). Stub; full P7 deliverable."""
    raise NotImplementedError("Orchestrator is a Phase 7 deliverable.")
