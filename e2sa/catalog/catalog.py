"""DuckDB-backed catalog for datasets, downloads, and observations."""
from __future__ import annotations

from pathlib import Path

import duckdb

DEFAULT_CATALOG_PATH = Path("data/catalog.duckdb")

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS datasets (
    dataset_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    name TEXT,
    description TEXT,
    source_url TEXT,
    license TEXT,
    registered_at TIMESTAMP,
    adapter_version TEXT,
    schema_version TEXT
);

CREATE TABLE IF NOT EXISTS downloads (
    download_id TEXT PRIMARY KEY,
    dataset_id TEXT,
    source_url TEXT,
    access_timestamp TIMESTAMP NOT NULL,
    content_checksum TEXT NOT NULL,
    local_path TEXT,
    bytes BIGINT
);

CREATE TABLE IF NOT EXISTS observations (
    obs_id TEXT PRIMARY KEY,
    dataset_id TEXT,
    obs_type TEXT NOT NULL,
    variable TEXT NOT NULL,
    value DOUBLE NOT NULL,
    unit TEXT NOT NULL,
    latitude DOUBLE NOT NULL,
    longitude DOUBLE NOT NULL,
    depth_m DOUBLE,
    time_start TIMESTAMP,
    time_end TIMESTAMP,
    qc_flags TEXT,
    extra TEXT
);

CREATE INDEX IF NOT EXISTS idx_obs_variable ON observations(variable);
CREATE INDEX IF NOT EXISTS idx_obs_latlon ON observations(latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_obs_dataset ON observations(dataset_id);

CREATE TABLE IF NOT EXISTS package_files (
    file_id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    role TEXT,
    format TEXT,
    bytes BIGINT,
    content_checksum TEXT NOT NULL,
    access_timestamp TIMESTAMP NOT NULL,
    missing_sentinel TEXT,
    time_zone TEXT
);

CREATE INDEX IF NOT EXISTS idx_pkgfiles_dataset ON package_files(dataset_id);
CREATE INDEX IF NOT EXISTS idx_pkgfiles_checksum ON package_files(content_checksum);

CREATE TABLE IF NOT EXISTS dataset_variables (
    dataset_id TEXT NOT NULL,
    variable TEXT NOT NULL,
    raw_name TEXT,
    unit TEXT,
    file_id TEXT NOT NULL,
    depth_range TEXT,
    time_range TEXT,
    crs_tier TEXT,
    parseable BOOLEAN,
    PRIMARY KEY (dataset_id, variable, file_id)
);

CREATE INDEX IF NOT EXISTS idx_dsvar_variable ON dataset_variables(variable);
"""


def open_catalog(path: Path | str = DEFAULT_CATALOG_PATH) -> duckdb.DuckDBPyConnection:
    """Open (or create) the DuckDB catalog file and ensure the schema exists."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(p))
    conn.execute(_SCHEMA_SQL)
    return conn


def register_dataset(
    conn: duckdb.DuckDBPyConnection,
    dataset_id: str,
    source_id: str,
    name: str = "",
    description: str = "",
    source_url: str = "",
    license: str = "",
    adapter_version: str = "",
    schema_version: str = "",
) -> None:
    """Register a dataset in the catalog (upsert)."""
    from datetime import datetime, timezone

    conn.execute(
        """
        INSERT OR REPLACE INTO datasets
            (dataset_id, source_id, name, description, source_url, license,
             registered_at, adapter_version, schema_version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            dataset_id, source_id, name, description, source_url, license,
            datetime.now(tz=timezone.utc), adapter_version, schema_version,
        ],
    )


def register_download(
    conn: duckdb.DuckDBPyConnection,
    fetch_result: "FetchResult",
) -> None:
    """Record a download in the catalog."""
    from e2sa.data.base import FetchResult  # noqa: F811

    conn.execute(
        """
        INSERT OR REPLACE INTO downloads
            (download_id, dataset_id, source_url, access_timestamp,
             content_checksum, local_path, bytes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            f"{fetch_result.dataset_id}_{fetch_result.content_checksum[:8]}",
            fetch_result.dataset_id,
            fetch_result.source_url,
            fetch_result.access_timestamp,
            fetch_result.content_checksum,
            str(fetch_result.local_path),
            fetch_result.bytes_downloaded,
        ],
    )


def register_package_files(
    conn: duckdb.DuckDBPyConnection,
    rows: list[dict],
) -> int:
    """Bulk-upsert package_files rows. Each dict has keys matching the table columns.

    Required: file_id, dataset_id, relative_path, content_checksum, access_timestamp.
    Optional: role, format, bytes.
    Idempotent: re-running with the same rows is a no-op (INSERT OR REPLACE).
    """
    if not rows:
        return 0
    payload = [
        (
            r["file_id"],
            r["dataset_id"],
            r["relative_path"],
            r.get("role"),
            r.get("format"),
            r.get("bytes"),
            r["content_checksum"],
            r["access_timestamp"],
            r.get("missing_sentinel"),
            r.get("time_zone"),
        )
        for r in rows
    ]
    conn.executemany(
        """
        INSERT OR REPLACE INTO package_files
            (file_id, dataset_id, relative_path, role, format, bytes,
             content_checksum, access_timestamp, missing_sentinel, time_zone)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        payload,
    )
    return len(payload)


def register_dataset_variables(
    conn: duckdb.DuckDBPyConnection,
    rows: list[dict],
) -> int:
    """Bulk-upsert dataset_variables rows. Each dict has keys matching the table columns.

    Required: dataset_id, variable, file_id.
    Optional: raw_name, unit, depth_range, time_range, crs_tier, parseable.
    Idempotent: re-running with the same rows is a no-op (INSERT OR REPLACE).
    """
    if not rows:
        return 0
    payload = [
        (
            r["dataset_id"],
            r["variable"],
            r.get("raw_name"),
            r.get("unit"),
            r["file_id"],
            r.get("depth_range"),
            r.get("time_range"),
            r.get("crs_tier"),
            r.get("parseable"),
        )
        for r in rows
    ]
    conn.executemany(
        """
        INSERT OR REPLACE INTO dataset_variables
            (dataset_id, variable, raw_name, unit, file_id, depth_range,
             time_range, crs_tier, parseable)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        payload,
    )
    return len(payload)


def ingest_observations(
    conn: duckdb.DuckDBPyConnection,
    observations: list,
    dataset_id: str,
    batch_size: int = 1000,
) -> int:
    """Bulk-insert Observation records into the catalog. Returns count inserted."""
    import json

    rows = []
    for obs in observations:
        rows.append((
            obs.obs_id,
            dataset_id,
            obs.obs_type.value,
            obs.variable.value,
            obs.value,
            obs.unit,
            obs.latitude,
            obs.longitude,
            obs.depth_m,
            obs.time_start,
            obs.time_end,
            ",".join(obs.qc_flags) if obs.qc_flags else None,
            json.dumps(obs.extra) if obs.extra else None,
        ))

    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        conn.executemany(
            """
            INSERT OR REPLACE INTO observations
                (obs_id, dataset_id, obs_type, variable, value, unit,
                 latitude, longitude, depth_m, time_start, time_end,
                 qc_flags, extra)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            batch,
        )

    return len(rows)
