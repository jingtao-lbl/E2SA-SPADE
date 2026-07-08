"""Arctic Data Center connector (NSF Arctic Data Center / DataONE).

Access layer for the NSF Arctic Data Center, a DataONE member node. Owns
search + fetch for every dataset archived there; per-dataset parsing lives in
the dataset adapters (e.g. `e2sa/data/kanevskiy.py`).

The center is open (no auth). `search` queries the DataONE Solr index on the
member node; `fetch` downloads the dataset's whole BagIt package as a zip from
the DataONE `packages` endpoint, extracts it into
`raw_root/arctic_data_center/<dataset_id>/`, and verifies the BagIt layout.
`fetch` is idempotent (an already-extracted package on disk is verified, not
re-downloaded) and falls back to explicit manual-download instructions only if
the live download fails (e.g. no network).
"""
from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

from e2sa.data.base import DatasetInfo, FetchResult
from e2sa.data.connector import BaseConnector, register_connector

#: DataONE v2 member-node base URL for the NSF Arctic Data Center.
MN_BASE_URL = "https://arcticdata.io/metacat/d1/mn/v2"
#: DataONE object-format id for a BagIt 0.97 data package zip.
BAGIT_FORMAT_ID = "application/bagit-097"
#: Arctic Data Center mints resource-map PIDs as `resource_map_<metadata pid>`.
_RESOURCE_MAP_PREFIX = "resource_map_"
USER_AGENT = "e2sa-spade/0.1 (LBNL NGEE-Arctic)"

# Known dataset_id -> landing DOI URL. Maps a registered slug to its source DOI
# (the stable identifier; the slug is SPADE's local name). `fetch` resolves the
# slug to its package through this; `search` discovers *new* datasets by DOI.
_KNOWN_DATASETS: dict[str, str] = {
    "kanevskiy_2024_cryostratigraphy": "https://doi.org/10.18739/A2H12V928",
    # TSP North America annual ground-temperature series (2016-2025); one DOI per
    # year. See e2sa/data/adapters/tsp_north_america_ground_temperature.py.
    "tsp_2016_ground_temperature": "https://doi.org/10.18739/A2W08WG7P",
    "tsp_2017_ground_temperature": "https://doi.org/10.18739/A20R9M42C",
    "tsp_2018_ground_temperature": "https://doi.org/10.18739/A2HX15Q8V",
    "tsp_2019_ground_temperature": "https://doi.org/10.18739/A20R9M47S",
    "tsp_2020_ground_temperature": "https://doi.org/10.18739/A2MW28G02",
    "tsp_2021_ground_temperature": "https://doi.org/10.18739/A29G5GF7P",
    "tsp_2022_ground_temperature": "https://doi.org/10.18739/A2H70823W",
    "tsp_2023_ground_temperature": "https://doi.org/10.18739/A2DB7VR9J",
    "tsp_2024_ground_temperature": "https://doi.org/10.18739/A2X05XF3W",
    "tsp_2025_ground_temperature": "https://doi.org/10.18739/A2SF2MD87",
}


def _doi_from_url(doi_url: str) -> str:
    """'https://doi.org/10.18739/A2H12V928' -> '10.18739/A2H12V928'."""
    return doi_url.split("doi.org/", 1)[-1].strip("/")


