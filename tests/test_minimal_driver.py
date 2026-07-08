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

from e2sa.data.adapters.sloan_2014_barrow_soil import Sloan2014BarrowSoilAdapter
from e2sa.data.connectors import ess_dive as ess_dive_mod
from e2sa.data.registry import ADAPTER_REGISTRY, get_adapter
from e2sa.orchestrator import AcquireResult, acquire
from e2sa.qc import Finding
from e2sa_cli.commands.acquire import acquire_cmd

# ---- registry ----


class TestAdapterRegistry:
    def test_all_expected_sources_registered(self) -> None:
        assert set(ADAPTER_REGISTRY) == {
            "calm_alt", "gtnp_magt", "webb_2026_alaska_thaw_db", "above_stdm",
            "sloan_2014_barrow_soil", "kanevskiy_2024_cryostratigraphy",
            "tsp_north_america_ground_temperature",
        }

    def test_get_adapter_returns_instance(self, tmp_path: Path) -> None:
        adapter = get_adapter("sloan_2014_barrow_soil", raw_dir=tmp_path)
        assert isinstance(adapter, Sloan2014BarrowSoilAdapter)
        # Connector-backed: raw_dir is the top raw dir (no per-source subdir);
        # the ess_dive connector owns the raw/ess_dive/<dataset_id>/ layout.
        assert adapter.raw_dir == tmp_path

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
            source_id="sloan_2014_barrow_soil",
            dataset_id="sloan_2014_barrow_soil",
            catalog_path=catalog,
            raw_dir=tmp_path / "raw",
        )

        assert isinstance(result, AcquireResult)
        assert result.source_id == "sloan_2014_barrow_soil"
        assert result.dataset_id == "sloan_2014_barrow_soil"
        assert result.dataset_dir == tmp_path / "raw" / "ess_dive" / "sloan_2014_barrow_soil"
        assert result.n_files_downloaded == 1
        assert result.bytes_downloaded > 0
        assert result.n_indexed_files == 1
        assert result.package_checksum == "ess-dive-driver-test-pkg-id"
        assert result.md5_mismatches == []
        assert catalog.exists()
        # acquire() makes the staged folder self-describing (docs/design/18).
        folder = result.dataset_dir
        for name in ("PROVENANCE.json", "CITATION.cff", "README.md"):
            assert (folder / name).exists(), f"missing bundle file {name}"

    def test_writes_dataset_row_to_catalog(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_ess_dive_http(monkeypatch)
        catalog = tmp_path / "cat.duckdb"

        acquire(
            source_id="sloan_2014_barrow_soil",
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
            assert row[1] == "sloan_2014_barrow_soil"
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
            source_id="sloan_2014_barrow_soil",
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

    def test_project_resolves_destination(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # acquire(project=...) resolves raw_dir + catalog from the project tree
        # (no hand-passed paths). project_paths is patched to a tmp root so the
        # test does not write into the repo's real projects/spade/.
        from e2sa import orchestrator
        from e2sa.config import ProjectPaths

        _patch_ess_dive_http(monkeypatch)
        data = tmp_path / "projects" / "spade" / "data"
        pp = ProjectPaths(
            project="spade", root=tmp_path / "projects" / "spade", data_dir=data,
            raw_dir=data / "raw", interim_dir=data / "interim",
            processed_dir=data / "processed", catalog_path=data / "catalog.duckdb",
        )
        monkeypatch.setattr(orchestrator, "project_paths", lambda project, **k: pp)

        result = acquire(
            "sloan_2014_barrow_soil", "sloan_2014_barrow_soil", project="spade"
        )
        # data lands at <project>/data/raw/<data_center>/<dataset_id>/
        assert result.dataset_dir == data / "raw" / "ess_dive" / "sloan_2014_barrow_soil"
        assert (data / "catalog.duckdb").exists()

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
                source_id="sloan_2014_barrow_soil",
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

        monkeypatch.setattr(Sloan2014BarrowSoilAdapter, "parse_to_schema", fake_parse)

        result = acquire(
            source_id="sloan_2014_barrow_soil",
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

    def test_parse_qc_flags_out_of_range_and_still_ingests(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """parse=True QCs the real parse: out-of-range values are logged (the
        value_range check is error-severity, so it logs at ERROR) but never
        block -- the data still ingests (outliers are QC's to flag, not the
        adapter's to drop)."""
        import logging

        _patch_ess_dive_http(monkeypatch)
        catalog = tmp_path / "cat.duckdb"
        raw = tmp_path / "raw"

        from e2sa.schema import Observation, ObservationType, Provenance, Variable

        def fake_parse(self, fetch_result):
            prov = Provenance(
                source_id="sloan_2014_barrow_soil",
                source_url=fetch_result.source_url,
                access_timestamp=fetch_result.access_timestamp,
                content_checksum=fetch_result.content_checksum,
                adapter_version="0.1.0",
            )
            # One in-range obs and one absurd value (999 degC, well past the
            # SOIL_TEMPERATURE [-60, 40] VALID_RANGE) that QC must flag.
            return [
                Observation(
                    obs_id="ok_obs", obs_type=ObservationType.POINT,
                    variable=Variable.SOIL_TEMPERATURE, value=5.0, unit="degC",
                    latitude=71.0, longitude=-156.0, depth_m=0.05,
                    qc_flags=[], provenance=prov,
                ),
                Observation(
                    obs_id="bad_obs", obs_type=ObservationType.POINT,
                    variable=Variable.SOIL_TEMPERATURE, value=999.0, unit="degC",
                    latitude=71.0, longitude=-156.0, depth_m=0.15,
                    qc_flags=[], provenance=prov,
                ),
            ]

        monkeypatch.setattr(Sloan2014BarrowSoilAdapter, "parse_to_schema", fake_parse)

        with caplog.at_level(logging.WARNING, logger="e2sa.orchestrator"):
            result = acquire(
                source_id="sloan_2014_barrow_soil",
                dataset_id="sloan_2014_barrow_soil",
                catalog_path=catalog,
                raw_dir=raw,
                parse=True,
            )

        # Data still ingested despite the QC finding (non-blocking, drops nothing).
        assert result.n_observations_ingested == 2
        # The findings are surfaced on the result (for the autonomous driver).
        assert len(result.qc_findings) >= 1
        # The out-of-range value produced a value_range QC log naming the dataset.
        qc_logs = [
            r for r in caplog.records
            if "QC" in r.message and "value_range" in r.getMessage()
        ]
        assert qc_logs, "expected a value_range QC log for the out-of-range value"
        assert qc_logs[0].levelno == logging.ERROR  # value_range is error-severity
        assert any("sloan_2014_barrow_soil" in r.getMessage() for r in qc_logs)

    def test_parse_qc_logs_at_finding_severity(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Each finding logs at its own severity: error-severity -> ERROR,
        warning-severity -> WARNING. validate_observations is patched to emit
        one of each so the split is tested independent of which checks happen
        to be error-severity today (all of them currently are)."""
        import logging

        from e2sa import orchestrator
        from e2sa.qc import Finding

        _patch_ess_dive_http(monkeypatch)
        catalog = tmp_path / "cat.duckdb"

        from e2sa.schema import Observation, ObservationType, Provenance, Variable

        def fake_parse(self, fetch_result):
            prov = Provenance(
                source_id="sloan_2014_barrow_soil",
                source_url=fetch_result.source_url,
                access_timestamp=fetch_result.access_timestamp,
                content_checksum=fetch_result.content_checksum,
                adapter_version="0.1.0",
            )
            return [
                Observation(
                    obs_id="o1", obs_type=ObservationType.POINT,
                    variable=Variable.SOIL_TEMPERATURE, value=1.0, unit="degC",
                    latitude=71.0, longitude=-156.0, depth_m=0.05,
                    qc_flags=[], provenance=prov,
                ),
            ]

        monkeypatch.setattr(Sloan2014BarrowSoilAdapter, "parse_to_schema", fake_parse)
        monkeypatch.setattr(
            orchestrator, "validate_observations",
            lambda serves, observations: [
                Finding("fake_err", "error", "boom"),
                Finding("fake_warn", "warning", "meh"),
            ],
        )

        with caplog.at_level(logging.WARNING, logger="e2sa.orchestrator"):
            result = acquire(
                source_id="sloan_2014_barrow_soil",
                dataset_id="sloan_2014_barrow_soil",
                catalog_path=catalog,
                raw_dir=tmp_path / "raw",
                parse=True,
            )

        assert result.n_observations_ingested == 1  # non-blocking
        # Per-finding lines start with "QC <severity> ["; the roll-up summary
        # line ("acquire(...): QC found ...") is excluded by the prefix filter.
        by_check = {r.getMessage().split("[")[1].split("]")[0]: r.levelno
                    for r in caplog.records if r.msg.startswith("QC %s [")}
        assert by_check.get("fake_err") == logging.ERROR
        assert by_check.get("fake_warn") == logging.WARNING

    def test_parse_clean_data_no_qc_logs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A clean parse (in-range, depth present, serves honored) emits no QC
        logs -- the check is quiet when nothing is wrong."""
        import logging

        _patch_ess_dive_http(monkeypatch)
        catalog = tmp_path / "cat.duckdb"

        from e2sa.schema import Observation, ObservationType, Provenance, Variable

        def fake_parse(self, fetch_result):
            prov = Provenance(
                source_id="sloan_2014_barrow_soil",
                source_url=fetch_result.source_url,
                access_timestamp=fetch_result.access_timestamp,
                content_checksum=fetch_result.content_checksum,
                adapter_version="0.1.0",
            )
            return [
                Observation(
                    obs_id="clean_obs", obs_type=ObservationType.POINT,
                    variable=Variable.SOIL_TEMPERATURE, value=-3.5, unit="degC",
                    latitude=71.0, longitude=-156.0, depth_m=0.10,
                    qc_flags=[], provenance=prov,
                ),
            ]

        monkeypatch.setattr(Sloan2014BarrowSoilAdapter, "parse_to_schema", fake_parse)

        with caplog.at_level(logging.WARNING, logger="e2sa.orchestrator"):
            acquire(
                source_id="sloan_2014_barrow_soil",
                dataset_id="sloan_2014_barrow_soil",
                catalog_path=catalog,
                raw_dir=tmp_path / "raw",
                parse=True,
            )

        assert not [r for r in caplog.records if "QC" in r.message]

    def test_parse_false_is_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """parse defaults False — observations table stays empty for the dataset."""
        _patch_ess_dive_http(monkeypatch)
        catalog = tmp_path / "cat.duckdb"

        acquire(
            source_id="sloan_2014_barrow_soil",
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

        ds = "sloan_2014_barrow_soil"
        acquire(ds, ds, catalog_path=catalog, raw_dir=raw)
        acquire(ds, ds, catalog_path=catalog, raw_dir=raw)

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
            source_id="sloan_2014_barrow_soil",
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
                    "--source", "sloan_2014_barrow_soil",
                    "--dataset", "sloan_2014_barrow_soil",
                    "--catalog", str(tmp_path / "cat.duckdb"),
                    "--raw-dir", str(tmp_path / "raw"),
                ],
            )

        assert result.exit_code == 0, result.output
        mock_acq.assert_called_once_with(
            source_id="sloan_2014_barrow_soil",
            dataset_id="sloan_2014_barrow_soil",
            project=None,
            catalog_path=tmp_path / "cat.duckdb",
            raw_dir=tmp_path / "raw",
            parse=False,
        )
        assert "acquired: sloan_2014_barrow_soil/sloan_2014_barrow_soil" in result.output
        assert "files downloaded: 47" in result.output
        assert "indexed variables: 130" in result.output

    def test_qc_findings_line_in_output(self, tmp_path: Path) -> None:
        """When a parse produced QC findings, the CLI summary surfaces the count."""
        runner = CliRunner()
        fake_result = AcquireResult(
            source_id="above_stdm", dataset_id="above_stdm",
            dataset_dir=tmp_path, n_files_downloaded=1, bytes_downloaded=1,
            n_indexed_files=1, n_indexed_variables=1, package_checksum="x",
            md5_mismatches=[], n_observations_ingested=100,
            qc_findings=[
                Finding("value_range", "error", "out of range"),
                Finding("subsurface_depth", "warning", "missing depth"),
                Finding("self_describing", "warning", "no README"),
            ],
        )
        with patch("e2sa_cli.commands.acquire.acquire", return_value=fake_result):
            result = runner.invoke(
                acquire_cmd,
                ["--source", "above_stdm", "--dataset", "above_stdm",
                 "--catalog", str(tmp_path / "c.duckdb"),
                 "--raw-dir", str(tmp_path / "raw"), "--parse"],
            )
        assert result.exit_code == 0, result.output
        assert "QC findings: 3" in result.output

    def test_project_flag_forwarded(self, tmp_path: Path) -> None:
        # --project is forwarded to acquire() (which resolves the paths); raw-dir
        # + catalog are left None so the project resolution applies.
        runner = CliRunner()
        fake = AcquireResult(
            source_id="sloan_2014_barrow_soil", dataset_id="sloan_2014_barrow_soil",
            dataset_dir=tmp_path, n_files_downloaded=1, bytes_downloaded=1,
            n_indexed_files=1, n_indexed_variables=1, package_checksum="x",
            md5_mismatches=[],
        )
        with patch("e2sa_cli.commands.acquire.acquire", return_value=fake) as mock_acq:
            result = runner.invoke(
                acquire_cmd,
                ["--source", "sloan_2014_barrow_soil",
                 "--dataset", "sloan_2014_barrow_soil", "--project", "spade"],
            )
        assert result.exit_code == 0, result.output
        mock_acq.assert_called_once_with(
            source_id="sloan_2014_barrow_soil",
            dataset_id="sloan_2014_barrow_soil",
            project="spade",
            catalog_path=None,
            raw_dir=None,
            parse=False,
        )

    def test_requires_project_or_raw_dir(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            acquire_cmd,
            ["--source", "sloan_2014_barrow_soil", "--dataset", "sloan_2014_barrow_soil"],
        )
        assert result.exit_code != 0
        out = result.output.lower()
        assert "project" in out and "raw-dir" in out

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
        result = runner.invoke(acquire_cmd, ["--source", "sloan_2014_barrow_soil"])
        assert result.exit_code != 0
        assert "Missing option" in result.output or "required" in result.output.lower()

    def test_md5_mismatch_warning_in_output(self, tmp_path: Path) -> None:
        runner = CliRunner()
        fake_result = AcquireResult(
            source_id="kanevskiy_2024_cryostratigraphy",
            dataset_id="kanevskiy_2024_cryostratigraphy",
            dataset_dir=tmp_path / "raw" / "kanevskiy_2024_cryostratigraphy",
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
                    "--source", "kanevskiy_2024_cryostratigraphy",
                    "--dataset", "kanevskiy_2024_cryostratigraphy",
                    "--catalog", str(tmp_path / "cat.duckdb"),
                    "--raw-dir", str(tmp_path / "raw"),
                ],
            )

        assert result.exit_code == 0
        assert "md5 mismatch" in result.output


class TestAcquireQc:
    """V1 (docs/design/19): acquire() attaches QC findings (advisory, non-fatal)."""

    def test_qc_findings_attached_and_warned(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog
    ) -> None:
        _patch_ess_dive_http(monkeypatch)
        # Inject a staged-folder finding so the wiring is exercised deterministically,
        # independent of the fake package's actual contents.
        import e2sa.orchestrator as orch

        monkeypatch.setattr(
            orch,
            "validate_staged_folder",
            lambda folder: [Finding("test_check", "warning", "injected", {})],
        )

        with caplog.at_level("WARNING"):
            result = acquire(
                source_id="sloan_2014_barrow_soil",
                dataset_id="sloan_2014_barrow_soil",
                catalog_path=tmp_path / "cat.duckdb",
                raw_dir=tmp_path / "raw",
            )

        assert [f.check for f in result.qc_findings] == ["test_check"]
        assert "QC found" in caplog.text

    def test_clean_acquire_has_list_findings(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_ess_dive_http(monkeypatch)
        result = acquire(
            source_id="sloan_2014_barrow_soil",
            dataset_id="sloan_2014_barrow_soil",
            catalog_path=tmp_path / "cat.duckdb",
            raw_dir=tmp_path / "raw",
        )
        assert isinstance(result.qc_findings, list)
