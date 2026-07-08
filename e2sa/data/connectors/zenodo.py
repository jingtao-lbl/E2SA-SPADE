"""Zenodo connector (general-purpose research-data repository).

Access layer for Zenodo (https://zenodo.org). A dataset is a record holding one or
more files; SPADE datasets here are downloaded as a single archive (e.g. the Alaska
Permafrost Thaw Database ZIP). Open access for public records, no auth. The record's
JSON metadata (citation, description, license, keywords) is captured from the open
Zenodo REST API (`/api/records/<id>`) as the native metadata.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

from e2sa.data.base import DatasetInfo, FetchResult
from e2sa.data.connector import BaseConnector, register_connector

USER_AGENT = "e2sa-spade/0.1 (LBNL NGEE-Arctic)"
_RECORD_RE = re.compile(r"/records/(\d+)")

# Registered dataset_id slug -> the Zenodo file download URL.
_KNOWN_DATASETS: dict[str, str] = {
    "webb_2026_alaska_thaw_db": (
        "https://zenodo.org/records/17494851/files/"
        "ArcticWebb/Alaska_Permafrost_Thaw_Database-v2.0.0.zip?download=1"
    ),
}


def _record_id(url: str) -> str | None:
    m = _RECORD_RE.search(url)
    return m.group(1) if m else None


@register_connector
class ZenodoConnector(BaseConnector):
    """Connector for Zenodo (single-archive downloads by record)."""

    data_center: ClassVar[str] = "zenodo"

    def search(
        self,
        *,
        variables: list[str] | None = None,
        bbox: tuple[float, float, float, float] | None = None,
        time_range: tuple[str, str] | None = None,
    ) -> list[DatasetInfo]:
        # Documented stub: Zenodo has a REST search API (/api/records?q=...);
        # wiring it is a future enhancement. The known-record fetch path below
        # does not depend on it.
        return []

    def fetch(self, dataset_id: str) -> FetchResult:
        file_url = _KNOWN_DATASETS.get(dataset_id)
        if file_url is None:
            known = ", ".join(sorted(_KNOWN_DATASETS)) or "(none)"
            raise KeyError(
                f"Unknown Zenodo dataset_id: {dataset_id!r}. Known: {known}."
            )

        rec = _record_id(file_url)
        landing = f"https://zenodo.org/records/{rec}" if rec else file_url
        pkg_dir = self.raw_root / self.data_center / dataset_id
        out_path = pkg_dir / f"{dataset_id}.zip"

        # On-disk fast-path (idempotency).
        if out_path.exists():
            return self._result(dataset_id, out_path, landing)

        pkg_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._download(file_url, out_path)
        except (urllib.error.URLError, OSError) as exc:
            raise FileNotFoundError(
                f"Could not download Zenodo dataset {dataset_id!r} from {file_url} "
                f"({exc}). Download it manually from {landing} into {out_path}, "
                f"then re-run."
            ) from exc

        # Capture the record's native metadata (open Zenodo API), best-effort.
        if rec:
            self._capture_metadata(rec, pkg_dir)
        return self._result(dataset_id, out_path, landing)

    def _download(self, url: str, target: Path) -> None:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=300) as r, open(target, "wb") as f:  # noqa: S310
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)

    def _capture_metadata(self, record_id: str, pkg_dir: Path) -> None:
        url = f"https://zenodo.org/api/records/{record_id}"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
                meta = json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError):
            return
        (pkg_dir / "metadata.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False) + "\n"
        )

    def _result(self, dataset_id: str, out_path: Path, landing: str) -> FetchResult:
        """Single-file FetchResult (local_path is the archive; `files` empty)."""
        return FetchResult(
            dataset_id=dataset_id,
            local_path=out_path,
            bytes_downloaded=out_path.stat().st_size,
            access_timestamp=datetime.fromtimestamp(out_path.stat().st_mtime, tz=UTC),
            content_checksum=_sha256(out_path),
            source_url=landing,
        )


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()
