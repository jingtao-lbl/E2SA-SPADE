"""Tests for the Zenodo connector (e2sa.data.connectors.zenodo).

Connector behavior: single-archive download by dataset_id + on-disk fast-path +
native-metadata capture, with `urllib.request.urlopen` monkeypatched (no network).
The alaska-thaw-db parse is in test_adapters.py; the adapter delegates fetch here.
One opt-in E2E_LIVE test hits the real Zenodo download.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pytest

from e2sa.data.base import FetchResult
from e2sa.data.connector import CONNECTOR_REGISTRY, get_connector
from e2sa.data.connectors import zenodo

DATASET = "webb_2026_alaska_thaw_db"
_ZIP = b"PK\x03\x04 fake zip bytes"
_REC_META = {"id": 17494851, "metadata": {"title": "Alaska Permafrost Thaw Database"}}


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._buf = io.BytesIO(body)

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc) -> None:
        self._buf.close()

    def read(self, size: int = -1) -> bytes:
        return self._buf.read(size) if size != -1 else self._buf.read()


def _dispatcher(log: list | None = None):
    def fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        if log is not None:
            log.append(url)
        if "/api/records/" in url:
            return _FakeResponse(json.dumps(_REC_META).encode("utf-8"))
        return _FakeResponse(_ZIP)
    return fake_urlopen


class TestRegistry:
    def test_zenodo_connector_registered(self, tmp_path: Path) -> None:
        conn = get_connector("zenodo", raw_root=tmp_path)
        assert "zenodo" in CONNECTOR_REGISTRY
        assert conn.data_center == "zenodo"


class TestFetch:
    def test_downloads_archive_and_native_metadata(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(zenodo.urllib.request, "urlopen", _dispatcher())
        conn = get_connector("zenodo", raw_root=tmp_path)
        result = conn.fetch(DATASET)

        pkg = tmp_path / "zenodo" / DATASET
        assert isinstance(result, FetchResult)
        assert result.local_path == pkg / f"{DATASET}.zip"
        assert result.local_path.read_bytes() == _ZIP
        assert result.source_url == "https://zenodo.org/records/17494851"
        # native metadata captured from the open Zenodo API
        assert (pkg / "metadata.json").exists()
        assert json.loads((pkg / "metadata.json").read_text())["id"] == 17494851

    def test_idempotent_second_call_skips_redownload(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        log: list = []
        monkeypatch.setattr(zenodo.urllib.request, "urlopen", _dispatcher(log=log))
        conn = get_connector("zenodo", raw_root=tmp_path)
        conn.fetch(DATASET)
        first = len(log)  # 1 download + 1 metadata GET
        conn.fetch(DATASET)  # fast-path
        assert len(log) == first  # no further requests

    def test_unknown_dataset_id_raises_key_error(self, tmp_path: Path) -> None:
        conn = get_connector("zenodo", raw_root=tmp_path)
        with pytest.raises(KeyError, match="Unknown Zenodo dataset_id"):
            conn.fetch("not_a_real_dataset")

    def test_download_failure_falls_back_to_manual_instructions(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import urllib.error

        def fail(*a, **k):
            raise urllib.error.URLError("no network")

        monkeypatch.setattr(zenodo.urllib.request, "urlopen", fail)
        conn = get_connector("zenodo", raw_root=tmp_path)
        with pytest.raises(FileNotFoundError, match="Download it manually"):
            conn.fetch(DATASET)


@pytest.mark.skipif(
    not os.environ.get("E2E_LIVE"),
    reason="live Zenodo download; set E2E_LIVE=1 to run",
)
def test_live_zenodo_download(tmp_path: Path) -> None:
    conn = get_connector("zenodo", raw_root=tmp_path)
    result = conn.fetch(DATASET)
    assert result.local_path.exists()
    assert result.bytes_downloaded > 0
    assert (tmp_path / "zenodo" / DATASET / "metadata.json").exists()
