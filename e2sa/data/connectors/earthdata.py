"""NASA Earthdata connector (CMR / ORNL DAAC, via the earthaccess library).

Access layer for NASA Earthdata-hosted datasets (ABoVE / ORNL DAAC, NSIDC, and
future SMAP / Sentinel). Unlike the open centers, Earthdata **requires auth**:
`earthaccess.login(strategy="netrc")` reads `~/.netrc` (machine
`urs.earthdata.nasa.gov`) non-interactively (or `EARTHDATA_USERNAME` /
`EARTHDATA_PASSWORD`), per `docs/design/05`. `earthaccess` is an optional dependency
(`pip install 'e2sa[earthdata]'`, or bare `pip install earthaccess`), imported lazily
in `fetch`.

`fetch` searches CMR by DOI and downloads the granule(s) into
`raw_root/earthdata/<dataset_id>/`; per-dataset parsing lives in the adapters.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

from e2sa.data.base import DatasetInfo, FetchResult
from e2sa.data.connector import BaseConnector, register_connector

# Registered dataset_id slug -> Earthdata/DAAC DOI.
_KNOWN_DATASETS: dict[str, str] = {
    "above_stdm": "10.3334/ORNLDAAC/1903",
}


@register_connector
class EarthdataConnector(BaseConnector):
    """Connector for NASA Earthdata (auth required; earthaccess-backed)."""

    data_center: ClassVar[str] = "earthdata"

    def search(
        self,
        *,
        variables: list[str] | None = None,
        bbox: tuple[float, float, float, float] | None = None,
        time_range: tuple[str, str] | None = None,
    ) -> list[DatasetInfo]:
        # Documented stub: CMR collection search (earthaccess.search_datasets,
        # filtered by keyword / bbox / temporal) is a future enhancement. The
        # known-DOI fetch path below does not depend on it.
        return []

    def fetch(self, dataset_id: str) -> FetchResult:
        doi = _KNOWN_DATASETS.get(dataset_id)
        if doi is None:
            known = ", ".join(sorted(_KNOWN_DATASETS)) or "(none)"
            raise KeyError(
                f"Unknown Earthdata dataset_id: {dataset_id!r}. Known: {known}."
            )

        source_url = f"https://doi.org/{doi}"
        pkg_dir = self.raw_root / self.data_center / dataset_id

        # On-disk fast-path (idempotency): a CSV already on disk is reused.
        existing = sorted(pkg_dir.glob("*.csv")) if pkg_dir.exists() else []
        if existing:
            return _result(dataset_id, existing[0], source_url)

        try:
            import earthaccess  # noqa: PLC0415
        except ImportError as e:
            raise ImportError(
                "earthaccess is required for Earthdata downloads. "
                "Install with: pip install 'e2sa[earthdata]'"
            ) from e

        # Non-interactive auth (docs/design/05): ~/.netrc machine
        # urs.earthdata.nasa.gov, or EARTHDATA_USERNAME/PASSWORD.
        earthaccess.login(strategy="netrc")
        results = earthaccess.search_data(doi=doi)
        if not results:
            raise RuntimeError(
                f"No Earthdata granules found for DOI {doi} ({dataset_id})."
            )
        pkg_dir.mkdir(parents=True, exist_ok=True)
        downloaded = earthaccess.download(results, local_path=str(pkg_dir))
        if not downloaded:
            raise RuntimeError(f"Earthdata download returned no files for {doi}.")

        _capture_metadata(results, pkg_dir)
        csvs = sorted(p for p in (Path(f) for f in downloaded) if p.suffix == ".csv")
        main = csvs[0] if csvs else Path(downloaded[0])
        return _result(dataset_id, main, source_url)


def _result(dataset_id: str, main_file: Path, source_url: str) -> FetchResult:
    """Single-file FetchResult (local_path = the main downloaded file)."""
    return FetchResult(
        dataset_id=dataset_id,
        local_path=main_file,
        bytes_downloaded=main_file.stat().st_size,
        access_timestamp=datetime.fromtimestamp(main_file.stat().st_mtime, tz=UTC),
        content_checksum=_sha256(main_file),
        source_url=source_url,
    )


def _capture_metadata(results: list, pkg_dir: Path) -> None:
    """Save the granules' UMM metadata as the native record (best-effort)."""
    try:
        umm = [getattr(r, "umm", None) or dict(r) for r in results]
        (pkg_dir / "metadata.json").write_text(
            json.dumps(umm, indent=2, ensure_ascii=False, default=str) + "\n"
        )
    except (OSError, TypeError, ValueError):
        return


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()
