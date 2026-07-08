"""PGC connector (Polar Geospatial Center, University of Minnesota).

Access layer for the ArcticDEM time-stamped DEM **strips** (SETSM s2s041, 2 m)
hosted by PGC. Owns search + whole-geocell fetch for the center; per-dataset
parsing lives in the dataset adapter (`e2sa/data/adapters/arcticdem_strips.py`).

Shape (why this connector differs from the others). ArcticDEM is ONE DOI
(`10.7910/DVN/C98DVS`) but a pan-Arctic *tiled* archive: you fetch a spatial
**subset** (the 1-degree geocells over an AOI), not a single package. The
`BaseConnector.fetch(dataset_id)` contract carries no bbox, so `fetch` takes an
additive `geocells` kwarg defaulting to the SPADE North Slope cell already
inspected (`n69w151`). Deriving the geocell set from a request bbox at S0 intake
is the proper upstream path (same gap as the ESS-DIVE "bbox at intake" note,
root TODO "generate the run config from a question"); it is a documented stopgap
here, not invented.

API (confirmed live 2026-06-30, no auth):
- Listing: GET https://data.pgc.umn.edu/elev/dem/setsm/ArcticDEM/strips/s2s041/2m/<geocell>/
    OPEN (no auth; HTTP 200). Plain Apache directory index; each strip is a direct
    `href="SETSM_..._2m_lsf_seg<N>.tar.gz"` anchor (listed twice per row: the icon
    link + the filename link, so dedupe).
- File bytes: GET <listing_url>/<filename>  -- open. Content-Length is the
    idempotency key (local size == remote size -> skip).
- The PGC interactive portal + S3 STAC surface MOSAIC tiles only, never strips
    (source card "Access path note"); the HTTP file browser is the strips path.
- Cloudflare blocks `Python-urllib/*`; always send a real User-Agent.

Auth model: open download, no token (CC-BY 4.0 + mandatory NSF-OPP
acknowledgement, recorded in the source card / metadata bundle, not a credential).
"""
from __future__ import annotations

import hashlib
import logging
import re
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

from e2sa.data.base import DatasetInfo, FetchResult
from e2sa.data.connector import BaseConnector, register_connector

logger = logging.getLogger(__name__)

STRIPS_BASE = (
    "https://data.pgc.umn.edu/elev/dem/setsm/ArcticDEM/strips/s2s041/2m"
)
USER_AGENT = "e2sa-spade/0.1 (LBNL SPADE; permafrost research)"

#: Mandatory PGC acknowledgement (non-optional, per the source card / license).
PGC_ACKNOWLEDGEMENT = (
    "DEMs provided by the Polar Geospatial Center under NSF-OPP awards 1043681, "
    "1559691, 1542736, 1810976, and 2129685."
)

# Known dataset_id -> source DOI (the strips product, V4.1 on Harvard Dataverse).
# The slug is SPADE's local name; the DOI lives in provenance/source_url. Note PGC's
# acknowledgement page misprints the strips DOI as the mosaic's 3VDC4W; C98DVS is the
# authoritative strips DOI from the Dataverse record (source card "Citation" note).
_KNOWN_DATASETS: dict[str, str] = {
    "arcticdem_strips": "10.7910/DVN/C98DVS",
}

# Stopgap AOI: the 1-degree geocell over the Kanevskiy AF-1..AF-4 boreholes
# (~69.25 N / -150.73 W, North Slope), the cell inspected + staged 2026-06-25.
# Replace with bbox->geocell selection at S0 intake (see module docstring).
_DEFAULT_GEOCELLS: tuple[str, ...] = ("n69w151",)

# Matches a strip tarball filename in the Apache directory listing.
_STRIP_RE = re.compile(r'href="(SETSM_[^"]+_2m[^"]*\.tar\.gz)"')


