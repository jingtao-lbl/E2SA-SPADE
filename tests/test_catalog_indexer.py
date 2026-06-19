"""Tests for the Phase A catalog indexer tables and writers.

Covers package_files + dataset_variables: round-trip, idempotency, NULL handling,
and the variable-by-file-id query the relevance matcher will use.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from e2sa.catalog import (
    open_catalog,
    register_dataset,
    register_dataset_variables,
    register_package_files,
)
from e2sa.data.indexing import index_package

NOW = datetime(2026, 6, 18, tzinfo=UTC)


def _seed_dataset(conn, dataset_id: str = "test_ds") -> None:
    register_dataset(
        conn,
        dataset_id=dataset_id,
        source_id="test_source",
        name="Test dataset",
        adapter_version="0.0.0",
        schema_version="0.1.0",
    )


def test_package_files_round_trip(tmp_path: Path) -> None:
    conn = open_catalog(tmp_path / "cat.duckdb")
    _seed_dataset(conn)

    rows = [
        {
            "file_id": "f1",
            "dataset_id": "test_ds",
            "relative_path": "data/a.csv",
            "role": "data",
            "format": "csv",
            "bytes": 1234,
            "content_checksum": "deadbeef",
            "access_timestamp": NOW,
        },
        {
            "file_id": "f2",
            "dataset_id": "test_ds",
            "relative_path": "metadata/science-metadata.xml",
            "role": "eml",
            "format": "xml",
            "bytes": 9999,
            "content_checksum": "cafebabe",
            "access_timestamp": NOW,
        },
    ]
    n = register_package_files(conn, rows)
    assert n == 2

    got = conn.execute(
        "SELECT file_id, role, format, bytes FROM package_files ORDER BY file_id"
    ).fetchall()
    assert got == [("f1", "data", "csv", 1234), ("f2", "eml", "xml", 9999)]

    conn.close()


def test_package_files_idempotent_upsert(tmp_path: Path) -> None:
    conn = open_catalog(tmp_path / "cat.duckdb")
    _seed_dataset(conn)

    row = {
        "file_id": "f1",
        "dataset_id": "test_ds",
        "relative_path": "data/a.csv",
        "role": "data",
        "format": "csv",
        "bytes": 1234,
        "content_checksum": "deadbeef",
        "access_timestamp": NOW,
    }
    register_package_files(conn, [row])
    register_package_files(conn, [row])

    count = conn.execute("SELECT COUNT(*) FROM package_files").fetchone()[0]
    assert count == 1

    conn.close()


def test_package_files_empty_list_is_no_op(tmp_path: Path) -> None:
    conn = open_catalog(tmp_path / "cat.duckdb")
    _seed_dataset(conn)
    assert register_package_files(conn, []) == 0
    assert register_dataset_variables(conn, []) == 0
    conn.close()


def test_dataset_variables_round_trip(tmp_path: Path) -> None:
    conn = open_catalog(tmp_path / "cat.duckdb")
    _seed_dataset(conn)
    register_package_files(
        conn,
        [
            {
                "file_id": "f_data",
                "dataset_id": "test_ds",
                "relative_path": "data/a.csv",
                "role": "data",
                "format": "csv",
                "bytes": 100,
                "content_checksum": "x",
                "access_timestamp": NOW,
            }
        ],
    )

    rows = [
        {
            "dataset_id": "test_ds",
            "variable": "soil_temperature",
            "raw_name": "Tsoil_5cm",
            "unit": "degC",
            "file_id": "f_data",
            "depth_range": "0.05-0.05 m",
            "time_range": "2012-2013",
            "crs_tier": "pdf",
            "parseable": True,
        },
        {
            "dataset_id": "test_ds",
            "variable": "soil_moisture_raw",
            "file_id": "f_data",
            "parseable": False,
        },
    ]
    n = register_dataset_variables(conn, rows)
    assert n == 2

    parsed = conn.execute(
        "SELECT variable, unit, parseable FROM dataset_variables ORDER BY variable"
    ).fetchall()
    assert parsed == [
        ("soil_moisture_raw", None, False),
        ("soil_temperature", "degC", True),
    ]

    conn.close()


def test_index_package_single_file_registers_one_row(tmp_path: Path) -> None:
    """index_package handed a file (not a dir) records one package_files row."""
    conn = open_catalog(tmp_path / "cat.duckdb")
    _seed_dataset(conn, "single_file_ds")

    f = tmp_path / "alaska_thaw_db_v2.zip"
    f.write_bytes(b"fake zip content for test")

    result = index_package(conn, "single_file_ds", f)
    assert result.standard == "single_file"
    assert result.n_files == 1
    assert result.n_variables == 0
    assert result.md5_mismatches == []

    rows = conn.execute(
        "SELECT relative_path, role, format, bytes FROM package_files "
        "WHERE dataset_id = 'single_file_ds'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "alaska_thaw_db_v2.zip"
    assert rows[0][3] == len(b"fake zip content for test")

    conn.close()


def test_index_package_skips_dot_prefixed_files(tmp_path: Path) -> None:
    """Hidden files (e.g. .essdive_package_id) are adapter-internal state, not data."""
    conn = open_catalog(tmp_path / "cat.duckdb")
    _seed_dataset(conn, "dot_skip_ds")
    pkg_dir = tmp_path / "pkg"
    pkg_dir.mkdir()
    (pkg_dir / "real_data.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (pkg_dir / ".essdive_package_id").write_text("hidden-cache", encoding="utf-8")
    (pkg_dir / ".DS_Store").write_text("mac noise", encoding="utf-8")

    result = index_package(conn, "dot_skip_ds", pkg_dir)
    assert result.n_files == 1

    rels = [
        r[0] for r in conn.execute(
            "SELECT relative_path FROM package_files WHERE dataset_id = 'dot_skip_ds'"
        ).fetchall()
    ]
    assert rels == ["real_data.csv"]
    conn.close()


def test_index_package_missing_path_raises(tmp_path: Path) -> None:
    conn = open_catalog(tmp_path / "cat.duckdb")
    _seed_dataset(conn)
    nonexistent = tmp_path / "definitely_not_here"
    with pytest.raises(FileNotFoundError, match="Not a file or directory"):
        index_package(conn, "test_ds", nonexistent)
    conn.close()


def test_dataset_variables_query_by_variable(tmp_path: Path) -> None:
    """The relevance matcher's core query: which datasets/files hold variable X."""
    conn = open_catalog(tmp_path / "cat.duckdb")
    _seed_dataset(conn, "ds_a")
    _seed_dataset(conn, "ds_b")
    register_package_files(
        conn,
        [
            {
                "file_id": "fa",
                "dataset_id": "ds_a",
                "relative_path": "a.csv",
                "role": "data",
                "format": "csv",
                "bytes": 1,
                "content_checksum": "a",
                "access_timestamp": NOW,
            },
            {
                "file_id": "fb",
                "dataset_id": "ds_b",
                "relative_path": "b.csv",
                "role": "data",
                "format": "csv",
                "bytes": 1,
                "content_checksum": "b",
                "access_timestamp": NOW,
            },
        ],
    )
    register_dataset_variables(
        conn,
        [
            {"dataset_id": "ds_a", "variable": "volumetric_ice_content", "file_id": "fa"},
            {"dataset_id": "ds_b", "variable": "soil_temperature", "file_id": "fb"},
        ],
    )

    hits = conn.execute(
        "SELECT dataset_id, file_id FROM dataset_variables WHERE variable = ?",
        ["volumetric_ice_content"],
    ).fetchall()
    assert hits == [("ds_a", "fa")]

    conn.close()
