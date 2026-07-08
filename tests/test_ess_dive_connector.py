"""Tests for the ESS-DIVE connector (e2sa.data.connectors.ess_dive).

Connector behavior: token preflight + whole-package fetch with urllib.request
monkeypatched so no network is hit. The Sloan-2014 parse (adapter side) is in
test_sloan_2014_barrow_soil_adapter.py. One opt-in @pytest.mark.skipif test in
that adapter file exercises the real download when ESS_DIVE_TOKEN is set.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from e2sa.data.base import FetchResult
from e2sa.data.connector import get_connector
from e2sa.data.connectors import ess_dive
from e2sa.data.connectors.ess_dive import _require_token

DATASET = "sloan_2014_barrow_soil"


# ---- fake ESS-DIVE member node ----


def _fake_metadata(file_specs: list[dict]) -> dict:
    """JSON-LD mimicking GET /packages/doi:<DOI>."""
    return {
        "id": "ess-dive-fake-id-20260618",
        "isPublic": True,
        "dataset": {
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
    def __init__(self, body: bytes) -> None:
        self._buf = io.BytesIO(body)

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc) -> None:
        self._buf.close()

    def read(self, size: int = -1) -> bytes:
        return self._buf.read(size) if size != -1 else self._buf.read()


def _make_dispatcher(metadata: dict, file_bodies: dict[str, bytes]):
    def fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        if "/packages/doi:" in url:
            return _FakeResponse(json.dumps(metadata).encode("utf-8"))
        for name, body in file_bodies.items():
            if url.endswith(f"fake-{name}"):
                return _FakeResponse(body)
        import urllib.error

        raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b""))

    return fake_urlopen


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


# ---- registry + token ----


class TestRegistry:
    def test_ess_dive_connector_registered(self) -> None:
        from e2sa.data.connector import CONNECTOR_REGISTRY

        conn = get_connector("ess_dive", raw_root=Path("/tmp/x"))
        assert "ess_dive" in CONNECTOR_REGISTRY
        assert conn.data_center == "ess_dive"


class TestRequireToken:
    def test_missing_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ESS_DIVE_TOKEN", raising=False)
        with pytest.raises(RuntimeError, match="ESS_DIVE_TOKEN env var is not set"):
            _require_token()

    def test_present_returns_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ESS_DIVE_TOKEN", "fake-token-value")
        assert _require_token() == "fake-token-value"


# ---- fetch (mocked HTTP) ----


class TestFetch:
    def test_downloads_all_files_and_returns_files_list(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        two_file_pkg: tuple[dict, dict[str, bytes]],
    ) -> None:
        metadata, bodies = two_file_pkg
        monkeypatch.setenv("ESS_DIVE_TOKEN", "fake")
        monkeypatch.setattr(
            ess_dive.urllib.request, "urlopen", _make_dispatcher(metadata, bodies)
        )
        conn = get_connector("ess_dive", raw_root=tmp_path)
        result = conn.fetch(DATASET)

        assert isinstance(result, FetchResult)
        assert result.local_path == tmp_path / "ess_dive" / DATASET
        assert {p.name for p in result.files} == {"file_a.csv", "file_b.csv"}
        for p in result.files:
            assert p.exists() and p.stat().st_size > 0
        assert result.bytes_downloaded == sum(len(b) for b in bodies.values())
        assert result.content_checksum == "ess-dive-fake-id-20260618"
        assert result.source_url == "https://doi.org/10.5440/1121134"

    def test_idempotent_second_call_skips_redownload(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
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
            ess_dive.urllib.request, "urlopen", logging_dispatcher(metadata, bodies)
        )
        conn = get_connector("ess_dive", raw_root=tmp_path)
        conn.fetch(DATASET)
        first = len(call_log)
        assert first == 3  # 1 metadata + 2 file downloads
        conn.fetch(DATASET)
        assert len(call_log) - first == 0  # fast path: no API hits

    def test_partial_file_is_redownloaded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        two_file_pkg: tuple[dict, dict[str, bytes]],
    ) -> None:
        metadata, bodies = two_file_pkg
        monkeypatch.setenv("ESS_DIVE_TOKEN", "fake")
        monkeypatch.setattr(
            ess_dive.urllib.request, "urlopen", _make_dispatcher(metadata, bodies)
        )
        conn = get_connector("ess_dive", raw_root=tmp_path)
        result = conn.fetch(DATASET)
        result.files[0].write_bytes(b"x")  # corrupt one file
        result2 = conn.fetch(DATASET)
        assert result2.files[0].stat().st_size == len(bodies[result2.files[0].name])

    def test_fetch_works_without_token(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        two_file_pkg: tuple[dict, dict[str, bytes]],
    ) -> None:
        # Reads are open: fetch must succeed with NO token set (token is for
        # write/upload only; a bearer can break read endpoints).
        metadata, bodies = two_file_pkg
        monkeypatch.delenv("ESS_DIVE_TOKEN", raising=False)
        monkeypatch.setattr(
            ess_dive.urllib.request, "urlopen", _make_dispatcher(metadata, bodies)
        )
        conn = get_connector("ess_dive", raw_root=tmp_path)
        result = conn.fetch(DATASET)
        assert len(result.files) == 2
        assert result.content_checksum == "ess-dive-fake-id-20260618"

    def test_fast_path_skips_token_when_cache_and_files_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dataset_dir = tmp_path / "ess_dive" / DATASET
        dataset_dir.mkdir(parents=True)
        body = b"region,site\nN/A,N/A\n"
        (dataset_dir / "BEO_data.csv").write_bytes(body)
        (dataset_dir / ".essdive_package_id").write_text(json.dumps({
            "id": "ess-dive-cached-id-from-prior-run",
            "files": {"BEO_data.csv": len(body)},
        }))

        def _no_network(*args, **kwargs):
            raise AssertionError("urlopen should NOT be called when cache is warm")

        monkeypatch.setattr(ess_dive.urllib.request, "urlopen", _no_network)
        monkeypatch.delenv("ESS_DIVE_TOKEN", raising=False)
        conn = get_connector("ess_dive", raw_root=tmp_path)
        result = conn.fetch(DATASET)
        assert result.content_checksum == "ess-dive-cached-id-from-prior-run"
        assert len(result.files) == 1
        assert result.files[0].name == "BEO_data.csv"

    def test_unknown_dataset_id_fails_fast(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ESS_DIVE_TOKEN", "fake")
        conn = get_connector("ess_dive", raw_root=tmp_path)
        with pytest.raises(KeyError, match="Unknown ESS-DIVE dataset_id"):
            conn.fetch("does_not_exist")


# ---- search (mocked: text hits + per-package enrichment + bbox filter) ----


def _meta(doi: str, name: str, nw: tuple, se: tuple, start: str, end: str) -> dict:
    """Full per-package metadata JSON-LD with spatial + temporal coverage."""
    return {
        "id": f"ess-dive-{doi}",
        "dataset": {
            "@id": f"doi:{doi}",
            "name": name,
            "description": f"{name} description",
            "license": "http://creativecommons.org/licenses/by/4.0/",
            "spatialCoverage": [{
                "@type": "Place",
                "geo": [
                    {"name": "Northwest", "latitude": nw[0], "longitude": nw[1]},
                    {"name": "Southeast", "latitude": se[0], "longitude": se[1]},
                ],
            }],
            "temporalCoverage": {"startDate": start, "endDate": end},
        },
    }


def _search_dispatcher(search_payload: dict, metas: dict[str, dict]):
    def fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        if "/packages/doi:" in url:
            doi = url.split("/packages/doi:", 1)[1]
            return _FakeResponse(json.dumps(metas[doi]).encode("utf-8"))
        if "/packages?" in url:
            return _FakeResponse(json.dumps(search_payload).encode("utf-8"))
        import urllib.error
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b""))
    return fake_urlopen


class TestSearch:
    def test_bbox_coverage_filters_alaska_from_lower48_and_global(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Three text hits: a localized Alaska dataset (kept), a lower-48 dataset
        # (no overlap -> dropped), and a GLOBAL dataset whose bbox overlaps the
        # Alaska query but covers a tiny fraction of its own footprint (dropped by
        # the coverage filter, not by overlap). Only the Alaska dataset survives.
        ak_doi, lo48_doi, glob_doi = "10.5440/AK1", "10.5440/LO1", "10.5440/GLOB"
        ds = lambda doi, name, desc: {  # noqa: E731
            "viewUrl": f"https://data.ess-dive.lbl.gov/view/doi:{doi}",
            "dataset": {"@id": f"doi:{doi}", "name": name, "description": desc,
                        "providerName": "X"},
        }
        search_payload = {"total": 3, "result": [
            ds(ak_doi, "Barrow soil T", "Alaska soil temperature"),
            ds(lo48_doi, "Ohio soil T", "Ohio soil temperature"),
            ds(glob_doi, "Global root traits", "global soil temperature DB"),
        ]}
        metas = {
            ak_doi: _meta(ak_doi, "Barrow soil T", (71.35, -156.7), (71.2, -156.4),
                          "2012-06-18", "2014-08-06"),
            lo48_doi: _meta(lo48_doi, "Ohio soil T", (40.0, -83.0), (39.8, -82.8),
                            "2015-01-01", "2018-01-01"),
            # Whole-globe bbox: overlaps Alaska but coverage ~0.013 < 0.10.
            glob_doi: _meta(glob_doi, "Global root traits", (90.0, -180.0),
                            (-90.0, 180.0), "1990-01-01", "2025-01-01"),
        }
        monkeypatch.setattr(
            ess_dive.urllib.request, "urlopen", _search_dispatcher(search_payload, metas)
        )
        conn = get_connector("ess_dive", raw_root=tmp_path)
        hits = conn.search(variables=["soil_temperature"], bbox=(-170, 51, -129, 72))
        assert [h.dataset_id for h in hits] == [ak_doi]
        assert "2012-06-18" in hits[0].temporal_coverage
        assert hits[0].url.endswith(f"doi:{ak_doi}")
