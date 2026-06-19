"""Tests for `e2sa catalog inspect` and its report builder."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from click.testing import CliRunner

from e2sa.catalog import (
    open_catalog,
    register_dataset,
    register_dataset_variables,
    register_package_files,
)
from e2sa_cli.commands.catalog import (
    _build_query_report,
    _build_report,
    _fmt_bytes,
    catalog_grp,
)

NOW = datetime(2026, 6, 18, tzinfo=UTC)


def _populate_small_catalog(conn) -> None:
    """Seed two datasets with files + variables for a realistic inspect test."""
    register_dataset(
        conn, dataset_id="ds_one", source_id="ess_dive",
        name="ESS-DIVE test package one",
        adapter_version="0.1.0", schema_version="0.1.0",
    )
    register_dataset(
        conn, dataset_id="ds_two", source_id="calm",
        name="CALM test", adapter_version="0.1.0", schema_version="0.1.0",
    )
    register_package_files(conn, [
        {
            "file_id": "fa", "dataset_id": "ds_one",
            "relative_path": "a.csv", "role": "data", "format": "csv",
            "bytes": 2048, "content_checksum": "h1", "access_timestamp": NOW,
        },
        {
            "file_id": "fb", "dataset_id": "ds_one",
            "relative_path": "b.csv", "role": "data", "format": "csv",
            "bytes": 4096, "content_checksum": "h2", "access_timestamp": NOW,
        },
        {
            "file_id": "fc", "dataset_id": "ds_two",
            "relative_path": "c.tsv", "role": "data", "format": "tsv",
            "bytes": 1024, "content_checksum": "h3", "access_timestamp": NOW,
        },
    ])
    register_dataset_variables(conn, [
        {"dataset_id": "ds_one", "variable": "soil_temperature",
         "file_id": "fa", "parseable": True},
        {"dataset_id": "ds_one", "variable": "raw_unmapped_col",
         "file_id": "fa", "parseable": False},
        {"dataset_id": "ds_two", "variable": "active_layer_thickness",
         "file_id": "fc", "parseable": True},
    ])


class TestFmtBytes:
    def test_bytes_under_1k(self) -> None:
        assert _fmt_bytes(512) == "512B"

    def test_kb(self) -> None:
        assert _fmt_bytes(2048) == "2.0KB"

    def test_mb(self) -> None:
        assert _fmt_bytes(5 * 1024 * 1024) == "5.0MB"

    def test_gb(self) -> None:
        assert _fmt_bytes(2 * 1024 * 1024 * 1024) == "2.00GB"


class TestBuildReport:
    def test_empty_catalog(self, tmp_path: Path) -> None:
        conn = open_catalog(tmp_path / "empty.duckdb")
        try:
            out = _build_report(conn)
        finally:
            conn.close()
        assert "0 datasets" in out
        assert "catalog is empty" in out

    def test_populated_catalog_shows_totals(self, tmp_path: Path) -> None:
        conn = open_catalog(tmp_path / "cat.duckdb")
        try:
            _populate_small_catalog(conn)
            out = _build_report(conn)
        finally:
            conn.close()
        assert "2 datasets" in out
        assert "3 files" in out
        assert "3 variables (2 parseable)" in out

    def test_populated_catalog_shows_per_dataset_rows(self, tmp_path: Path) -> None:
        conn = open_catalog(tmp_path / "cat.duckdb")
        try:
            _populate_small_catalog(conn)
            out = _build_report(conn)
        finally:
            conn.close()
        assert "ds_one" in out
        assert "ds_two" in out
        assert "ess_dive" in out
        assert "calm" in out

    def test_populated_catalog_shows_mapped_variables(self, tmp_path: Path) -> None:
        conn = open_catalog(tmp_path / "cat.duckdb")
        try:
            _populate_small_catalog(conn)
            out = _build_report(conn)
        finally:
            conn.close()
        assert "mapped variables" in out
        assert "soil_temperature" in out
        assert "active_layer_thickness" in out
        # Raw unmapped name should NOT appear under "mapped variables".
        mapped_block = out.split("mapped variables")[1]
        assert "raw_unmapped_col" not in mapped_block


class TestQueryReport:
    def test_no_hits_message(self, tmp_path: Path) -> None:
        conn = open_catalog(tmp_path / "cat.duckdb")
        try:
            _populate_small_catalog(conn)
            out = _build_query_report(conn, "ndvi")
        finally:
            conn.close()
        assert "no hits for variable 'ndvi'" in out

    def test_hits_grouped_by_dataset(self, tmp_path: Path) -> None:
        conn = open_catalog(tmp_path / "cat.duckdb")
        try:
            _populate_small_catalog(conn)
            out = _build_query_report(conn, "soil_temperature")
        finally:
            conn.close()
        # ds_one has soil_temperature (in file fa = a.csv).
        assert "soil_temperature" in out
        assert "[ess_dive]" in out
        assert "ds_one" in out
        assert "a.csv" in out
        # ds_two doesn't have soil_temperature.
        assert "ds_two" not in out

    def test_unparseable_rows_excluded(self, tmp_path: Path) -> None:
        """raw_unmapped_col is parseable=False and must not show up."""
        conn = open_catalog(tmp_path / "cat.duckdb")
        try:
            _populate_small_catalog(conn)
            out = _build_query_report(conn, "raw_unmapped_col")
        finally:
            conn.close()
        assert "no hits" in out


class TestQueryCLI:
    def test_invoke_query(self, tmp_path: Path) -> None:
        path = tmp_path / "cat.duckdb"
        conn = open_catalog(path)
        try:
            _populate_small_catalog(conn)
        finally:
            conn.close()
        runner = CliRunner()
        result = runner.invoke(
            catalog_grp,
            ["query", "--variable", "active_layer_thickness", "--catalog", str(path)],
        )
        assert result.exit_code == 0, result.output
        assert "active_layer_thickness" in result.output
        assert "[calm]" in result.output
        assert "ds_two" in result.output

    def test_missing_catalog_exits_2(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            catalog_grp,
            ["query", "--variable", "soil_temperature",
             "--catalog", str(tmp_path / "missing.duckdb")],
        )
        assert result.exit_code == 2

    def test_missing_required_variable_arg(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(catalog_grp, ["query"])
        assert result.exit_code != 0


class TestInspectCLI:
    def test_missing_catalog_exits_2(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            catalog_grp,
            ["inspect", "--catalog", str(tmp_path / "does_not_exist.duckdb")],
        )
        assert result.exit_code == 2
        assert "catalog not found" in result.output

    def test_invoke_against_populated_catalog(self, tmp_path: Path) -> None:
        path = tmp_path / "cat.duckdb"
        conn = open_catalog(path)
        try:
            _populate_small_catalog(conn)
        finally:
            conn.close()

        runner = CliRunner()
        result = runner.invoke(catalog_grp, ["inspect", "--catalog", str(path)])
        assert result.exit_code == 0, result.output
        assert "E2SA catalog inspect" in result.output
        assert "ds_one" in result.output
        assert "ds_two" in result.output
        assert "soil_temperature" in result.output
