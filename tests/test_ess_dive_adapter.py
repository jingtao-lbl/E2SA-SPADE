"""Tests for the ESS-DIVE adapter (e2sa.data.ess_dive).

Pure-Python tests: list_available, registry lookup, token preflight,
and fetch() with urlopen monkeypatched so no network is hit. One opt-in
@pytest.mark.skipif test exercises the real Sloan 2014 download if
ESS_DIVE_TOKEN is set in the environment.
"""
from __future__ import annotations

import io
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError

import pytest

from e2sa.data import ess_dive
from e2sa.data.base import FetchResult
from e2sa.data.ess_dive import (
    ESSDIVEAdapter,
    _find_config,
    _require_token,
)

# ---- fake server: enough to satisfy ESS-DIVE's two-step protocol ----


def _fake_metadata(file_specs: list[dict]) -> dict:
    """Build a JSON-LD response mimicking GET /packages/doi:<DOI>.

    file_specs is a list of {name, bytes_b64-or-str} stubs. We expose
    each as a distribution[] entry pointing at a fake contentUrl.
    """
    return {
        "id": "ess-dive-fake-id-20260618",
        "viewUrl": "https://data.ess-dive.lbl.gov/view/doi:10.5440/1121134",
        "url": "https://api.ess-dive.lbl.gov/packages/ess-dive-fake-id-20260618",
        "isPublic": True,
        "citation": "Test fixture",
        "dataset": {
            "@context": "http://schema.org/",
            "@type": "Dataset",
            "@id": "doi:10.5440/1121134",
            "name": "Fake test package",
            "distribution": [
                {
                    "contentUrl": (
                        f"https://data.ess-dive.lbl.gov/catalog/d1/mn/v2/object/"
                        f"fake-{spec['name']}"
                    ),
                    "encodingFormat": "text/csv",
                    "identifier": f"fake-{spec['name']}",
                    "name": spec["name"],
                    "contentSize": len(spec["body"].encode("utf-8")) / 1024,
                }
                for spec in file_specs
            ],
        },
    }


class _FakeResponse:
    """Context-manager response wrapper that mimics urllib.response."""

    def __init__(self, body: bytes, status: int = 200) -> None:
        self._buf = io.BytesIO(body)
        self.status = status
        self.headers = {"Content-Length": str(len(body))}

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc) -> None:
        self._buf.close()

    def read(self, size: int = -1) -> bytes:
        return self._buf.read(size) if size != -1 else self._buf.read()


def _make_dispatcher(metadata: dict, file_bodies: dict[str, bytes]):
    """Return a urlopen replacement that serves metadata + each file body."""

    def fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        if "/packages/doi:" in url:
            return _FakeResponse(json.dumps(metadata).encode("utf-8"))
        for name, body in file_bodies.items():
            if url.endswith(f"fake-{name}"):
                return _FakeResponse(body)
        raise HTTPError(url, 404, "Not Found", {}, io.BytesIO(b""))

    return fake_urlopen


# ---- list_available + registry ----


class TestListAvailable:
    def test_returns_at_least_sloan(self, tmp_path: Path) -> None:
        adapter = ESSDIVEAdapter(raw_dir=tmp_path)
        datasets = adapter.list_available()
        assert len(datasets) >= 1
        ids = {d.dataset_id for d in datasets}
        assert "sloan_2014_barrow_soil" in ids

    def test_sloan_metadata_fields_set(self, tmp_path: Path) -> None:
        adapter = ESSDIVEAdapter(raw_dir=tmp_path)
        sloan = next(
            d for d in adapter.list_available()
            if d.dataset_id == "sloan_2014_barrow_soil"
        )
        assert sloan.url == "https://doi.org/10.5440/1121134"
        assert "Barrow" in sloan.name or "Utqiagvik" in sloan.name
        assert "soil_temperature" in sloan.variables


class TestFindConfig:
    def test_known_dataset_id(self) -> None:
        cfg = _find_config("sloan_2014_barrow_soil")
        assert cfg.doi == "10.5440/1121134"

    def test_unknown_raises_keyerror(self) -> None:
        with pytest.raises(KeyError, match="Unknown ESS-DIVE dataset_id"):
            _find_config("not_a_real_dataset")


# ---- _require_token ----


