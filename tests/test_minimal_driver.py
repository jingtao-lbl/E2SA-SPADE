"""Tests for the minimal acquire() driver and its CLI wrapper.

Covers e2sa.data.registry.get_adapter, e2sa.orchestrator.acquire (with
mocked fetch so no network), and the `e2sa acquire` Click command.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from e2sa.data import ess_dive as ess_dive_mod
from e2sa.data.ess_dive import ESSDIVEAdapter
from e2sa.data.registry import ADAPTER_REGISTRY, get_adapter
from e2sa.orchestrator import AcquireResult, acquire
from e2sa_cli.commands.acquire import acquire_cmd

# ---- registry ----


class TestAdapterRegistry:
    def test_all_expected_sources_registered(self) -> None:
        assert set(ADAPTER_REGISTRY) == {
            "calm", "gtnp", "alaska_thaw_db", "above", "ess_dive",
        }

    def test_get_adapter_returns_instance(self, tmp_path: Path) -> None:
        adapter = get_adapter("ess_dive", raw_dir=tmp_path)
        assert isinstance(adapter, ESSDIVEAdapter)
        assert adapter.raw_dir == tmp_path / "ess_dive"

    def test_get_adapter_unknown_raises_with_options(self, tmp_path: Path) -> None:
        with pytest.raises(KeyError, match="Unknown source_id"):
            get_adapter("not_a_real_source", raw_dir=tmp_path)


# ---- acquire() ----


def _fake_essdive_metadata(name: str, body: bytes) -> dict:
    """Same shape as ESS-DIVE's JSON-LD response, one file."""
    return {
        "id": "ess-dive-driver-test-pkg-id",
        "isPublic": True,
        "dataset": {
            "@type": "Dataset",
            "@id": "doi:10.5440/1121134",
            "name": "Fake Sloan package for driver test",
            "distribution": [
                {
                    "contentUrl": f"https://data.ess-dive.lbl.gov/catalog/d1/mn/v2/object/fake-{name}",
                    "encodingFormat": "text/csv",
                    "identifier": f"fake-{name}",
                    "name": name,
                    "contentSize": len(body) / 1024,
                }
            ],
        },
    }


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        import io
        self._buf = io.BytesIO(body)
        self.status = 200
        self.headers = {"Content-Length": str(len(body))}

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc) -> None:
        self._buf.close()

    def read(self, size: int = -1) -> bytes:
        return self._buf.read(size) if size != -1 else self._buf.read()