@register_connector
class PGCConnector(BaseConnector):
    """Connector for the Polar Geospatial Center (ArcticDEM strips)."""

    data_center: ClassVar[str] = "pgc"

    def search(
        self,
        *,
        variables: list[str] | None = None,
        bbox: tuple[float, float, float, float] | None = None,
        time_range: tuple[str, str] | None = None,
    ) -> list[DatasetInfo]:
        """Return the ArcticDEM strips dataset when the filter matches.

        PGC is a static file tree with no dataset-search API, so this is a
        documented stub over the single known product rather than a live query.
        ArcticDEM strips serve surface ELEVATION pan-Arctic (all land north of
        ~60 N, all of Alaska), 2010-present. The dataset is returned unless the
        filter clearly excludes it:
          - `variables`: matched on elevation/terrain/DEM terms (best-effort,
            since `serves` is the adapter's authoritative emit-contract).
          - `bbox`: any box intersecting the pan-Arctic footprint passes; a box
            wholly south of 60 N is dropped.
          - `time_range`: any range overlapping 2010-present passes.
        Geocell/strip selection happens at fetch time, not here.
        """
        if variables:
            terms = " ".join(variables).lower()
            if not any(
                k in terms
                for k in ("elev", "terrain", "dem", "topograph", "deformation", "subsid")
            ):
                return []
        if bbox is not None and bbox[3] < 60.0:  # north edge south of 60 N
            return []
        if time_range is not None:
            try:
                start_year = int(time_range[1][:4])
                if start_year < 2010:
                    return []
            except (ValueError, IndexError):
                pass
        doi = _KNOWN_DATASETS["arcticdem_strips"]
        return [
            DatasetInfo(
                dataset_id="arcticdem_strips",
                name="ArcticDEM - Strips, Version 4.1 (SETSM s2s041, 2 m)",
                description=(
                    "Time-stamped 2 m stereo-photogrammetric DEM strips (per-"
                    "acquisition, EPSG:3413, WGS84 ellipsoidal). Pan-Arctic terrain "
                    "elevation; repeat-pass strips also support derived surface "
                    "deformation."
                ),
                variables=["surface_elevation"],
                spatial_coverage="Pan-Arctic (all land north of ~60 N, all of Alaska)",
                temporal_coverage="2010-present (per-acquisition timestamps)",
                format="Cloud-Optimized GeoTIFF in .tar.gz strip bundles",
                url=f"https://doi.org/{doi}",
                license="CC-BY-4.0 (with mandatory PGC NSF-OPP acknowledgement)",
                citation=(
                    "Porter, C., et al. 2022. ArcticDEM - Strips, Version 4.1. "
                    f"Harvard Dataverse, V1. https://doi.org/{doi}. "
                    f"{PGC_ACKNOWLEDGEMENT}"
                ),
            )
        ]

    def fetch(
        self,
        dataset_id: str,
        *,
        geocells: tuple[str, ...] | None = None,
        max_strips: int | None = None,
    ) -> FetchResult:
        """Download ArcticDEM strip tarballs for the AOI geocells.

        `geocells` defaults to the SPADE North Slope cell (`n69w151`); pass an
        explicit set for another AOI (bbox->geocell selection at intake is the
        upstream fix, see module docstring). `max_strips` caps the strips fetched
        PER geocell for sampling/tests; None (default) fetches the geocell's full
        strip set -- this can be many GB, so the count + the cap are logged (no
        silent caps). Idempotent: a strip already on disk at the remote
        Content-Length is skipped, so manually-staged tarballs are reused.
        """
        if dataset_id not in _KNOWN_DATASETS:
            known = ", ".join(sorted(_KNOWN_DATASETS)) or "(none)"
            raise KeyError(
                f"Unknown PGC dataset_id: {dataset_id!r}. Known: {known}."
            )
        doi = _KNOWN_DATASETS[dataset_id]
        source_url = f"https://doi.org/{doi}"
        cells = geocells or _DEFAULT_GEOCELLS

        dataset_dir = self.raw_root / self.data_center / dataset_id
        dataset_dir.mkdir(parents=True, exist_ok=True)

        downloaded: list[Path] = []
        total_bytes = 0
        inventory: list[tuple[str, int]] = []  # (geocell/name, size) for the checksum
        for geocell in cells:
            cell_dir = dataset_dir / geocell
            cell_dir.mkdir(parents=True, exist_ok=True)
            listing_url = f"{STRIPS_BASE}/{geocell}/"
            try:
                strip_names = _list_geocell_strips(listing_url)
            except (urllib.error.URLError, OSError) as exc:
                raise FileNotFoundError(
                    f"Could not list PGC geocell {geocell} at {listing_url}: {exc}. "
                    f"Manual download: browse {listing_url} and place the "
                    f"*.tar.gz strips in {cell_dir}. DOI {source_url}."
                ) from exc
            if max_strips is not None and len(strip_names) > max_strips:
                logger.warning(
                    "PGC %s: capping geocell %s at %d of %d strips (max_strips); "
                    "the rest are skipped",
                    dataset_id, geocell, max_strips, len(strip_names),
                )
                strip_names = strip_names[:max_strips]
            else:
                logger.info(
                    "PGC %s: geocell %s has %d strips to reconcile",
                    dataset_id, geocell, len(strip_names),
                )

            for name in strip_names:
                file_url = f"{listing_url}{name}"
                target = cell_dir / name
                remote_size = _remote_size(file_url)
                if (
                    target.exists()
                    and remote_size is not None
                    and target.stat().st_size == remote_size
                ):
                    logger.info("PGC %s: %s already on disk, skipping", geocell, name)
                else:
                    _download_file(file_url, target)
                size = target.stat().st_size
                downloaded.append(target)
                total_bytes += size
                inventory.append((f"{geocell}/{name}", size))

        # Capture the source's native context so the folder is self-describing
        # (the per-strip mdf.txt metadata is inside each tarball; this records the
        # product-level provenance the connector knows). Written but NOT returned in
        # `files`, so it is not catalogued as a data file.
        _write_native_metadata(dataset_dir, doi, source_url, cells, inventory)

        # Package fingerprint: a hash of the (path, size) inventory. Cheap on the
        # fast-path (no re-hashing GB of rasters); changes if any strip's size
        # changes. Per-strip sha256 is a provenance refinement (TODO).
        checksum = _inventory_checksum(inventory)

        return FetchResult(
            dataset_id=dataset_id,
            local_path=dataset_dir,
            bytes_downloaded=total_bytes,
            access_timestamp=datetime.now(tz=UTC),
            content_checksum=checksum,
            source_url=source_url,
            files=downloaded,
        )


