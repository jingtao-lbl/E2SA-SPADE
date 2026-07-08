"""PANGAEA connector (data publisher / DOI download).

Access layer for PANGAEA (https://pangaea.de). A dataset downloads as a single
tab-separated text file from its DOI landing page (`?format=textfile`): a
`/* ... */` header block followed by the data table. Open access, no auth.

One connector backs multiple SPADE datasets (CALM ALT, GTN-P MAGT) — the
"many adapters, one connector" case. Per-dataset parsing lives in the adapters
(`e2sa/data/adapters/{calm,gtnp}.py`), which delegate `fetch` here.
"""
from __future__ import annotations

import hashlib
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

from e2sa.data.base import DatasetInfo, FetchResult
from e2sa.data.connector import BaseConnector, register_connector

USER_AGENT = "e2sa-spade/0.1 (LBNL NGEE-Arctic)"

# Registered dataset_id slug -> PANGAEA DOI (the slug is SPADE's name; the DOI
# lives in source_url/provenance).
_KNOWN_DATASETS: dict[str, str] = {
    "calm_alt": "10.1594/PANGAEA.972777",
    "gtnp_magt": "10.1594/PANGAEA.972992",
}


def _pangaea_url(doi: str) -> str:
    return f"https://doi.pangaea.de/{doi}?format=textfile"


@register_connector
class PangaeaConnector(BaseConnector):
    """Connector for PANGAEA (single-file TSV downloads by DOI)."""

    data_center: ClassVar[str] = "pangaea"

    def search(
        self,
        *,
        variables: list[str] | None = None,
        bbox: tuple[float, float, float, float] | None = None,
        time_range: tuple[str, str] | None = None,
    ) -> list[DatasetInfo]:
        # Documented stub: PANGAEA has a search API (OAI-PMH + an Elasticsearch
        # endpoint); wiring it is a future enhancement. The known-DOI fetch path
        # below does not depend on it.
        return []

    def fetch(self, dataset_id: str) -> FetchResult:
        doi = _KNOWN_DATASETS.get(dataset_id)
        if doi is None:
            known = ", ".join(sorted(_KNOWN_DATASETS)) or "(none)"
            raise KeyError(
                f"Unknown PANGAEA dataset_id: {dataset_id!r}. Known: {known}."
            )

        url = _pangaea_url(doi)
        pkg_dir = self.raw_root / self.data_center / dataset_id
        out_path = pkg_dir / f"{dataset_id}.tsv"

        # On-disk fast-path (idempotency): a TSV already on disk is reused.
        if out_path.exists():
            return self._result(dataset_id, out_path, url)

        pkg_dir.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:  # noqa: S310
                raw = r.read()
        except (urllib.error.URLError, OSError) as exc:
            raise FileNotFoundError(
                f"Could not download PANGAEA dataset {dataset_id!r} from {url} "
                f"({exc}). Download it manually (the DOI landing page -> "
                f"'Download dataset as tab-separated text') into {out_path}, then "
                f"re-run."
            ) from exc
        out_path.write_bytes(raw)
        return self._result(dataset_id, out_path, url)

    def _result(self, dataset_id: str, out_path: Path, url: str) -> FetchResult:
        """Single-file FetchResult (local_path is the TSV; `files` stays empty)."""
        _write_native_metadata(out_path)
        return FetchResult(
            dataset_id=dataset_id,
            local_path=out_path,
            bytes_downloaded=out_path.stat().st_size,
            access_timestamp=datetime.fromtimestamp(out_path.stat().st_mtime, tz=UTC),
            content_checksum=_sha256(out_path),
            source_url=url,
        )


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _write_native_metadata(tsv_path: Path) -> None:
    """Extract the PANGAEA `/* ... */` header (citation, abstract, references,
    coverage, license) from the TSV into a sibling `metadata.txt`, so the folder
    is self-describing without parsing the data file."""
    try:
        text = tsv_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    if not text.startswith("/*"):
        return
    end = text.find("*/")
    header = text[: end + 2] if end != -1 else text.split("\n\n", 1)[0]
    # encoding="utf-8" is required: PANGAEA headers carry Unicode hyphens that the
    # Windows cp1252 default cannot encode (crashed acquire on Windows; F1, 20260624a).
    (tsv_path.parent / "metadata.txt").write_text(header.strip() + "\n", encoding="utf-8")