def _patch_ess_dive_http(monkeypatch: pytest.MonkeyPatch) -> None:
    body = b"region,site\nN/A,N/A\n"
    metadata = _fake_essdive_metadata("BEO_soil_properties_user_file.pdf", body)

    def fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        if "/packages/doi:" in url:
            return _FakeResponse(json.dumps(metadata).encode("utf-8"))
        return _FakeResponse(body)

    monkeypatch.setattr(ess_dive_mod.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("ESS_DIVE_TOKEN", "fake-token-for-driver-test")


class TestAcquire:
    def test_returns_acquire_result_with_summary(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_ess_dive_http(monkeypatch)
        catalog = tmp_path / "cat.duckdb"

        result = acquire(
            source_id="ess_dive",
            dataset_id="sloan_2014_barrow_soil",
            catalog_path=catalog,
            raw_dir=tmp_path / "raw",
        )

        assert isinstance(result, AcquireResult)
        assert result.source_id == "ess_dive"
        assert result.dataset_id == "sloan_2014_barrow_soil"
        assert result.dataset_dir == tmp_path / "raw" / "ess_dive" / "sloan_2014_barrow_soil"
        assert result.n_files_downloaded == 1
        assert result.bytes_downloaded > 0
        assert result.n_indexed_files == 1
        assert result.package_checksum == "ess-dive-driver-test-pkg-id"
        assert result.md5_mismatches == []
        assert catalog.exists()

    def test_writes_dataset_row_to_catalog(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_ess_dive_http(monkeypatch)
        catalog = tmp_path / "cat.duckdb"

        acquire(
            source_id="ess_dive",
            dataset_id="sloan_2014_barrow_soil",
            catalog_path=catalog,
            raw_dir=tmp_path / "raw",
        )

        from e2sa.catalog import open_catalog
        conn = open_catalog(catalog)
        try:
            row = conn.execute(
                "SELECT dataset_id, source_id, name, source_url, adapter_version "
                "FROM datasets WHERE dataset_id = ?",
                ["sloan_2014_barrow_soil"],
            ).fetchone()
            assert row is not None
            assert row[0] == "sloan_2014_barrow_soil"
            assert row[1] == "ess_dive"
            assert "Barrow" in row[2] or "Utqiagvik" in row[2]
            assert row[3] == "https://doi.org/10.5440/1121134"
            assert row[4] == "0.1.0"
        finally:
            conn.close()

    def test_writes_download_row(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_ess_dive_http(monkeypatch)
        catalog = tmp_path / "cat.duckdb"

        acquire(
            source_id="ess_dive",
            dataset_id="sloan_2014_barrow_soil",
            catalog_path=catalog,
            raw_dir=tmp_path / "raw",
        )

        from e2sa.catalog import open_catalog
        conn = open_catalog(catalog)
        try:
            n = conn.execute(
                "SELECT COUNT(*) FROM downloads WHERE dataset_id = ?",
                ["sloan_2014_barrow_soil"],
            ).fetchone()[0]
            assert n == 1
        finally:
            conn.close()

    def test_unknown_source_raises(self, tmp_path: Path) -> None:
        with pytest.raises(KeyError, match="Unknown source_id"):
            acquire(
                source_id="not_a_source",
                dataset_id="anything",
                catalog_path=tmp_path / "cat.duckdb",
                raw_dir=tmp_path / "raw",
            )

    def test_parse_true_ingests_observations(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """parse=True: observations from parse_to_schema land in the observations table."""
        _patch_ess_dive_http(monkeypatch)
        catalog = tmp_path / "cat.duckdb"
        raw = tmp_path / "raw"

        # Replace parse_to_schema with a stub returning two synthetic obs so we
        # don't depend on a specific dataset's parser implementation here.
        from e2sa.schema import Observation, ObservationType, Provenance, Variable

        def fake_parse(self, fetch_result):
            prov = Provenance(
                source_id="ess_dive",
                source_url=fetch_result.source_url,
                access_timestamp=fetch_result.access_timestamp,
                content_checksum=fetch_result.content_checksum,
                adapter_version="0.1.0",
            )
            return [
                Observation(
                    obs_id="test_obs_001", obs_type=ObservationType.POINT,
                    variable=Variable.SOIL_TEMPERATURE, value=5.0, unit="degC",
                    latitude=71.0, longitude=-156.0, depth_m=0.05,
                    qc_flags=[], provenance=prov,
                ),
                Observation(
                    obs_id="test_obs_002", obs_type=ObservationType.POINT,
                    variable=Variable.SOIL_TEMPERATURE, value=4.5, unit="degC",
                    latitude=71.0, longitude=-156.0, depth_m=0.15,
                    qc_flags=[], provenance=prov,
                ),
            ]

        monkeypatch.setattr(ESSDIVEAdapter, "parse_to_schema", fake_parse)

        result = acquire(
            source_id="ess_dive",
            dataset_id="sloan_2014_barrow_soil",
            catalog_path=catalog,
            raw_dir=raw,
            parse=True,
        )

        assert result.n_observations_ingested == 2

        from e2sa.catalog import open_catalog
        conn = open_catalog(catalog)
        try:
            n_obs = conn.execute(
                "SELECT COUNT(*) FROM observations WHERE dataset_id = ?",
                ["sloan_2014_barrow_soil"],
            ).fetchone()[0]
            assert n_obs == 2
        finally:
            conn.close()

    def test_parse_false_is_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """parse defaults False — observations table stays empty for the dataset."""
        _patch_ess_dive_http(monkeypatch)
        catalog = tmp_path / "cat.duckdb"

        acquire(
            source_id="ess_dive",
            dataset_id="sloan_2014_barrow_soil",
            catalog_path=catalog,
            raw_dir=tmp_path / "raw",
        )

        from e2sa.catalog import open_catalog
        conn = open_catalog(catalog)
        try:
            n_obs = conn.execute(
                "SELECT COUNT(*) FROM observations WHERE dataset_id = ?",
                ["sloan_2014_barrow_soil"],
            ).fetchone()[0]
            assert n_obs == 0
        finally:
            conn.close()

    def test_idempotent_second_call(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two acquires of the same dataset = one catalog row each, no duplicates."""
        _patch_ess_dive_http(monkeypatch)
        catalog = tmp_path / "cat.duckdb"
        raw = tmp_path / "raw"

        acquire("ess_dive", "sloan_2014_barrow_soil", catalog_path=catalog, raw_dir=raw)
        acquire("ess_dive", "sloan_2014_barrow_soil", catalog_path=catalog, raw_dir=raw)

        from e2sa.catalog import open_catalog
        conn = open_catalog(catalog)
        try:
            dsid = "sloan_2014_barrow_soil"
            n_ds = conn.execute(
                "SELECT COUNT(*) FROM datasets WHERE dataset_id = ?", [dsid]
            ).fetchone()[0]
            n_dl = conn.execute(
                "SELECT COUNT(*) FROM downloads WHERE dataset_id = ?", [dsid]
            ).fetchone()[0]
            n_pf = conn.execute(
                "SELECT COUNT(*) FROM package_files WHERE dataset_id = ?", [dsid]
            ).fetchone()[0]
            assert n_ds == 1
            assert n_dl == 1
            assert n_pf == 1
        finally:
            conn.close()


# ---- CLI ----


class TestAcquireCLI:
    def test_invokes_acquire_with_parsed_args(self, tmp_path: Path) -> None:
        """Patch acquire() so we don't hit network/disk; verify the CLI passed
        the right args through."""
        runner = CliRunner()
        fake_result = AcquireResult(
            source_id="ess_dive",
            dataset_id="sloan_2014_barrow_soil",
            dataset_dir=tmp_path / "raw" / "ess_dive" / "sloan_2014_barrow_soil",
            n_files_downloaded=47,
            bytes_downloaded=133_543_806,
            n_indexed_files=47,
            n_indexed_variables=130,
            package_checksum="ess-dive-2b96c166c484e6b-20240927T115806255",
            md5_mismatches=[],
        )

        with patch("e2sa_cli.commands.acquire.acquire", return_value=fake_result) as mock_acq:
            result = runner.invoke(
                acquire_cmd,
                [
                    "--source", "ess_dive",
                    "--dataset", "sloan_2014_barrow_soil",
                    "--catalog", str(tmp_path / "cat.duckdb"),
                    "--raw-dir", str(tmp_path / "raw"),
                ],
            )

        assert result.exit_code == 0, result.output
        mock_acq.assert_called_once_with(
            source_id="ess_dive",
            dataset_id="sloan_2014_barrow_soil",
            catalog_path=tmp_path / "cat.duckdb",
            raw_dir=tmp_path / "raw",
            parse=False,
        )
        assert "acquired: ess_dive/sloan_2014_barrow_soil" in result.output
        assert "files downloaded: 47" in result.output
        assert "indexed variables: 130" in result.output

    def test_unknown_source_exit_code_2(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            acquire_cmd,
            [
                "--source", "not_a_source",
                "--dataset", "anything",
                "--catalog", str(tmp_path / "cat.duckdb"),
                "--raw-dir", str(tmp_path / "raw"),
            ],
        )
        assert result.exit_code == 2
        assert "Unknown source_id" in result.output

    def test_missing_required_args_fails(self) -> None:
        runner = CliRunner()
        result = runner.invoke(acquire_cmd, ["--source", "ess_dive"])
        assert result.exit_code != 0
        assert "Missing option" in result.output or "required" in result.output.lower()

    def test_md5_mismatch_warning_in_output(self, tmp_path: Path) -> None:
        runner = CliRunner()
        fake_result = AcquireResult(
            source_id="kanevskiy_cryostratigraphy",
            dataset_id="kanevskiy_v2024",
            dataset_dir=tmp_path / "raw" / "kanevskiy",
            n_files_downloaded=10,
            bytes_downloaded=1024,
            n_indexed_files=10,
            n_indexed_variables=20,
            package_checksum="ess-dive-x",
            md5_mismatches=["data/file_a.csv", "data/file_b.csv"],
        )

        with patch("e2sa_cli.commands.acquire.acquire", return_value=fake_result):
            result = runner.invoke(
                acquire_cmd,
                [
                    "--source", "ess_dive",
                    "--dataset", "kanevskiy_v2024",
                    "--catalog", str(tmp_path / "cat.duckdb"),
                    "--raw-dir", str(tmp_path / "raw"),
                ],
            )

        assert result.exit_code == 0
        assert "md5 mismatch" in result.output
