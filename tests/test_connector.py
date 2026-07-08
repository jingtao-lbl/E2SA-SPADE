"""Tests for the connector layer (Option C, docs/design/15-16).

A connector owns auth + search + fetch for one data center. These cover the
registry/get_connector plumbing and the Arctic Data Center connector's DataONE
search + BagIt package download, with `urllib.request.urlopen` monkeypatched so
no network is hit. Two opt-in @pytest.mark.skipif tests exercise the real
DataONE Solr search + the real ~59 MB Kanevskiy download when E2E_LIVE=1.

The adapter side (parse/serves/EIC + fetch-via-delegation) is in
test_kanevskiy_adapter.py.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import urllib.error
import zipfile
from pathlib import Path

import pytest

from e2sa.data.base import DatasetInfo, FetchResult
from e2sa.data.connector import (
    CONNECTOR_REGISTRY,
    BaseConnector,
    get_connector,
)
from e2sa.data.connectors import arctic_data_center
from e2sa.data.connectors.arctic_data_center import ArcticDataCenterConnector

FIXTURE = Path(__file__).parent / "fixtures" / "kanevskiy_pkg"
KANEVSKIY_SLUG = "kanevskiy_2024_cryostratigraphy"
KANEVSKIY_DOI = "10.18739/A2H12V928"
DATA_CENTER = "arctic_data_center"  # raw layout: raw_root/<data_center>/<dataset_id>/


# ---- fake DataONE member node (Solr + packages endpoints) ----


class _FakeResponse:
    """Context-manager response wrapper that mimics urllib.response."""

    def __init__(self, body: bytes) -> None:
        self._buf = io.BytesIO(body)

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc) -> None:
        self._buf.close()

    def read(self, size: int = -1) -> bytes:
        return self._buf.read(size) if size != -1 else self._buf.read()


def _bagit_zip(wrap_dir: str | None = None) -> bytes:
    """A minimal valid BagIt package zip (optionally wrapped in a top folder)."""
    prefix = f"{wrap_dir}/" if wrap_dir else ""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(prefix + "bagit.txt", "BagIt-Version: 0.97\n")
        zf.writestr(prefix + "data/Itkillik_River_July_2019.csv", "title\n\nh\n")
        zf.writestr(prefix + "manifest-md5.txt", "0  data/Itkillik_River_July_2019.csv\n")
    return buf.getvalue()


def _dispatcher(*, zip_bytes: bytes | None = None, solr_docs: list[dict] | None = None):
    """urlopen replacement: serves the Solr resourceMap + a package zip."""

    def fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        if "/query/solr/" in url:
            docs = (
                solr_docs
                if solr_docs is not None
                else [{"resourceMap": [f"resource_map_doi:{KANEVSKIY_DOI}"]}]
            )
            return _FakeResponse(json.dumps({"response": {"docs": docs}}).encode())
        if "/packages/" in url:
            return _FakeResponse(zip_bytes if zip_bytes is not None else _bagit_zip())
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b""))

    return fake_urlopen


# ---- registry plumbing ----


class TestRegistry:
    def test_arctic_data_center_registered(self) -> None:
        assert "arctic_data_center" in CONNECTOR_REGISTRY
        assert CONNECTOR_REGISTRY["arctic_data_center"] is ArcticDataCenterConnector

    def test_get_connector_returns_instance(self, tmp_path: Path) -> None:
        conn = get_connector("arctic_data_center", raw_root=tmp_path)
        assert isinstance(conn, BaseConnector)
        assert isinstance(conn, ArcticDataCenterConnector)
        assert conn.raw_root == tmp_path

    def test_unknown_data_center_raises_key_error(self) -> None:
        with pytest.raises(KeyError):
            get_connector("not_a_real_data_center")


# ---- fetch ----


class TestFetch:
    def test_unknown_dataset_id_raises_key_error(self, tmp_path: Path) -> None:
        conn = get_connector("arctic_data_center", raw_root=tmp_path)
        with pytest.raises(KeyError):
            conn.fetch("not_a_real_dataset")

    def test_on_disk_package_is_verified_not_redownloaded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A valid package already on disk must NOT trigger any network call.
        pkg = tmp_path / DATA_CENTER / KANEVSKIY_SLUG
        shutil.copytree(FIXTURE, pkg)

        def boom(*a, **k):
            raise AssertionError("urlopen should not be called for an on-disk package")

        monkeypatch.setattr(arctic_data_center.urllib.request, "urlopen", boom)
        conn = get_connector("arctic_data_center", raw_root=tmp_path)
        result = conn.fetch(KANEVSKIY_SLUG)
        assert isinstance(result, FetchResult)
        assert result.local_path == pkg
        assert result.bytes_downloaded > 0
        assert "10.18739/A2H12V928" in result.source_url

    @pytest.mark.parametrize("wrap_dir", [None, "Kanevskiy_2024"])
    def test_live_download_extracts_and_verifies(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, wrap_dir: str | None
    ) -> None:
        # Both zip layouts: bag at the root, and bag wrapped in a top folder.
        monkeypatch.setattr(
            arctic_data_center.urllib.request,
            "urlopen",
            _dispatcher(zip_bytes=_bagit_zip(wrap_dir)),
        )
        conn = get_connector("arctic_data_center", raw_root=tmp_path)
        result = conn.fetch(KANEVSKIY_SLUG)

        pkg = tmp_path / DATA_CENTER / KANEVSKIY_SLUG
        assert (pkg / "bagit.txt").exists()
        assert (pkg / "data").is_dir()
        assert result.local_path == pkg
        assert len(result.files) >= 3
        # No leftover temp artifacts beside the package (zip/extract cleaned up).
        siblings = {p.name for p in pkg.parent.iterdir()}
        assert siblings == {KANEVSKIY_SLUG}

    def test_download_failure_falls_back_to_manual_instructions(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fail(*a, **k):
            raise urllib.error.URLError("no network")

        monkeypatch.setattr(arctic_data_center.urllib.request, "urlopen", fail)
        conn = get_connector("arctic_data_center", raw_root=tmp_path)
        with pytest.raises(FileNotFoundError) as exc_info:
            conn.fetch(KANEVSKIY_SLUG)
        msg = str(exc_info.value)
        assert "10.18739/A2H12V928" in msg
        assert "bagit.txt" in msg


# ---- search ----


class TestSearch:
    def test_maps_solr_docs_to_dataset_info(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        docs = [
            {
                "id": f"doi:{KANEVSKIY_DOI}",
                "title": "Cryostratigraphy and ground-ice content",
                "abstract": "Per-borehole excess ice content.",
                "westBoundCoord": -169.0,
                "southBoundCoord": 60.0,
                "eastBoundCoord": -70.0,
                "northBoundCoord": 74.0,
                "beginDate": "2018-01-01T00:00:00Z",
                "endDate": "2023-01-01T00:00:00Z",
            }
        ]
        monkeypatch.setattr(
            arctic_data_center.urllib.request,
            "urlopen",
            _dispatcher(solr_docs=docs),
        )
        conn = get_connector("arctic_data_center", raw_root=tmp_path)
        hits = conn.search(variables=["ground_ice_content"], bbox=(-169, 60, -141, 74))
        assert len(hits) == 1
        di = hits[0]
        assert isinstance(di, DatasetInfo)
        assert di.dataset_id == KANEVSKIY_DOI
        assert "ground-ice" in di.name
        assert di.url.endswith(f"doi:{KANEVSKIY_DOI}")
        assert "2018" in di.temporal_coverage


# ---- opt-in live tests (real DataONE member node) ----


@pytest.mark.skipif(
    not os.environ.get("E2E_LIVE"),
    reason="live DataONE search; set E2E_LIVE=1 to run",
)
def test_live_search_finds_kanevskiy(tmp_path: Path) -> None:
    conn = get_connector("arctic_data_center", raw_root=tmp_path)
    hits = conn.search(
        variables=["ground ice content"],
        bbox=(-169.0, 60.0, -141.0, 74.0),
        time_range=("2017-01-01", "2024-01-01"),
        rows=15,
    )
    assert any(KANEVSKIY_DOI in h.dataset_id for h in hits)


@pytest.mark.skipif(
    not os.environ.get("E2E_LIVE"),
    reason="downloads the real ~59 MB Kanevskiy package; set E2E_LIVE=1 to run",
)
def test_live_fetch_downloads_kanevskiy(tmp_path: Path) -> None:
    conn = get_connector("arctic_data_center", raw_root=tmp_path)
    result = conn.fetch(KANEVSKIY_SLUG)
    pkg = tmp_path / DATA_CENTER / KANEVSKIY_SLUG
    assert (pkg / "bagit.txt").exists()
    assert len(list((pkg / "data").glob("*.csv"))) == 22
    assert result.bytes_downloaded > 50_000_000
