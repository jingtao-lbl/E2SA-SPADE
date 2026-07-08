"""ESS-DIVE connector (DOE BER data center).

Access layer for ESS-DIVE (https://ess-dive.lbl.gov), which archives NGEE-Arctic
and many other DOE BER datasets. Owns auth + search + whole-package fetch for the
center; per-dataset parsing lives in the dataset adapters (e.g. the Sloan 2014
Barrow soil adapter in `e2sa/data/adapters/sloan_2014_barrow_soil.py`).

Packages are bundles of many files (data CSVs, dictionaries, FLMD, PDF user-file),
so `fetch` downloads the WHOLE package once into
`raw_root/ess_dive/<dataset_id>/`; `index_package` then walks it and the adapter
parses on demand.

API (confirmed live 2026-06-18; re-verified open-for-read 2026-06-23):
- Search: GET https://api.ess-dive.lbl.gov/packages?text=<terms>&isPublic=true&pageSize=N
    OPEN (no auth). Returns {total, result[]} where each result has a thin
    `dataset` JSON-LD (@id=DOI, name, description, providerName) + viewUrl.
    The thin summary lacks spatial/temporal, so `search` enriches each candidate
    via the per-package metadata GET to filter by bbox / time.
- Metadata: GET https://api.ess-dive.lbl.gov/packages/doi:<DOI>
    OPEN (no auth; returns HTTP 200 without a token). Full JSON-LD:
    spatialCoverage (NW/SE GeoCoordinates), temporalCoverage, license,
    distribution[] {contentUrl, name, contentSize (KB)}.
- File bytes: GET <contentUrl>  (DataONE Member Node /object/<pid>) — open.
- Cloudflare WAF blocks `Python-urllib/*`; always send a real User-Agent.

Auth model: reads (search/metadata/download) are OPEN for public datasets and
must NOT send a bearer header (a bearer can trigger 403/404 on read endpoints,
docs/design 04 setup note). The ESS-DIVE JWT (`ESS_DIVE_TOKEN`, 18 h TTL) is for
write/upload only; `_require_token` is kept for a future publish path.
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, ClassVar

from e2sa.data.base import DatasetInfo, FetchResult
from e2sa.data.connector import BaseConnector, register_connector

API_BASE = "https://api.ess-dive.lbl.gov"
USER_AGENT = "e2sa-spade/0.1 (LBNL NGEE-Arctic)"
ESSDIVE_ID_CACHE_NAME = ".essdive_package_id"

# A dataset passes the spatial filter only if at least this fraction of its own
# bbox lies within the query bbox. Drops near-global / continental-scatter
# datasets whose bbox technically overlaps the query region but is not localized
# to it (e.g. a global root-trait DB, a multi-continent river-corridor campaign).
# Localized datasets sit at ~1.0; tune lower for broader (lower-precision) recall.
_DEFAULT_MIN_COVERAGE = 0.10

# Known dataset_id -> source DOI. Maps a registered slug to its ESS-DIVE DOI
# (the slug is SPADE's local name; the DOI lives in provenance/source_url).
# `fetch` resolves the slug through this; `search` discovers new datasets.
_KNOWN_DATASETS: dict[str, str] = {
    "sloan_2014_barrow_soil": "10.5440/1121134",
}


@register_connector
class ESSDIVEConnector(BaseConnector):
    """Connector for the ESS-DIVE data center."""

    data_center: ClassVar[str] = "ess_dive"

    def search(
        self,
        *,
        variables: list[str] | None = None,
        bbox: tuple[float, float, float, float] | None = None,
        time_range: tuple[str, str] | None = None,
        rows: int = 10,
        candidate_pool: int = 30,
        min_coverage: float = _DEFAULT_MIN_COVERAGE,
    ) -> list[DatasetInfo]:
        """Discover ESS-DIVE datasets matching the filters (open API, no token).

        `variables` are free-text terms for the full-text query. `bbox` is
        (west, south, east, north) in decimal degrees; `time_range` is
        (start, end) ISO dates. Because the search summary is thin, the top
        `candidate_pool` text hits are enriched via the per-package metadata GET,
        then filtered:
          - **spatial:** a dataset must have spatial metadata AND at least
            `min_coverage` of its own bbox inside the query bbox. This drops both
            non-overlapping datasets and near-global / continental-scatter ones
            whose bbox merely overlaps the query (precision over recall; lower
            `min_coverage` for broader recall). Datasets with no spatial metadata
            are dropped when a bbox is requested.
          - **temporal:** a dataset with temporal metadata must overlap `time_range`.
        Returns up to `rows` DatasetInfos identified by DOI.

        Relevance note (F8, 20260624a): this is open full-text search, so a text-only
        query with NO bbox is best-effort and can surface off-target hits (a shrub-cover
        study matched on "soil temperature" was seen). It is not token-gated (search is
        public; the token is for a future publish path). Pass a `bbox` to engage the
        spatial coverage filter above, which prunes such hits; relevance is further
        guarded by the human source-selection checkpoint, and known datasets bypass
        search via fetch-by-DOI. Deriving the bbox from the request at S0 intake is the
        upstream fix (see TODO "generate the run config from a question", part 3).
        """
        terms = " ".join(
            t.replace("_", " ").strip() for t in (variables or []) if t.strip()
        )
        params = {"isPublic": "true", "rowStart": "1", "pageSize": str(candidate_pool)}
        if terms:
            params["text"] = terms
        candidates = _search_packages(params)

        out: list[DatasetInfo] = []
        for c in candidates:
            doi = c.get("doi")
            if not doi:
                continue
            try:
                meta = _package_metadata(doi)
            except (urllib.error.URLError, OSError, ValueError):
                continue
            ds_bbox = _extract_bbox(meta)
            ds_time = _extract_temporal(meta)
            if bbox is not None and (
                ds_bbox is None or _bbox_coverage(bbox, ds_bbox) < min_coverage
            ):
                continue
            if time_range is not None and ds_time is not None and not _time_overlap(
                time_range, ds_time
            ):
                continue
            out.append(_meta_to_dataset_info(c, meta, ds_bbox, ds_time))
            if len(out) >= rows:
                break
        return out

    def fetch(self, dataset_id: str) -> FetchResult:
        doi = _KNOWN_DATASETS.get(dataset_id)
        if doi is None:
            known = ", ".join(sorted(_KNOWN_DATASETS)) or "(none)"
            raise KeyError(
                f"Unknown ESS-DIVE dataset_id: {dataset_id!r}. Known: {known}."
            )

        source_url = f"https://doi.org/{doi}"
        dataset_dir = self.raw_root / self.data_center / dataset_id
        dataset_dir.mkdir(parents=True, exist_ok=True)
        id_cache = dataset_dir / ESSDIVE_ID_CACHE_NAME

        # Fast path: disk has every cached file at the cached size. Skip the
        # token check + API call entirely so re-runs and parse-only flows work
        # without a live token. Per-file sizes are cached so a truncated file
        # from a killed run falls through to the live path and re-downloads.
        if id_cache.exists():
            try:
                cached = json.loads(id_cache.read_text())
                cached_id = cached["id"]
                cached_files: dict[str, int] = cached["files"]
            except (json.JSONDecodeError, KeyError, TypeError):
                cached_id, cached_files = None, {}
            if cached_id and _all_files_match(dataset_dir, cached_files):
                # Fast-path is network-free by contract; the native metadata.json
                # is written on the live download path (below), not here.
                paths = [dataset_dir / name for name in cached_files]
                return FetchResult(
                    dataset_id=dataset_id,
                    local_path=dataset_dir,
                    bytes_downloaded=sum(cached_files.values()),
                    access_timestamp=datetime.fromtimestamp(
                        dataset_dir.stat().st_mtime, tz=UTC
                    ),
                    content_checksum=cached_id,
                    source_url=source_url,
                    files=paths,
                )

        # Live path: open read (no token — reads are public; a bearer can break
        # read endpoints, see module docstring).
        metadata = _package_metadata(doi)
        # Capture the native JSON-LD metadata record so the folder is
        # self-describing (citation, abstract, coverage, license live here).
        (dataset_dir / "metadata.json").write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False) + "\n"
        )
        distribution = metadata["dataset"]["distribution"]

        downloaded: list[Path] = []
        total_bytes = 0
        for entry in distribution:
            target = dataset_dir / entry["name"]
            expected_bytes = int(round(entry["contentSize"] * 1024))
            if target.exists() and target.stat().st_size == expected_bytes:
                downloaded.append(target)
                total_bytes += target.stat().st_size
                continue
            _download_file(entry["contentUrl"], target)
            downloaded.append(target)
            total_bytes += target.stat().st_size

        # Cache package id + per-file sizes so the next fetch can fast-path.
        id_cache.write_text(json.dumps({
            "id": metadata["id"],
            "files": {p.name: p.stat().st_size for p in downloaded},
        }))

        return FetchResult(
            dataset_id=dataset_id,
            local_path=dataset_dir,
            bytes_downloaded=total_bytes,
            access_timestamp=datetime.now(tz=UTC),
            content_checksum=metadata["id"],
            source_url=source_url,
            files=downloaded,
        )


def _require_token() -> str:
    """Return the ESS-DIVE JWT (write/upload path only; reads are open).

    Kept for a future publish path. `fetch`/`search` (reads) do NOT call this —
    public reads are token-free and a bearer header can break read endpoints.
    """
    token = os.environ.get("ESS_DIVE_TOKEN")
    if not token:
        raise RuntimeError(
            "ESS_DIVE_TOKEN env var is not set. Regenerate at "
            "https://data.ess-dive.lbl.gov/ (Profile > Settings > "
            "Authentication Token) and export it. Tokens expire after 18 h."
        )
    return token


def _api_get_json(url: str) -> dict[str, Any]:
    """GET an open ESS-DIVE JSON endpoint (User-Agent only, no auth)."""
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(
            f"ESS-DIVE API returned HTTP {e.code} for {url}: {detail}"
        ) from e


def _package_metadata(doi: str) -> dict[str, Any]:
    """Full per-package metadata JSON-LD (open read, no token)."""
    return _api_get_json(f"{API_BASE}/packages/doi:{doi}")


def _search_packages(params: dict[str, str]) -> list[dict[str, Any]]:
    """Run the open ESS-DIVE package search; return thin candidate summaries.

    Each summary: {doi, name, description, view_url, provider}.
    """
    payload = _api_get_json(f"{API_BASE}/packages?{urllib.parse.urlencode(params)}")
    out: list[dict[str, Any]] = []
    for r in payload.get("result", []):
        ds = r.get("dataset", {})
        pid = ds.get("@id", "")
        doi = pid[len("doi:"):] if pid.startswith("doi:") else None
        out.append({
            "doi": doi,
            "name": ds.get("name", ""),
            "description": ds.get("description", ""),
            "view_url": r.get("viewUrl") or (f"https://doi.org/{doi}" if doi else None),
            "provider": ds.get("providerName"),
        })
    return out


def _extract_bbox(
    meta: dict[str, Any],
) -> tuple[float, float, float, float] | None:
    """(west, south, east, north) from a package's spatialCoverage geo points."""
    ds = meta.get("dataset", meta)
    sc = ds.get("spatialCoverage")
    if not sc:
        return None
    lats: list[float] = []
    lons: list[float] = []
    for place in sc if isinstance(sc, list) else [sc]:
        for g in place.get("geo", []) if isinstance(place, dict) else []:
            try:
                lats.append(float(g["latitude"]))
                lons.append(float(g["longitude"]))
            except (KeyError, TypeError, ValueError):
                continue
    if not lats or not lons:
        return None
    return (min(lons), min(lats), max(lons), max(lats))