@register_connector
class ArcticDataCenterConnector(BaseConnector):
    """Connector for the NSF Arctic Data Center (DataONE member node)."""

    data_center: ClassVar[str] = "arctic_data_center"

    def search(
        self,
        *,
        variables: list[str] | None = None,
        bbox: tuple[float, float, float, float] | None = None,
        time_range: tuple[str, str] | None = None,
        rows: int = 25,
    ) -> list[DatasetInfo]:
        """Query the DataONE Solr index on the member node.

        `variables` are free-text terms ANDed into the full-text query. `bbox`
        is (west, south, east, north) in decimal degrees and selects datasets
        whose coverage overlaps it. `time_range` is (start, end) ISO dates and
        selects datasets whose temporal coverage overlaps it. Returns one
        DatasetInfo per metadata record; the discovered dataset is identified by
        its DOI (DatasetInfo.dataset_id + .url), since a SPADE slug is assigned
        only when an adapter is written for it.
        """
        # formatType:METADATA -> dataset records (not data files); -obsoletedBy:*
        # -> current versions only (drop superseded entries in each DOI chain).
        q_terms = ["formatType:METADATA", "-obsoletedBy:*"]
        for term in variables or []:
            t = term.replace('_', ' ').strip()
            if t:
                q_terms.append(f'text:"{t}"')
        if bbox is not None:
            west, south, east, north = bbox
            # Coverage overlaps the query box (no-overlap is the negation).
            q_terms.append(f"eastBoundCoord:[{west} TO *]")
            q_terms.append(f"westBoundCoord:[* TO {east}]")
            q_terms.append(f"northBoundCoord:[{south} TO *]")
            q_terms.append(f"southBoundCoord:[* TO {north}]")
        if time_range is not None:
            start, end = time_range
            q_terms.append(f"endDate:[{start}T00:00:00Z TO *]")
            q_terms.append(f"beginDate:[* TO {end}T00:00:00Z]")

        params = {
            "q": " AND ".join(q_terms),
            "fl": (
                "id,title,abstract,northBoundCoord,southBoundCoord,"
                "eastBoundCoord,westBoundCoord,beginDate,endDate,formatId,"
                "rightsHolder"
            ),
            "rows": str(rows),
            "wt": "json",
        }
        docs = self._solr_query(params)
        return [_doc_to_dataset_info(d) for d in docs]

    def fetch(self, dataset_id: str) -> FetchResult:
        source_url = _KNOWN_DATASETS.get(dataset_id)
        if source_url is None:
            known = ", ".join(sorted(_KNOWN_DATASETS)) or "(none)"
            raise KeyError(
                f"Unknown Arctic Data Center dataset_id: {dataset_id!r}. "
                f"Known: {known}."
            )

        # Option C raw layout: raw_root/<data_center>/<dataset_id>/.
        pkg_root = self.raw_root / self.data_center / dataset_id

        # Idempotency: a valid package already on disk is verified, not refetched.
        if (pkg_root / "bagit.txt").exists() and (pkg_root / "data").is_dir():
            return self._fetch_result(dataset_id, pkg_root, source_url)

        # Live download of the whole BagIt package from the DataONE MN.
        try:
            self._download_and_extract(source_url, pkg_root)
        except (urllib.error.URLError, OSError, zipfile.BadZipFile) as exc:
            raise FileNotFoundError(
                f"Could not download the Arctic Data Center package for "
                f"{dataset_id!r} ({exc}). Download manually instead:\n"
                f"  1. Visit {source_url}\n"
                f"  2. Click 'Download All' (BagIt zip)\n"
                f"  3. Extract into {pkg_root} so that "
                f"{pkg_root / 'bagit.txt'} exists.\n"
                f"Then re-run."
            ) from exc

        return self._fetch_result(dataset_id, pkg_root, source_url)

    # --- live-fetch helpers ---

    def _download_and_extract(self, source_url: str, pkg_root: Path) -> None:
        """Download the BagIt package zip and extract it to pkg_root.

        Resolves the dataset DOI to its resource-map PID via Solr, GETs the
        BagIt zip from the DataONE `packages` endpoint, extracts to a temp dir,
        locates the BagIt root (the dir containing `bagit.txt`), and moves it
        into place atomically.
        """
        doi = _doi_from_url(source_url)
        rm_pid = self._resolve_resource_map(doi)

        pkg_root.parent.mkdir(parents=True, exist_ok=True)
        zip_path = pkg_root.with_suffix(".bagit.zip.partial")
        self._download_package_zip(rm_pid, zip_path)

        extract_dir = pkg_root.with_suffix(".extracting")
        if extract_dir.exists():
            _rmtree(extract_dir)
        try:
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(extract_dir)
            bag_root = _find_bag_root(extract_dir)
            if pkg_root.exists():
                _rmtree(pkg_root)
            bag_root.replace(pkg_root)
        finally:
            zip_path.unlink(missing_ok=True)
            if extract_dir.exists():
                _rmtree(extract_dir)

    def _resolve_resource_map(self, doi: str) -> str:
        """Return the resource-map PID for a dataset DOI (Solr, with fallback)."""
        docs = self._solr_query(
            {"q": f'id:"doi:{doi}"', "fl": "resourceMap", "rows": "1", "wt": "json"}
        )
        if docs:
            rm = docs[0].get("resourceMap")
            if isinstance(rm, list) and rm:
                return rm[0]
            if isinstance(rm, str) and rm:
                return rm
        # ADC convention when Solr omits the field: resource_map_doi:<doi>.
        return f"{_RESOURCE_MAP_PREFIX}doi:{doi}"

    def _download_package_zip(self, rm_pid: str, target: Path) -> None:
        """Stream-download the BagIt package zip for a resource-map PID."""
        url = (
            f"{MN_BASE_URL}/packages/"
            f"{urllib.parse.quote(BAGIT_FORMAT_ID, safe='')}/"
            f"{urllib.parse.quote(rm_pid, safe='')}"
        )
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=600) as r, open(target, "wb") as f:  # noqa: S310
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)

    def _solr_query(self, params: dict[str, str]) -> list[dict[str, Any]]:
        """Run a Solr query against the member node, return the doc list."""
        url = f"{MN_BASE_URL}/query/solr/?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
            payload = json.loads(r.read().decode("utf-8"))
        return payload.get("response", {}).get("docs", [])

    def _fetch_result(
        self, dataset_id: str, pkg_root: Path, source_url: str
    ) -> FetchResult:
        """Build a FetchResult from an on-disk BagIt package."""
        files: list[Path] = sorted(p for p in pkg_root.rglob("*") if p.is_file())
        total_bytes = sum(p.stat().st_size for p in files)

        manifest = pkg_root / "manifest-md5.txt"
        if manifest.exists():
            checksum = hashlib.sha256(manifest.read_bytes()).hexdigest()
        else:
            # Fallback: hash the sorted file list (paths + sizes).
            h = hashlib.sha256()
            for p in files:
                h.update(str(p.relative_to(pkg_root)).encode())
                h.update(str(p.stat().st_size).encode())
            checksum = h.hexdigest()

        return FetchResult(
            dataset_id=dataset_id,
            local_path=pkg_root,
            bytes_downloaded=total_bytes,
            access_timestamp=datetime.now(tz=UTC),
            content_checksum=checksum,
            source_url=source_url,
            files=files,
        )


