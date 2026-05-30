"""Test catalog integration: adapter -> parse -> ingest into DuckDB."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from e2sa.catalog import ingest_observations, open_catalog, register_dataset, register_download
from e2sa.data.base import FetchResult
from e2sa.data.calm import CALMAdapter

FIXTURES = Path(__file__).parent / "fixtures"


def test_calm_end_to_end_into_catalog(tmp_path: Path) -> None:
    """Parse CALM fixture, ingest into catalog, query back."""
    conn = open_catalog(tmp_path / "test_catalog.duckdb")

    register_dataset(
        conn,
        dataset_id="calm_test",
        source_id="calm",
        name="CALM test fixture",
        adapter_version="0.1.0",
        schema_version="0.1.0",
    )

    fr = FetchResult(
        dataset_id="calm_test",
        local_path=FIXTURES / "calm_sample.tsv",
        bytes_downloaded=1000,
        access_timestamp=datetime(2026, 4, 12, tzinfo=timezone.utc),
        content_checksum="fixture_checksum",
        source_url="https://test.invalid",
    )
    register_download(conn, fr)

    adapter = CALMAdapter(raw_dir=tmp_path)
    observations = adapter.parse_to_schema(fr)
    count = ingest_observations(conn, observations, dataset_id="calm_test")

    assert count == len(observations)
    assert count > 0

    result = conn.execute("SELECT COUNT(*) FROM observations").fetchone()
    assert result[0] == count

    result = conn.execute(
        "SELECT COUNT(*) FROM observations WHERE variable = 'active_layer_thickness'"
    ).fetchone()
    assert result[0] == count

    result = conn.execute("SELECT COUNT(*) FROM datasets").fetchone()
    assert result[0] == 1

    result = conn.execute("SELECT COUNT(*) FROM downloads").fetchone()
    assert result[0] == 1

    conn.close()
