"""Tests for the PGC connector (e2sa.data.connectors.pgc).

ArcticDEM strips: geocell-listing + per-strip HEAD-size + download with
urllib.request monkeypatched so no network is hit. The raster/feature parse
(adapter side) lives in test_arcticdem_strips_adapter.py. One opt-in
@pytest.mark.skipif(E2E_LIVE) test exercises the real PGC listing + a capped
download.
"""
from __future__ import annotations

import io
import os
from pathlib import Path

import pytest

from e2sa.data.base import DatasetInfo, FetchResult
from e2sa.data.connector import get_connector
from e2sa.data.connectors import pgc

DATASET = "arcticdem_strips"
GEOCELL = "n69w151"

# Two fake strip tarballs (bodies stand in for .tar.gz bytes).
_STRIPS = {
    "SETSM_s2s041_W1W1_20110410_A_B_2m_lsf_seg7.tar.gz": b"fake-tarball-one" * 4,
    "SETSM_s2s041_WV03_20170428_C_D_2m_lsf_seg1.tar.gz": b"fake-tarball-two-longer" * 8,
}


def _listing_html(names: list[str]) -> bytes:
    """Apache directory index: each strip listed twice (icon + filename link)."""
    rows = []
    for n in names:
        rows.append(f'<img src="/icons/compressed.gif"> <a href="{n}">{n}</a>')
        rows.append(f'<a href="{n}">{n}</a> 2026-06-30 12:00 63M')
    # Decoy non-strip links that must NOT be picked up.
    rows.append('<a href="?C=N;O=D">Name</a>')
    rows.append('<a href="/elev/dem/setsm/ArcticDEM/strips/s2s041/2m/">Parent</a>')
    return ("<html><body>" + "\n".join(rows) + "</body></html>").encode("utf-8")


class _FakeResponse:
    def __init__(self, body: bytes = b"", headers: dict | None = None) -> None:
        self._buf = io.BytesIO(body)
        self.headers = headers or {}

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc) -> None:
        self._buf.close()

    def read(self, size: int = -1) -> bytes:
        return self._buf.read(size) if size != -1 else self._buf.read()


def _make_dispatcher(strips: dict[str, bytes], call_log: list[str] | None = None):
    """urlopen replacement: serves the geocell listing, per-strip HEAD sizes,
    and strip bodies. Records 'GET <url>' / 'HEAD <url>' if call_log is given."""

    def fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        method = req.get_method() if hasattr(req, "get_method") else "GET"
        if call_log is not None:
            call_log.append(f"{method} {url}")
        if method == "HEAD":
            name = url.rsplit("/", 1)[-1]
            size = len(strips.get(name, b""))
            return _FakeResponse(headers={"Content-Length": str(size)})
        if url.endswith(f"/{GEOCELL}/"):
            return _FakeResponse(_listing_html(list(strips)))
        name = url.rsplit("/", 1)[-1]
        if name in strips:
            return _FakeResponse(strips[name])
        import urllib.error
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b""))

    return fake_urlopen


# ---- registry ----


class TestRegistry:
    def test_pgc_connector_registered(self) -> None:
        from e2sa.data.connector import CONNECTOR_REGISTRY

        conn = get_connector("pgc", raw_root=Path("/tmp/x"))
        assert "pgc" in CONNECTOR_REGISTRY
        assert conn.data_center == "pgc"


# ---- fetch (mocked HTTP) ----