def _find_bag_root(extract_dir: Path) -> Path:
    """Locate the BagIt root (dir containing bagit.txt) within an extract dir.

    DataONE zips sometimes wrap the bag in a top-level folder and sometimes
    extract the bag contents at the root; handle both by finding the shallowest
    bagit.txt.
    """
    candidates = sorted(extract_dir.rglob("bagit.txt"), key=lambda p: len(p.parts))
    if not candidates:
        raise zipfile.BadZipFile(
            f"Downloaded package has no bagit.txt under {extract_dir}."
        )
    return candidates[0].parent


def _rmtree(path: Path) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)


def _doc_to_dataset_info(doc: dict[str, Any]) -> DatasetInfo:
    """Map one Solr metadata doc to a DatasetInfo discovery candidate."""
    pid = doc.get("id", "")
    doi = pid[len("doi:"):] if pid.startswith("doi:") else pid
    landing = (
        f"https://arcticdata.io/catalog/view/{pid}" if pid.startswith("doi:") else pid
    )
    bbox = (
        doc.get("westBoundCoord"),
        doc.get("southBoundCoord"),
        doc.get("eastBoundCoord"),
        doc.get("northBoundCoord"),
    )
    spatial = (
        f"bbox W{bbox[0]} S{bbox[1]} E{bbox[2]} N{bbox[3]}"
        if all(v is not None for v in bbox)
        else "unspecified"
    )
    begin, end = doc.get("beginDate"), doc.get("endDate")
    temporal = f"{begin} to {end}" if begin and end else "unspecified"
    abstract = doc.get("abstract") or ""
    if isinstance(abstract, list):
        abstract = " ".join(abstract)
    return DatasetInfo(
        dataset_id=doi,
        name=doc.get("title", "") or doi,
        description=abstract[:500],
        variables=[],
        spatial_coverage=spatial,
        temporal_coverage=temporal,
        format="BagIt package (DataONE)",
        url=landing,
        license=None,
    )
