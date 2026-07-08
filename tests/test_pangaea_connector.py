"""Tests for the PANGAEA connector (e2sa.data.connectors.pangaea).

Connector behavior: single-file TSV download by dataset_id with on-disk fast-path,
mocked `urllib.request.urlopen` (no network). The calm/gtnp parse is in
test_adapters.py; the adapters delegate `fetch` here. One opt-in E2E_LIVE test
hits the real PANGAEA DOI download.
"""
from __future__ import annotations

import io
import os
from pathlib import Path

import pytest

from e2sa.data.base import FetchResult
from e2sa.data.connector import CONNECTOR_REGISTRY, get_connector
from e2sa.data.connectors import pangaea

CALM = "calm_alt"
GTNP = "gtnp_magt"
_TSV = b"/* PANGAEA header */\nEvent\tLatitude\tALD [cm]\nX\t68.0\t42.0\n"


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._buf = io.BytesIO(body)

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc) -> None:
        self._buf.close()

    def read(self, size: int = -1) -> bytes:
        return self._buf.read(size) if size != -1 else self._buf.read()


def _dispatcher(body: bytes = _TSV, log: list | None = None):
    def fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        if log is not None:
            log.append(url)
        return _FakeResponse(body)
    return fake_urlopen


class TestRegistry:
    def test_pangaea_connector_registered(self, tmp_path: Path) -> None:
        conn = get_connector("pangaea", raw_root=tmp_path)
        assert "pangaea" in CONNECTOR_REGISTRY
        assert conn.data_center == "pangaea"


class TestFetch:
    def test_downloads_single_tsv_to_dataset_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(pangaea.urllib.request, "urlopen", _dispatcher())
        conn = get_connector("pangaea", raw_root=tmp_path)
        result = conn.fetch(CALM)

        assert isinstance(result, FetchResult)
        assert result.local_path == tmp_path / "pangaea" / CALM / f"{CALM}.tsv"
        assert result.local_path.read_bytes() == _TSV
        assert result.bytes_downloaded == len(_TSV)
        assert result.content_checksum
        assert "PANGAEA.972777" in result.source_url
        assert result.files == []  # single-file shape

    def test_both_datasets_share_one_connector(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The many-adapters-one-connector case: calm_alt + gtnp_magt both fetch
        # through the same pangaea connector, to their own dataset dirs.
        monkeypatch.setattr(pangaea.urllib.request, "urlopen", _dispatcher())
        conn = get_connector("pangaea", raw_root=tmp_path)
        r_calm = conn.fetch(CALM)
        r_gtnp = conn.fetch(GTNP)
        assert r_calm.local_path == tmp_path / "pangaea" / CALM / f"{CALM}.tsv"
        assert r_gtnp.local_path == tmp_path / "pangaea" / GTNP / f"{GTNP}.tsv"
        assert "PANGAEA.972992" in r_gtnp.source_url

    def test_idempotent_second_call_skips_redownload(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        log: list = []
        monkeypatch.setattr(pangaea.urllib.request, "urlopen", _dispatcher(log=log))
        conn = get_connector("pangaea", raw_root=tmp_path)
        conn.fetch(CALM)
        assert len(log) == 1
        conn.fetch(CALM)  # on-disk fast-path
        assert len(log) == 1  # no second download

    def test_unknown_dataset_id_raises_key_error(self, tmp_path: Path) -> None:
        conn = get_connector("pangaea", raw_root=tmp_path)
        with pytest.raises(KeyError, match="Unknown PANGAEA dataset_id"):
            conn.fetch("not_a_real_dataset")

    def test_download_failure_falls_back_to_manual_instructions(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import urllib.error

        def fail(*a, **k):
            raise urllib.error.URLError("no network")

        monkeypatch.setattr(pangaea.urllib.request, "urlopen", fail)
        conn = get_connector("pangaea", raw_root=tmp_path)
        with pytest.raises(FileNotFoundError, match="Download it manually"):
            conn.fetch(CALM)


@pytest.mark.skipif(
    not os.environ.get("E2E_LIVE"),
    reason="live PANGAEA download; set E2E_LIVE=1 to run",
)
@pytest.mark.parametrize("dataset_id", [CALM, GTNP])
def test_live_pangaea_download(tmp_path: Path, dataset_id: str) -> None:
    conn = get_connector("pangaea", raw_root=tmp_path)
    result = conn.fetch(dataset_id)
    assert result.local_path.exists()
    assert result.bytes_downloaded > 0