class TestFetch:
    def test_downloads_all_strips_and_returns_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            pgc.urllib.request, "urlopen", _make_dispatcher(_STRIPS)
        )
        conn = get_connector("pgc", raw_root=tmp_path)
        result = conn.fetch(DATASET)

        assert isinstance(result, FetchResult)
        assert result.local_path == tmp_path / "pgc" / DATASET
        assert {p.name for p in result.files} == set(_STRIPS)
        for p in result.files:
            assert p.exists() and p.stat().st_size > 0
            assert p.parent.name == GEOCELL  # raw/pgc/arcticdem_strips/n69w151/<file>
        assert result.bytes_downloaded == sum(len(b) for b in _STRIPS.values())
        assert result.source_url == "https://doi.org/10.7910/DVN/C98DVS"
        # metadata.txt written (self-describing) but NOT catalogued as a data file.
        meta = result.local_path / "metadata.txt"
        assert meta.exists()
        assert "NSF-OPP" in meta.read_text()
        assert meta not in result.files

    def test_decoy_links_not_treated_as_strips(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            pgc.urllib.request, "urlopen", _make_dispatcher(_STRIPS)
        )
        conn = get_connector("pgc", raw_root=tmp_path)
        result = conn.fetch(DATASET)
        # The ?C=N sort link and the Parent dir link must not be fetched.
        assert all(p.name.endswith(".tar.gz") for p in result.files)
        assert len(result.files) == len(_STRIPS)

    def test_idempotent_second_call_skips_download(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        call_log: list[str] = []
        monkeypatch.setattr(
            pgc.urllib.request, "urlopen", _make_dispatcher(_STRIPS, call_log)
        )
        conn = get_connector("pgc", raw_root=tmp_path)
        conn.fetch(DATASET)
        gets_first = [c for c in call_log if c.startswith("GET") and c.endswith(".tar.gz")]
        assert len(gets_first) == len(_STRIPS)  # each strip downloaded once
        call_log.clear()
        conn.fetch(DATASET)
        # Second run: HEADs to compare sizes, but no body GETs (sizes match on disk).
        gets_second = [c for c in call_log if c.startswith("GET") and c.endswith(".tar.gz")]
        assert gets_second == []

    def test_partial_strip_is_redownloaded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            pgc.urllib.request, "urlopen", _make_dispatcher(_STRIPS)
        )
        conn = get_connector("pgc", raw_root=tmp_path)
        result = conn.fetch(DATASET)
        truncated = result.files[0]
        truncated.write_bytes(b"x")  # wrong size -> must re-download
        result2 = conn.fetch(DATASET)
        name = truncated.name
        assert (result2.local_path / GEOCELL / name).stat().st_size == len(_STRIPS[name])

    def test_max_strips_caps_per_geocell(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            pgc.urllib.request, "urlopen", _make_dispatcher(_STRIPS)
        )
        conn = get_connector("pgc", raw_root=tmp_path)
        result = conn.fetch(DATASET, max_strips=1)
        assert len(result.files) == 1

    def test_unknown_dataset_id_fails_fast(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conn = get_connector("pgc", raw_root=tmp_path)
        with pytest.raises(KeyError, match="Unknown PGC dataset_id"):
            conn.fetch("does_not_exist")

    def test_listing_failure_raises_with_manual_instructions(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(req, timeout=None):
            import urllib.error
            raise urllib.error.URLError("network down")

        monkeypatch.setattr(pgc.urllib.request, "urlopen", boom)
        conn = get_connector("pgc", raw_root=tmp_path)
        with pytest.raises(FileNotFoundError, match="Manual download"):
            conn.fetch(DATASET)


# ---- search (documented stub over the single known product) ----


class TestSearch:
    def test_returns_dataset_for_elevation_arctic_query(
        self, tmp_path: Path
    ) -> None:
        conn = get_connector("pgc", raw_root=tmp_path)
        hits = conn.search(
            variables=["elevation"], bbox=(-170, 51, -129, 72),
            time_range=("2015-01-01", "2020-01-01"),
        )
        assert len(hits) == 1
        assert isinstance(hits[0], DatasetInfo)
        assert hits[0].dataset_id == DATASET
        assert "C98DVS" in (hits[0].url or "")

    def test_non_elevation_variable_excluded(self, tmp_path: Path) -> None:
        conn = get_connector("pgc", raw_root=tmp_path)
        assert conn.search(variables=["soil_temperature"]) == []

    def test_bbox_south_of_arctic_excluded(self, tmp_path: Path) -> None:
        conn = get_connector("pgc", raw_root=tmp_path)
        # Whole bbox south of 60 N (lower-48): no ArcticDEM coverage.
        assert conn.search(bbox=(-100, 30, -90, 45)) == []

    def test_pre_2010_timerange_excluded(self, tmp_path: Path) -> None:
        conn = get_connector("pgc", raw_root=tmp_path)
        assert conn.search(time_range=("2000-01-01", "2005-01-01")) == []

    def test_no_filters_returns_dataset(self, tmp_path: Path) -> None:
        conn = get_connector("pgc", raw_root=tmp_path)
        hits = conn.search()
        assert len(hits) == 1 and hits[0].dataset_id == DATASET


# ---- opt-in live ----


@pytest.mark.skipif(
    not os.environ.get("E2E_LIVE"), reason="set E2E_LIVE=1 for live PGC fetch"
)
def test_live_listing_and_capped_fetch(tmp_path: Path) -> None:
    conn = get_connector("pgc", raw_root=tmp_path)
    result = conn.fetch(DATASET, max_strips=1)
    assert len(result.files) == 1
    assert result.files[0].name.endswith(".tar.gz")
    assert result.files[0].stat().st_size > 0