def _extract_temporal(meta: dict[str, Any]) -> tuple[str, str] | None:
    ds = meta.get("dataset", meta)
    tc = ds.get("temporalCoverage")
    if isinstance(tc, dict) and tc.get("startDate") and tc.get("endDate"):
        return (tc["startDate"], tc["endDate"])
    return None


def _bbox_coverage(
    q: tuple[float, float, float, float], d: tuple[float, float, float, float]
) -> float:
    """Fraction of dataset bbox `d` that lies within query bbox `q` (0..1).

    0.0 when they do not overlap. A point/line dataset (zero area) that overlaps
    returns 1.0 (fully 'within' as far as its coordinates can tell). This is the
    localization signal: a global dataset overlapping a small query covers only a
    tiny fraction of its own footprint -> near 0; a dataset sitting inside the
    query -> near 1.0.
    """
    qw, qs, qe, qn = q
    dw, ds, de, dn = d
    iw, ie = max(qw, dw), min(qe, de)
    isth, inth = max(qs, ds), min(qn, dn)
    if ie <= iw or inth <= isth:
        return 0.0
    inter = (ie - iw) * (inth - isth)
    d_area = (de - dw) * (dn - ds)
    if d_area <= 1e-9:  # point / line dataset, fully overlapping
        return 1.0
    return inter / d_area


