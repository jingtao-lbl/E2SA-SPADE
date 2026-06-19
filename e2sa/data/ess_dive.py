"""ESS-DIVE Dataset API adapter (whole-package fetch + index handoff).

ESS-DIVE archives NGEE-Arctic and many other DOE BER datasets. Packages
are bundles of many files (data CSVs, dictionaries, FLMD, PDF user-file),
so `fetch` downloads the WHOLE package once and `index_package` (see
`e2sa.data.indexing`) then walks the resulting directory and registers
every file and variable in the DuckDB catalog. Per-variable parsing into
Observation records is deferred to a per-dataset parse spec.

API (confirmed live 2026-06-18):
- Metadata: GET https://api.ess-dive.lbl.gov/packages/doi:<DOI>
    Headers: Authorization: bearer <JWT>, User-Agent: <non-default>.
    Returns JSON-LD; file list at `dataset.distribution[]` with entries
    {contentUrl, encodingFormat, identifier, name, contentSize (KB)}.
- File bytes: GET <contentUrl>  (DataONE Member Node /object/<pid>)
    No auth needed for public packages. User-Agent required (Cloudflare).
- Cloudflare WAF blocks `Python-urllib/*`; always send a real User-Agent.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from e2sa.data.base import BaseAdapter, DatasetInfo, FetchResult
from e2sa.schema import Observation, ObservationType, Provenance, Variable

ADAPTER_VERSION = "0.1.0"

API_BASE = "https://api.ess-dive.lbl.gov"
USER_AGENT = "e2sa-spade/0.1 (LBNL NGEE-Arctic)"
ESSDIVE_ID_CACHE_NAME = ".essdive_package_id"


@dataclass
class ESSDIVEDatasetConfig:
    dataset_id: str
    doi: str
    name: str
    description: str
    variables: list[str]
    format: str
    spatial_coverage: str
    temporal_coverage: str
    extra: dict[str, Any] = field(default_factory=dict)


DATASET_REGISTRY: dict[str, ESSDIVEDatasetConfig] = {
    "sloan_2014_barrow_soil": ESSDIVEDatasetConfig(
        dataset_id="sloan_2014_barrow_soil",
        doi="10.5440/1121134",
        name="Soil temperature, soil moisture and thaw depth, Utqiagvik (Barrow), Alaska",
        description=(
            "NGEE-Arctic Barrow Environmental Observatory soil package: "
            "soil T/moisture profiles, thaw depth, vegetation plot locations, "
            "FLMD + per-file data dictionaries + PDF user-file."
        ),
        variables=["soil_temperature", "volumetric_water_content", "thaw_depth"],
        format="CSV+PDF",
        spatial_coverage="Utqiagvik (Barrow), Alaska (EPSG:26904)",
        temporal_coverage="2012-2014",
    ),
}


class ESSDIVEAdapter(BaseAdapter):
    source_id = "ess_dive"
    adapter_version = ADAPTER_VERSION

    def list_available(self) -> list[DatasetInfo]:
        return [
            DatasetInfo(
                dataset_id=cfg.dataset_id,
                name=cfg.name,
                description=cfg.description,
                variables=cfg.variables,
                spatial_coverage=cfg.spatial_coverage,
                temporal_coverage=cfg.temporal_coverage,
                format=cfg.format,
                url=f"https://doi.org/{cfg.doi}",
                license="CC-BY-4.0 (ESS-DIVE default)",
            )
            for cfg in DATASET_REGISTRY.values()
        ]

    def fetch(self, dataset_id: str) -> FetchResult:
        cfg = _find_config(dataset_id)
        dataset_dir = self.raw_dir / cfg.dataset_id
        dataset_dir.mkdir(parents=True, exist_ok=True)
        id_cache = dataset_dir / ESSDIVE_ID_CACHE_NAME

        # Fast path: disk has every cached file at the cached size. Skip the
        # token check + API call entirely — lets re-runs and parse-only flows
        # work without a live token. The cache stores per-file sizes so disk
        # corruption (a truncated file from a killed run) still falls through
        # to the live path and re-downloads.
        if id_cache.exists():
            try:
                cached = json.loads(id_cache.read_text())
                cached_id = cached["id"]
                cached_files: dict[str, int] = cached["files"]
            except (json.JSONDecodeError, KeyError, TypeError):
                cached_id, cached_files = None, {}
            if cached_id and _all_files_match(dataset_dir, cached_files):
                paths = [dataset_dir / name for name in cached_files]
                return FetchResult(
                    dataset_id=dataset_id,
                    local_path=dataset_dir,
                    bytes_downloaded=sum(cached_files.values()),
                    access_timestamp=datetime.fromtimestamp(
                        dataset_dir.stat().st_mtime, tz=UTC
                    ),
                    content_checksum=cached_id,
                    source_url=f"https://doi.org/{cfg.doi}",
                    files=paths,
                )

        # Live path: needs the token + the API.
        token = _require_token()
        metadata = _get_package_metadata(cfg.doi, token)
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
            source_url=f"https://doi.org/{cfg.doi}",
            files=downloaded,
        )

    def parse_to_schema(self, fetch_result: FetchResult) -> list[Observation]:
        """Dispatch to the per-dataset parse spec for this fetch_result.

        Each ESS-DIVE dataset has its own internal layout (CRS, time zone,
        sentinels, column names, long-vs-wide format), so parse logic is
        per-dataset, not generic. Add a new dataset by writing
        `_parse_<dataset_id>()` and adding it to the dispatch below.
        """
        if fetch_result.dataset_id == "sloan_2014_barrow_soil":
            return _parse_sloan_2014_barrow_soil(fetch_result)
        raise NotImplementedError(
            f"No parse spec for ESS-DIVE dataset_id={fetch_result.dataset_id!r}. "
            f"Available: sloan_2014_barrow_soil. To add a parser, write a "
            f"_parse_<dataset_id>() helper and add it to parse_to_schema dispatch."
        )


def _find_config(dataset_id: str) -> ESSDIVEDatasetConfig:
    for key, cfg in DATASET_REGISTRY.items():
        if cfg.dataset_id == dataset_id or key == dataset_id:
            return cfg
    raise KeyError(
        f"Unknown ESS-DIVE dataset_id: {dataset_id}. "
        f"Available: {list(DATASET_REGISTRY)}"
    )


def _require_token() -> str:
    token = os.environ.get("ESS_DIVE_TOKEN")
    if not token:
        raise RuntimeError(
            "ESS_DIVE_TOKEN env var is not set. Regenerate at "
            "https://data.ess-dive.lbl.gov/ (Profile > Settings > "
            "Authentication Token) and export it. Tokens expire after 18 h."
        )
    return token


def _get_package_metadata(doi: str, token: str) -> dict[str, Any]:
    url = f"{API_BASE}/packages/doi:{doi}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"bearer {token}",
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(
            f"ESS-DIVE metadata API returned HTTP {e.code} for {doi}: {detail}"
        ) from e
    return json.loads(body)


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
    with urllib.request.urlopen(req, timeout=300) as r, open(tmp, "wb") as f:
        while True:
            chunk = r.read(65536)
            if not chunk:
                break
            h.update(chunk)
            f.write(chunk)
    tmp.replace(target)
    return h.hexdigest()


# --- per-dataset parse specs ---

SLOAN_30MIN_DATA = "BEO_soil_temperature_30_min_2012_2013.csv"
SLOAN_LOCATIONS = "BEO_soil_properties_vegetation_plot_locations.csv"
SLOAN_SENTINEL = "-9999"
AKST = timezone(timedelta(hours=-9))  # 30-min dd-CSV: "AKST (UTC -9 hrs)"
AKDT = timezone(timedelta(hours=-8))  # per-plot dd-CSV: "GMT-08:00"
SLOAN_PERPLOT_GLOB = "BEO_soil_additional_temperature_plot*cm_2013_2014*.csv"
_SLOAN_PERPLOT_NAME_RE = re.compile(r"plot([A-Z0-9]+)_(\d+)cm_")


def _parse_sloan_2014_barrow_soil(fetch_result: FetchResult) -> list[Observation]:
    """Parse all Sloan 2014 soil-temperature files into Observations.

    Two file shapes:
      - 30-min long file (2012-2013, AKST): one row per (plot, depth, time);
        full plot/site metadata in columns; uses sentinel -9999.
      - 35 per-plot files (2013-2014, AKDT): two columns only (datetime, temp);
        plot_id and depth are encoded in the filename.
    Both share the plot-centroid lookup from BEO_soil_properties_vegetation_plot_locations.csv
    (4 UTM corner rows per plot, centroid then reproject to WGS84).
    """
    pkg = fetch_result.local_path
    loc_csv = pkg / SLOAN_LOCATIONS
    data_csv = pkg / SLOAN_30MIN_DATA
    if not loc_csv.exists() or not data_csv.exists():
        raise FileNotFoundError(
            f"Sloan 2014 parse expects {SLOAN_LOCATIONS} and {SLOAN_30MIN_DATA} "
            f"in {pkg}, but at least one is missing. Run adapter.fetch() first."
        )

    centroids = _load_plot_centroids_epsg26904_to_wgs84(loc_csv)
    provenance = Provenance(
        source_id="ess_dive",
        source_url=fetch_result.source_url,
        access_timestamp=fetch_result.access_timestamp,
        content_checksum=fetch_result.content_checksum,
        license="CC-BY-4.0",
        adapter_version=ADAPTER_VERSION,
    )

    obs = _parse_sloan_30min(data_csv, centroids, provenance, fetch_result.dataset_id)
    obs.extend(_parse_sloan_perplot_files(pkg, centroids, provenance, fetch_result.dataset_id))
    return obs


def _parse_sloan_30min(
    data_csv: Path,
    centroids: dict[str, tuple[float, float]],
    provenance: Provenance,
    dataset_id: str,
) -> list[Observation]:
    """30-min long-format file: 2012-2013, AKST timezone, -9999 sentinel."""
    obs: list[Observation] = []
    with open(data_csv, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("region") == "N/A":  # units row
                continue
            plot_id = (row.get("plot_ID") or "").strip()
            if not plot_id or plot_id not in centroids:
                continue
            depth_raw = (row.get("depth") or "").strip()
            temp_raw = (row.get("temperature") or "").strip()
            if depth_raw == SLOAN_SENTINEL or temp_raw == SLOAN_SENTINEL:
                continue
            try:
                depth_cm = float(depth_raw)
                temp = float(temp_raw)
            except ValueError:
                continue
            try:
                local_dt = datetime.strptime(
                    f"{row['date']} {row['time']}", "%Y-%m-%d %H:%M"
                )
            except (KeyError, ValueError):
                continue
            utc_dt = local_dt.replace(tzinfo=AKST).astimezone(UTC)
            lat, lon = centroids[plot_id]

            obs.append(
                Observation(
                    obs_id=(
                        f"ess_dive_sloan_2014_30min_{plot_id}_"
                        f"{int(depth_cm)}cm_{utc_dt.strftime('%Y%m%dT%H%M%SZ')}"
                    ),
                    obs_type=ObservationType.POINT,
                    variable=Variable.SOIL_TEMPERATURE,
                    value=temp,
                    unit="degC",
                    latitude=lat,
                    longitude=lon,
                    depth_m=depth_cm / 100.0,
                    time_start=utc_dt,
                    time_end=utc_dt,
                    qc_flags=[],
                    provenance=provenance,
                    extra={
                        "dataset_id": dataset_id,
                        "plot_id": plot_id,
                        "polygon_sub_unit": row.get("polygon_sub_unit", ""),
                        "polygon_type": row.get("polygon_type", ""),
                        "area": row.get("area", ""),
                        "polygon_id": row.get("polygon_ID", ""),
                        "site": row.get("site", ""),
                        "source_file": data_csv.name,
                    },
                )
            )
    return obs


def _parse_sloan_perplot_files(
    pkg: Path,
    centroids: dict[str, tuple[float, float]],
    provenance: Provenance,
    dataset_id: str,
) -> list[Observation]:
    """35 per-plot files: 2013-2014, AKDT (GMT-08:00) timezone, no sentinel column.

    Files named BEO_soil_additional_temperature_plot{PLOT}_{DEPTH}cm_2013_2014*.csv
    where {PLOT} is e.g. 'A1C' and {DEPTH} is e.g. '5'. Two columns:
        "Date Time, GMT-08:00", "Temp, deg C"
    Format example: 2013-09-01 20:30,15.223
    """
    obs: list[Observation] = []
    for csv_path in sorted(pkg.glob(SLOAN_PERPLOT_GLOB)):
        m = _SLOAN_PERPLOT_NAME_RE.search(csv_path.name)
        if not m:
            continue
        plot_id = m.group(1)
        depth_cm = int(m.group(2))
        if plot_id not in centroids:
            continue
        lat, lon = centroids[plot_id]
        depth_m = depth_cm / 100.0

        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                time_raw = (row.get("Date Time, GMT-08:00") or "").strip()
                temp_raw = (row.get("Temp, deg C") or "").strip()
                if not time_raw or not temp_raw:
                    continue
                try:
                    temp = float(temp_raw)
                except ValueError:
                    continue
                try:
                    local_dt = datetime.strptime(time_raw, "%Y-%m-%d %H:%M")
                except ValueError:
                    continue
                utc_dt = local_dt.replace(tzinfo=AKDT).astimezone(UTC)
                obs.append(
                    Observation(
                        obs_id=(
                            f"ess_dive_sloan_2014_perplot_{plot_id}_"
                            f"{depth_cm}cm_{utc_dt.strftime('%Y%m%dT%H%M%SZ')}"
                        ),
                        obs_type=ObservationType.POINT,
                        variable=Variable.SOIL_TEMPERATURE,
                        value=temp,
                        unit="degC",
                        latitude=lat,
                        longitude=lon,
                        depth_m=depth_m,
                        time_start=utc_dt,
                        time_end=utc_dt,
                        qc_flags=[],
                        provenance=provenance,
                        extra={
                            "dataset_id": dataset_id,
                            "plot_id": plot_id,
                            "source_file": csv_path.name,
                        },
                    )
                )
    return obs


def _load_plot_centroids_epsg26904_to_wgs84(
    loc_csv: Path,
) -> dict[str, tuple[float, float]]:
    """Read corner coordinates per plot, centroid them, reproject to WGS84.

    Returns {plot_ID: (latitude, longitude)} in decimal degrees.
    Source CRS is EPSG:26904 (UTM Zone 4N, NAD83) per the project user-file.
    """
    import pyproj  # lazy: pyproj import is non-trivial

    accum: dict[str, list[tuple[float, float]]] = defaultdict(list)
    with open(loc_csv, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("region") == "N/A":  # units row
                continue
            plot_id = (row.get("plot_ID") or "").strip()
            if not plot_id or plot_id == "N/A":
                continue
            try:
                n = float(row["northing"])
                e = float(row["easting"])
            except (KeyError, ValueError):
                continue
            if n == -9999 or e == -9999:
                continue
            accum[plot_id].append((n, e))

    transformer = pyproj.Transformer.from_crs(
        "EPSG:26904", "EPSG:4326", always_xy=True
    )
    out: dict[str, tuple[float, float]] = {}
    for plot_id, pts in accum.items():
        mean_n = sum(p[0] for p in pts) / len(pts)
        mean_e = sum(p[1] for p in pts) / len(pts)
        lon, lat = transformer.transform(mean_e, mean_n)
        out[plot_id] = (lat, lon)
    return out
