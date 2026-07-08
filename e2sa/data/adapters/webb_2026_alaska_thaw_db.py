"""Alaska Permafrost Thaw Database adapter.

Downloads the Webb et al. (2025) thaw database from Zenodo (19,540 labeled
thaw locations across Alaska) and parses into Observation records.
"""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

from e2sa.data.base import BaseAdapter, DatasetInfo, FetchResult
from e2sa.schema import Observation, ObservationType, Provenance, Variable

ZENODO_URL = (
    "https://zenodo.org/records/17494851/files/"
    "ArcticWebb/Alaska_Permafrost_Thaw_Database-v2.0.0.zip?download=1"
)
DATASET_ID = "webb_2026_alaska_thaw_db"
ADAPTER_VERSION = "0.1.0"

FEATURE_CATEGORIES = [
    "Active layer detachment",
    "Retrogressive thaw slump",
    "Thaw pond",
    "Thermoerosional gully",
    "Thermokarst",
    "Thermokarst lake",
    "Thermokarst wetland",
    "Wildfire-induced thaw",
    "Non-abrupt",
]


class AlaskaThawDBAdapter(BaseAdapter):
    source_id = DATASET_ID
    adapter_version = ADAPTER_VERSION
    data_center = "zenodo"
    serves = frozenset({Variable.THAW_EVENT_LABEL})

    def list_available(self) -> list[DatasetInfo]:
        return [
            DatasetInfo(
                dataset_id=DATASET_ID,
                name="Alaska Permafrost Thaw Database v2.0.0",
                description=(
                    "19,540 permafrost thaw and thermokarst locations across Alaska, "
                    "compiled from 44 sources (Webb et al. 2025)"
                ),
                variables=["thaw_event_label"],
                spatial_coverage="Alaska statewide, all ecoregions",
                temporal_coverage="1950-present (observation dates vary by source)",
                format="CSV (inside ZIP with GeoJSON and GeoPackage)",
                url=ZENODO_URL,
                license="CC-BY-4.0",
                citation=(
                    "Webb, H., Pierce, E., Abbott, B. W., Bowden, W. B., Chen, "
                    "Yaping, Chen, Yating, Douglas, T. A., Eklof, J. F., Euskirchen, "
                    "E. S., Langer, M., Myers-Smith, I. H., Overeem, I., Strauss, J., "
                    "Walter Anthony, K., Wang, K., Whitley, M. A., and Turetsky, "
                    "M. R. (2026). A comprehensive database of thawing permafrost "
                    "locations across Alaska: version 2.0.0. Earth System Science "
                    "Data 18:3147. https://doi.org/10.5194/essd-18-3147-2026"
                ),
                keywords=["thaw", "permafrost", "Alaska", "thermokarst"],
            )
        ]

    def parse_to_schema(self, fetch_result: FetchResult) -> list[Observation]:
        csv_text = _extract_csv_from_zip(fetch_result.local_path)
        reader = csv.DictReader(io.StringIO(csv_text))

        observations: list[Observation] = []
        for i, row in enumerate(reader):
            try:
                lat = float(row.get("Latitude", "").strip())
                lon = float(row.get("Longitude", "").strip())
            except (ValueError, AttributeError):
                continue

            feature_category = row.get("FeatureCategory", "").strip()
            thaw_type = row.get("ThawType", "").strip()
            feature_name = row.get("FeatureName", "").strip()

            category_index = (
                FEATURE_CATEGORIES.index(feature_category)
                if feature_category in FEATURE_CATEGORIES
                else -1
            )

            obs = Observation(
                obs_id=f"thawdb_{i:05d}_{lat:.3f}_{lon:.3f}",
                obs_type=ObservationType.EVENT,
                variable=Variable.THAW_EVENT_LABEL,
                value=float(category_index),
                unit="category_index",
                latitude=lat,
                longitude=lon,
                depth_m=None,
                time_start=None,
                time_end=None,
                qc_flags=[],
                provenance=Provenance(
                    source_id=self.source_id,
                    source_url=fetch_result.source_url,
                    access_timestamp=fetch_result.access_timestamp,
                    content_checksum=fetch_result.content_checksum,
                    adapter_version=ADAPTER_VERSION,
                ),
                extra={
                    "feature_name": feature_name,
                    "feature_type": row.get("FeatureType", "").strip(),
                    "feature_category": feature_category,
                    "thaw_type": thaw_type,
                    "data_source_type": row.get("DataSourceType", "").strip(),
                    "authors": row.get("Authors", "").strip(),
                    "doi": row.get("DOI", "").strip(),
                    "imagery": row.get("Imagery", "").strip(),
                    "imagery_dates": row.get("ImageryDates", "").strip(),
                    "imagery_resolution_m": row.get("ImageryResolution_meters", "").strip(),
                },
            )
            observations.append(obs)

        return observations


MAIN_CSV_SUFFIX = "Alaska_Permafrost_Thaw_Database_v2.0.0.csv"


def _extract_csv_from_zip(zip_path: Path) -> str:
    """Extract the main v2.0.0 thaw-database CSV from the ZIP archive.

    The Zenodo zip bundles four CSVs (v1.0.0 and v2.0.0, each as the main
    thaw database plus a TopographicVariables companion). We target the
    main v2.0.0 file by exact-suffix match, not just `.endswith('.csv')`,
    because alphabetical-first would pick the v1.0.0 topo variant.

    The file is encoded as Windows-1252 (cp1252) not UTF-8 (publication
    metadata fields contain en-dashes, smart quotes, etc. exported from
    R or Excel). Try UTF-8 first to remain future-proof, fall back to
    cp1252 if it fails.
    """
    with zipfile.ZipFile(zip_path) as zf:
        candidates = [n for n in zf.namelist() if n.endswith(MAIN_CSV_SUFFIX)]
        if not candidates:
            raise FileNotFoundError(f"No file matching '*{MAIN_CSV_SUFFIX}' in {zip_path}")
        if len(candidates) > 1:
            raise RuntimeError(
                f"Multiple matches for '*{MAIN_CSV_SUFFIX}' in {zip_path}: {candidates}"
            )
        raw = zf.read(candidates[0])
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("cp1252")
