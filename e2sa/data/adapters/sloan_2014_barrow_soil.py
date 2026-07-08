"""Sloan 2014 Barrow soil adapter (NGEE-Arctic, via the ESS-DIVE connector).

NGEE-Arctic Barrow Environmental Observatory soil package (Sloan et al. 2014):
soil T/moisture profiles, thaw depth, vegetation plot locations, FLMD + per-file
data dictionaries + PDF user-file. ESS-DIVE DOI 10.5440/1121134.

Option C: this adapter owns parse_to_schema + `serves`; auth + search + the
whole-package fetch live in the `ess_dive` connector
(`e2sa/data/connectors/ess_dive.py`), to which `fetch` delegates.

Primary target: SOIL_TEMPERATURE. Two file shapes are parsed (see
parse_to_schema): a 30-min long file (2012-2013, AKST) and 35 per-plot files
(2013-2014, AKDT). Plot centroids come from the UTM corner-coordinate locations
file, reprojected EPSG:26904 -> WGS84.
"""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from e2sa.data.base import BaseAdapter, DatasetInfo, FetchResult
from e2sa.schema import Observation, ObservationType, Provenance, Variable

ADAPTER_VERSION = "0.1.0"

DATASET_ID = "sloan_2014_barrow_soil"
DOI = "10.5440/1121134"
DOI_URL = f"https://doi.org/{DOI}"
LICENSE = "CC-BY-4.0"
# Official citation from the ESS-DIVE dataset record (verbatim). Do not synthesize.
CITATION = (
    "Sloan V; Liebig J; Hahn M; Curtis B; Brooks J; Rogers A; Iversen C; Norby R "
    "(2014): Soil temperature, soil moisture and thaw depth, Utqiagvik (Barrow), "
    "Alaska, Ver. 1. Next-Generation Ecosystem Experiments (NGEE) Arctic. Dataset. "
    "doi:10.5440/1121134"
)

SLOAN_30MIN_DATA = "BEO_soil_temperature_30_min_2012_2013.csv"
SLOAN_LOCATIONS = "BEO_soil_properties_vegetation_plot_locations.csv"
SLOAN_SENTINEL = "-9999"
AKST = timezone(timedelta(hours=-9))  # 30-min dd-CSV: "AKST (UTC -9 hrs)"
AKDT = timezone(timedelta(hours=-8))  # per-plot dd-CSV: "GMT-08:00"
SLOAN_PERPLOT_GLOB = "BEO_soil_additional_temperature_plot*cm_2013_2014*.csv"
_SLOAN_PERPLOT_NAME_RE = re.compile(r"plot([A-Z0-9]+)_(\d+)cm_")


class Sloan2014BarrowSoilAdapter(BaseAdapter):
    """Adapter for the Sloan 2014 Barrow soil package (ESS-DIVE)."""

    source_id = DATASET_ID
    adapter_version = ADAPTER_VERSION
    data_center = "ess_dive"
    # Sloan 2014 parse currently emits soil temperature only; expand as the
    # VWC / thaw-depth columns in the package are wired in.
    serves = frozenset({Variable.SOIL_TEMPERATURE})

    def list_available(self) -> list[DatasetInfo]:
        return [
            DatasetInfo(
                dataset_id=DATASET_ID,
                name=("Soil temperature, soil moisture and thaw depth, Utqiagvik (Barrow), Alaska"),
                description=(
                    "NGEE-Arctic Barrow Environmental Observatory soil package: "
                    "soil T/moisture profiles, thaw depth, vegetation plot "
                    "locations, FLMD + per-file data dictionaries + PDF user-file."
                ),
                variables=["soil_temperature", "volumetric_water_content", "thaw_depth"],
                spatial_coverage="Utqiagvik (Barrow), Alaska (EPSG:26904)",
                temporal_coverage="2012-2014",
                format="CSV+PDF",
                url=DOI_URL,
                license="CC-BY-4.0 (ESS-DIVE default)",
                citation=CITATION,
            )
        ]

    def parse_to_schema(self, fetch_result: FetchResult) -> list[Observation]:
        """Parse all Sloan 2014 soil-temperature files into Observations.

        Two file shapes:
          - 30-min long file (2012-2013, AKST): one row per (plot, depth, time);
            full plot/site metadata in columns; uses sentinel -9999.
          - 35 per-plot files (2013-2014, AKDT): two columns only (datetime, temp);
            plot_id and depth are encoded in the filename.
        Both share the plot-centroid lookup from the locations CSV (4 UTM corner
        rows per plot, centroid then reproject to WGS84).
        """
        pkg = fetch_result.local_path
        loc_csv = pkg / SLOAN_LOCATIONS
        data_csv = pkg / SLOAN_30MIN_DATA
        if not loc_csv.exists() or not data_csv.exists():
            raise FileNotFoundError(
                f"Sloan 2014 parse expects {SLOAN_LOCATIONS} and "
                f"{SLOAN_30MIN_DATA} in {pkg}, but at least one is missing. "
                f"Run adapter.fetch() first."
            )

        centroids = _load_plot_centroids_epsg26904_to_wgs84(loc_csv)
        provenance = Provenance(
            source_id=self.source_id,
            source_url=fetch_result.source_url,
            access_timestamp=fetch_result.access_timestamp,
            content_checksum=fetch_result.content_checksum,
            license=LICENSE,
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
                local_dt = datetime.strptime(f"{row['date']} {row['time']}", "%Y-%m-%d %H:%M")
            except (KeyError, ValueError):
                continue
            utc_dt = local_dt.replace(tzinfo=AKST).astimezone(UTC)
            lat, lon = centroids[plot_id]

            obs.append(
                Observation(
                    obs_id=(
                        f"sloan_2014_barrow_soil_30min_{plot_id}_"
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
                            f"sloan_2014_barrow_soil_perplot_{plot_id}_"
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

    transformer = pyproj.Transformer.from_crs("EPSG:26904", "EPSG:4326", always_xy=True)
    out: dict[str, tuple[float, float]] = {}
    for plot_id, pts in accum.items():
        mean_n = sum(p[0] for p in pts) / len(pts)
        mean_e = sum(p[1] for p in pts) / len(pts)
        lon, lat = transformer.transform(mean_e, mean_n)
        out[plot_id] = (lat, lon)
    return out