def _time_overlap(q: tuple[str, str], d: tuple[str, str]) -> bool:
    def parse(s: str) -> date | None:
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            return None
    qs, qe = parse(q[0]), parse(q[1])
    ds, de = parse(d[0]), parse(d[1])
    if qs is None or qe is None or ds is None or de is None:
        return True  # can't compare -> don't exclude
    return de >= qs and ds <= qe


def _meta_to_dataset_info(
    candidate: dict[str, Any],
    meta: dict[str, Any],
    bbox: tuple[float, float, float, float] | None,
    temporal: tuple[str, str] | None,
) -> DatasetInfo:
    ds = meta.get("dataset", meta)
    spatial = (
        f"bbox W{bbox[0]} S{bbox[1]} E{bbox[2]} N{bbox[3]}" if bbox else "unspecified"
    )
    return DatasetInfo(
        dataset_id=candidate["doi"],
        name=candidate.get("name") or ds.get("name", "") or candidate["doi"],
        description=(candidate.get("description") or "")[:500],
        variables=[],
        spatial_coverage=spatial,
        temporal_coverage=f"{temporal[0]} to {temporal[1]}" if temporal else "unspecified",
        format="ESS-DIVE package",
        url=candidate.get("view_url"),
        license=ds.get("license"),
    )


def _all_files_match(dataset_dir: Path, cached_files: dict[str, int]) -> bool:
    """Return True iff every cached (name, size) is present on disk at that size."""
    if not cached_files:
        return False
    for name, expected_size in cached_files.items():
        p = dataset_dir / name
        if not p.is_file() or p.stat().st_size != expected_size:
            return False
    return True


def _download_file(content_url: str, target: Path) -> str:
    """Stream-download one file to target, return its sha256.

    No auth on the contentUrl (DataONE MN /object/<pid>) for public packages;
    User-Agent still required to clear Cloudflare. Writes to a `.partial`
    sibling first and moves into place atomically on success.
    """
    req = urllib.request.Request(content_url, headers={"User-Agent": USER_AGENT})
    h = hashlib.sha256()
    tmp = target.with_suffix(target.suffix + ".partial")
    with urllib.request.urlopen(req, timeout=300) as r, open(tmp, "wb") as f:  # noqa: S310
        while True:
            chunk = r.read(65536)
            if not chunk:
                break
            h.update(chunk)
            f.write(chunk)
    tmp.replace(target)
    return h.hexdigest()