class TestRequireToken:
    def test_missing_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ESS_DIVE_TOKEN", raising=False)
        with pytest.raises(RuntimeError, match="ESS_DIVE_TOKEN env var is not set"):
            _require_token()

    def test_present_returns_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ESS_DIVE_TOKEN", "fake-token-value")
        assert _require_token() == "fake-token-value"


# ---- fetch (mocked HTTP) ----


@pytest.fixture
def two_file_pkg() -> tuple[dict, dict[str, bytes]]:
    file_a_body = b"region,site,value\nN/A,N/A,1.0\n"
    file_b_body = b"header,col\n1,2\n3,4\n"
    metadata = _fake_metadata([
        {"name": "file_a.csv", "body": file_a_body.decode()},
        {"name": "file_b.csv", "body": file_b_body.decode()},
    ])
    bodies = {"file_a.csv": file_a_body, "file_b.csv": file_b_body}
    return metadata, bodies


class TestFetch:
    def test_downloads_all_files_and_returns_files_list(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        two_file_pkg: tuple[dict, dict[str, bytes]],
    ) -> None:
        metadata, bodies = two_file_pkg
        monkeypatch.setenv("ESS_DIVE_TOKEN", "fake")
        monkeypatch.setattr(
            ess_dive.urllib.request,
            "urlopen",
            _make_dispatcher(metadata, bodies),
        )

        adapter = ESSDIVEAdapter(raw_dir=tmp_path)
        result = adapter.fetch("sloan_2014_barrow_soil")

        assert isinstance(result, FetchResult)
        assert result.local_path == tmp_path / "ess_dive" / "sloan_2014_barrow_soil"
        assert len(result.files) == 2
        assert {p.name for p in result.files} == {"file_a.csv", "file_b.csv"}
        for p in result.files:
            assert p.exists() and p.stat().st_size > 0
        assert result.bytes_downloaded == sum(len(b) for b in bodies.values())
        assert result.content_checksum == "ess-dive-fake-id-20260618"
        assert result.source_url == "https://doi.org/10.5440/1121134"

    def test_idempotent_second_call_skips_redownload(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        two_file_pkg: tuple[dict, dict[str, bytes]],
    ) -> None:
        metadata, bodies = two_file_pkg
        monkeypatch.setenv("ESS_DIVE_TOKEN", "fake")

        call_log: list[str] = []

        def logging_dispatcher(metadata, bodies):
            inner = _make_dispatcher(metadata, bodies)

            def wrapped(req, timeout=None):
                url = req.full_url if hasattr(req, "full_url") else req
                call_log.append(url)
                return inner(req, timeout=timeout)
            return wrapped

        monkeypatch.setattr(
            ess_dive.urllib.request,
            "urlopen",
            logging_dispatcher(metadata, bodies),
        )

        adapter = ESSDIVEAdapter(raw_dir=tmp_path)
        adapter.fetch("sloan_2014_barrow_soil")
        first_call_count = len(call_log)
        assert first_call_count == 3  # 1 metadata + 2 file downloads

        adapter.fetch("sloan_2014_barrow_soil")
        second_call_count = len(call_log) - first_call_count
        # Fast path: cached .essdive_package_id + files on disk → no API hits.
        assert second_call_count == 0, (
            f"Expected zero API calls on second invocation (fast path), got {second_call_count}: "
            f"{call_log[first_call_count:]}"
        )

    def test_partial_file_is_redownloaded(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        two_file_pkg: tuple[dict, dict[str, bytes]],
    ) -> None:
        """A short/corrupt file on disk should trigger re-download (size mismatch)."""
        metadata, bodies = two_file_pkg
        monkeypatch.setenv("ESS_DIVE_TOKEN", "fake")
        monkeypatch.setattr(
            ess_dive.urllib.request,
            "urlopen",
            _make_dispatcher(metadata, bodies),
        )

        adapter = ESSDIVEAdapter(raw_dir=tmp_path)
        result = adapter.fetch("sloan_2014_barrow_soil")
        # Corrupt one file (truncate to 1 byte)
        result.files[0].write_bytes(b"x")

        result2 = adapter.fetch("sloan_2014_barrow_soil")
        # After re-fetch the file should be back to its full size
        full_size = len(bodies[result2.files[0].name])
        assert result2.files[0].stat().st_size == full_size

    def test_missing_token_fails_fast(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("ESS_DIVE_TOKEN", raising=False)
        adapter = ESSDIVEAdapter(raw_dir=tmp_path)
        with pytest.raises(RuntimeError, match="ESS_DIVE_TOKEN"):
            adapter.fetch("sloan_2014_barrow_soil")

    def test_fast_path_skips_token_when_cache_and_files_present(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If .essdive_package_id + data files exist on disk, no token needed."""
        # Build a dataset dir with one data file + the id cache.
        dataset_dir = tmp_path / "ess_dive" / "sloan_2014_barrow_soil"
        dataset_dir.mkdir(parents=True)
        body = b"region,site\nN/A,N/A\n"
        (dataset_dir / "BEO_data.csv").write_bytes(body)
        (dataset_dir / ".essdive_package_id").write_text(json.dumps({
            "id": "ess-dive-cached-id-from-prior-run",
            "files": {"BEO_data.csv": len(body)},
        }))

        # Prove API is never called: make urlopen raise.
        def _no_network(*args, **kwargs):
            raise AssertionError("urlopen should NOT be called when cache is warm")
        monkeypatch.setattr(ess_dive.urllib.request, "urlopen", _no_network)
        monkeypatch.delenv("ESS_DIVE_TOKEN", raising=False)  # no token at all

        adapter = ESSDIVEAdapter(raw_dir=tmp_path)
        result = adapter.fetch("sloan_2014_barrow_soil")

        assert result.content_checksum == "ess-dive-cached-id-from-prior-run"
        assert len(result.files) == 1
        assert result.files[0].name == "BEO_data.csv"
        assert result.bytes_downloaded > 0

    def test_unknown_dataset_id_fails_fast(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ESS_DIVE_TOKEN", "fake")
        adapter = ESSDIVEAdapter(raw_dir=tmp_path)
        with pytest.raises(KeyError, match="Unknown ESS-DIVE dataset_id"):
            adapter.fetch("does_not_exist")


# ---- parse spec: Sloan 2014 30-min ----

SLOAN_FIXTURE = Path(__file__).parent / "fixtures" / "sloan_30min_pkg"


def _sloan_fixture_fetch_result() -> FetchResult:
    return FetchResult(
        dataset_id="sloan_2014_barrow_soil",
        local_path=SLOAN_FIXTURE,
        bytes_downloaded=0,
        access_timestamp=datetime(2026, 6, 18, 12, 0, tzinfo=UTC),
        content_checksum="ess-dive-fixture-pkg-id",
        source_url="https://doi.org/10.5440/1121134",
        files=[],
    )


class TestParseSloan:
    def test_emits_six_30min_plus_five_perplot_observations(self) -> None:
        """30-min: 10 rows, 4 skipped → 6 obs.
        Per-plot: A1C 5 rows (3 valid; 2 NaN/empty skipped) + A1E 2 rows
        + XYZ unknown plot skipped. Total: 6 + 3 + 2 = 11.
        """
        adapter = ESSDIVEAdapter(raw_dir=Path("/tmp/test_ess_dive"))
        obs = adapter.parse_to_schema(_sloan_fixture_fetch_result())
        n_30min = sum(1 for o in obs if "30min" in o.obs_id)
        n_perplot = sum(1 for o in obs if "perplot" in o.obs_id)
        assert n_30min == 6, f"expected 6 30-min, got {n_30min}"
        assert n_perplot == 5, f"expected 5 per-plot, got {n_perplot}"
        assert len(obs) == 11

    def test_reprojects_to_barrow_area(self) -> None:
        """A1C/A1E real UTM coords should land at Barrow (~71.28 N, -156.6 W)."""
        adapter = ESSDIVEAdapter(raw_dir=Path("/tmp/test_ess_dive"))
        obs = adapter.parse_to_schema(_sloan_fixture_fetch_result())
        for o in obs:
            assert 71.0 < o.latitude < 71.5, f"lat {o.latitude} not at Barrow"
            assert -156.8 < o.longitude < -156.4, f"lon {o.longitude} not at Barrow"

    def test_depth_cm_converted_to_m(self) -> None:
        """Source has 5/15/25 cm; output must be 0.05/0.15/0.25 m."""
        adapter = ESSDIVEAdapter(raw_dir=Path("/tmp/test_ess_dive"))
        obs = adapter.parse_to_schema(_sloan_fixture_fetch_result())
        depths_m = {o.depth_m for o in obs}
        assert depths_m == {0.05, 0.15, 0.25}

    def test_akst_converted_to_utc(self) -> None:
        """Row 'date=2012-06-23 time=19:00 AKST' should be 2012-06-24 04:00 UTC."""
        adapter = ESSDIVEAdapter(raw_dir=Path("/tmp/test_ess_dive"))
        obs = adapter.parse_to_schema(_sloan_fixture_fetch_result())
        # All time_starts must be tz-aware UTC.
        for o in obs:
            assert o.time_start is not None
            assert o.time_start.utcoffset() == timedelta(0)
        # The earliest local row (2012-06-23 19:00 AKST) -> 2012-06-24 04:00 UTC.
        earliest = min(o.time_start for o in obs)
        assert earliest == datetime(2012, 6, 24, 4, 0, tzinfo=UTC)

    def test_skips_sentinel_and_unknown_plot_and_malformed(self) -> None:
        adapter = ESSDIVEAdapter(raw_dir=Path("/tmp/test_ess_dive"))
        obs = adapter.parse_to_schema(_sloan_fixture_fetch_result())
        # No -9999 values, no unknown plot, no malformed numeric.
        assert all(o.value != -9999 for o in obs)
        plot_ids = {o.extra["plot_id"] for o in obs}
        assert plot_ids == {"A1C", "A1E"}, f"unknown plot leaked in: {plot_ids}"

    def test_provenance_and_schema_fields(self) -> None:
        adapter = ESSDIVEAdapter(raw_dir=Path("/tmp/test_ess_dive"))
        obs = adapter.parse_to_schema(_sloan_fixture_fetch_result())
        for o in obs:
            assert o.variable.value == "soil_temperature"
            assert o.unit == "degC"
            assert o.obs_type.value == "point"
            assert o.provenance.source_id == "ess_dive"
            assert o.provenance.content_checksum == "ess-dive-fixture-pkg-id"
            assert o.provenance.source_url == "https://doi.org/10.5440/1121134"
            assert o.provenance.license == "CC-BY-4.0"

    def test_missing_files_raises(self, tmp_path: Path) -> None:
        adapter = ESSDIVEAdapter(raw_dir=Path("/tmp/test_ess_dive"))
        empty = FetchResult(
            dataset_id="sloan_2014_barrow_soil",
            local_path=tmp_path,  # empty dir, none of the required files exist
            bytes_downloaded=0,
            access_timestamp=datetime.now(tz=UTC),
            content_checksum="x",
            source_url="https://test.invalid",
        )
        with pytest.raises(FileNotFoundError, match="Sloan 2014 parse expects"):
            adapter.parse_to_schema(empty)


class TestParseToSchemaDispatch:
    def test_unknown_dataset_id_raises_with_pointer(self, tmp_path: Path) -> None:
        adapter = ESSDIVEAdapter(raw_dir=tmp_path)
        fake = FetchResult(
            dataset_id="some_future_dataset",
            local_path=tmp_path,
            bytes_downloaded=0,
            access_timestamp=datetime.now(tz=UTC),
            content_checksum="x",
            source_url="https://test.invalid",
        )
        with pytest.raises(NotImplementedError, match="No parse spec for ESS-DIVE"):
            adapter.parse_to_schema(fake)


# ---- opt-in live test ----


@pytest.mark.skipif(
    not os.environ.get("ESS_DIVE_TOKEN"),
    reason="ESS_DIVE_TOKEN not set; skip live ESS-DIVE download test.",
)
def test_live_sloan_2014_fetch(tmp_path: Path) -> None:
    """Opt-in: real download against ESS-DIVE prod. Requires a valid token.

    Run with: pytest tests/test_ess_dive_adapter.py::test_live_sloan_2014_fetch -v
    (the token must be exported in the shell, not just in ~/.claude/.env).
    """
    adapter = ESSDIVEAdapter(raw_dir=tmp_path)
    result = adapter.fetch("sloan_2014_barrow_soil")
    assert result.local_path.is_dir()
    assert len(result.files) >= 40  # Sloan 2014 has 47 files
    for p in result.files:
        assert p.exists()
        assert p.stat().st_size > 0
    assert result.content_checksum.startswith("ess-dive-")
