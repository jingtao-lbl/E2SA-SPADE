"""Tests for the Earthdata connector (e2sa.data.connectors.earthdata).

Earthdata requires auth (earthaccess + ~/.netrc), and earthaccess is an optional
dependency, so the live download is E2E_LIVE-gated. The unit tests here cover what
is testable without earthaccess/credentials: registry, unknown-dataset KeyError,
and the on-disk fast-path. The above_stdm parse is in test_adapters.py.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from e2sa.data.base import FetchResult
from e2sa.data.connector import CONNECTOR_REGISTRY, get_connector

DATASET = "above_stdm"


class TestRegistry:
    def test_earthdata_connector_registered(self, tmp_path: Path) -> None:
        conn = get_connector("earthdata", raw_root=tmp_path)
        assert "earthdata" in CONNECTOR_REGISTRY
        assert conn.data_center == "earthdata"


class TestFetch:
    def test_unknown_dataset_id_raises_key_error(self, tmp_path: Path) -> None:
        conn = get_connector("earthdata", raw_root=tmp_path)
        with pytest.raises(KeyError, match="Unknown Earthdata dataset_id"):
            conn.fetch("not_a_real_dataset")

    def test_on_disk_fast_path_skips_auth_and_download(self, tmp_path: Path) -> None:
        # A CSV already on disk is reused without earthaccess/login/network.
        pkg = tmp_path / "earthdata" / DATASET
        pkg.mkdir(parents=True)
        csv = pkg / "above_stdm_data.csv"
        csv.write_text("site,alt\nA,42\n")
        conn = get_connector("earthdata", raw_root=tmp_path)
        result = conn.fetch(DATASET)
        assert isinstance(result, FetchResult)
        assert result.local_path == csv
        assert result.bytes_downloaded > 0
        assert "10.3334/ORNLDAAC/1903" in result.source_url


@pytest.mark.skipif(
    not os.environ.get("E2E_LIVE"),
    reason="live NASA Earthdata download; needs earthaccess + ~/.netrc; set E2E_LIVE=1",
)
def test_live_earthdata_download(tmp_path: Path) -> None:
    conn = get_connector("earthdata", raw_root=tmp_path)
    result = conn.fetch(DATASET)
    assert result.local_path.exists()
    assert result.bytes_downloaded > 0