def _list_geocell_strips(listing_url: str) -> list[str]:
    """Return the strip-tarball filenames in a geocell directory, deduped, sorted.

    The Apache index lists each strip twice (icon link + filename link); we dedupe
    and sort for a deterministic order.
    """
    req = urllib.request.Request(listing_url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
        html = r.read().decode("utf-8", errors="replace")
    names = {m.group(1) for m in _STRIP_RE.finditer(html)}
    return sorted(names)


def _remote_size(url: str) -> int | None:
    """Content-Length of a remote file via HEAD, or None if unavailable.

    Used as the idempotency key (local size == remote size -> skip re-download).
    Returns None when the server omits Content-Length, in which case the caller
    re-downloads to be safe.
    """
    req = urllib.request.Request(
        url, method="HEAD", headers={"User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
            length = r.headers.get("Content-Length")
    except (urllib.error.URLError, OSError):
        return None
    if length is None:
        return None
    try:
        return int(length)
    except ValueError:
        return None


def _download_file(url: str, target: Path) -> str:
    """Stream-download one tarball to target, return its sha256.

    Writes to a `.partial` sibling first and moves into place atomically on
    success, so a killed run never leaves a truncated file at the final path.
    User-Agent required to clear Cloudflare.
    """
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    h = hashlib.sha256()
    tmp = target.with_suffix(target.suffix + ".partial")
    with urllib.request.urlopen(req, timeout=600) as r, open(tmp, "wb") as f:  # noqa: S310
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
            f.write(chunk)
    tmp.replace(target)
    return h.hexdigest()


def _inventory_checksum(inventory: list[tuple[str, int]]) -> str:
    """sha256 over the sorted (path, size) inventory: a stable package fingerprint."""
    lines = "\n".join(f"{path}:{size}" for path, size in sorted(inventory))
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def _write_native_metadata(
    dataset_dir: Path,
    doi: str,
    source_url: str,
    geocells: tuple[str, ...],
    inventory: list[tuple[str, int]],
) -> None:
    """Write a product-level metadata.txt the connector knows (per-strip mdf.txt
    lives inside each tarball). Not returned in FetchResult.files."""
    lines = [
        "ArcticDEM - Strips, Version 4.1 (SETSM s2s041, 2 m)",
        f"DOI: {doi}",
        f"Source: {source_url}",
        f"Listing base: {STRIPS_BASE}/",
        f"Geocells: {', '.join(geocells)}",
        "CRS: EPSG:3413 (vertical: WGS84 ellipsoidal, meters)",
        "License: CC-BY-4.0",
        f"Acknowledgement (mandatory): {PGC_ACKNOWLEDGEMENT}",
        f"Strips: {len(inventory)}",
        "",
        "Strip inventory (path: bytes):",
        *[f"  {path}: {size}" for path, size in sorted(inventory)],
        "",
    ]
    (dataset_dir / "metadata.txt").write_text("\n".join(lines), encoding="utf-8")
