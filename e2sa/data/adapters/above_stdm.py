"""NASA ABoVE data adapter via ORNL DAAC.

Uses the earthaccess library for NASA Earthdata authentication, CMR search,
and download. Starts with the STDM compilation (DOI: 10.3334/ORNLDAAC/1903),
with a config-driven registry for adding more ABoVE datasets later.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from e2sa.data.base import BaseAdapter, DatasetInfo, FetchResult
from e2sa.harmonize.units import convert
from e2sa.schema import Observation, ObservationType, Provenance, Variable

ADAPTER_VERSION = "0.1.0"

VARIABLE_MAP = {
    "active_layer_thickness": Variable.ACTIVE_LAYER_THICKNESS,
    "alt": Variable.ACTIVE_LAYER_THICKNESS,
    "thaw_depth": Variable.ACTIVE_LAYER_THICKNESS,
    "volumetric_water_content": Variable.VOLUMETRIC_WATER_CONTENT,
    "vwc": Variable.VOLUMETRIC_WATER_CONTENT,
    "soil_moisture": Variable.VOLUMETRIC_WATER_CONTENT,
}


@dataclass
class ABoVEDatasetConfig:
    dataset_id: str
    doi: str
    name: str
    description: str
    variables: list[str]
    format: str
    spatial_coverage: str
    temporal_coverage: str
    citation: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


# Citation is the official ORNL DAAC citation from the dataset landing page
# (https://doi.org/10.3334/ORNLDAAC/1903), copied verbatim. Do not paraphrase or
# synthesize a citation; if the real one is unknown, leave it None.
_CITATION_1903 = (
    "Schaefer, K., Clayton, L. K., Battaglia, M. J., Bourgeau-Chavez, L. L., "
    "Chen, R. H., Chen, A. C., Chen, J., Bakian-Dogaheh, K., Douglas, T. A., "
    "Grelick, S. E., Iwahana, G., Jafarov, E., Liu, L., Ludwig, S., "
    "Michaelides, R. J., Moghaddam, M., Natali, S., Panda, S. K., "
    "Parsekian, A. D., … Zhao, Y. (2021). ABoVE: Soil Moisture and Active "
    "Layer Thickness in Alaska and NWT, Canada, 2008-2020 (Version 1). ORNL "
    "Distributed Active Archive Center. https://doi.org/10.3334/ORNLDAAC/1903"
)

DATASET_REGISTRY: dict[str, ABoVEDatasetConfig] = {
    "stdm_1903": ABoVEDatasetConfig(
        dataset_id="above_stdm",
        doi="10.3334/ORNLDAAC/1903",
        name="ABoVE: Soil Moisture and Active Layer Thickness in Alaska and NWT, Canada, 2008-2020",
        description=(
            "Field measurements of active layer thickness and soil moisture "
            "(volumetric water content) across Alaska and NWT, Canada, 2008-2020."
        ),
        variables=["active_layer_thickness", "volumetric_water_content"],
        format="CSV",
        spatial_coverage="Alaska and NWT, Canada",
        temporal_coverage="2008-2020",
        citation=_CITATION_1903,
    ),
}


class ABoVEAdapter(BaseAdapter):
    source_id = "above_stdm"
    adapter_version = ADAPTER_VERSION
    data_center = "earthdata"
    # Derived from VARIABLE_MAP so it cannot drift from what the adapter maps.
    serves = frozenset(VARIABLE_MAP.values())

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
                license="NASA Earthdata (free, requires login)",
                citation=cfg.citation,
            )
            for cfg in DATASET_REGISTRY.values()
        ]

    def parse_to_schema(self, fetch_result: FetchResult) -> list[Observation]:
        path = fetch_result.local_path
        if path.suffix.lower() == ".csv":
            return self._parse_csv(fetch_result)
        raise NotImplementedError(f"Format {path.suffix} not yet supported. Add a handler.")

    def _parse_csv(self, fetch_result: FetchResult) -> list[Observation]:
        observations: list[Observation] = []

        with open(fetch_result.local_path, encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader):
                try:
                    lat = float(row.get("Latitude", row.get("latitude", "")).strip())
                    lon = float(row.get("Longitude", row.get("longitude", "")).strip())
                except (ValueError, AttributeError):
                    continue

                row_depth = _depth_m(row)

                for col_name, raw_val in row.items():
                    if not raw_val or not col_name:
                        continue
                    mapped_var = _map_variable(col_name)
                    if mapped_var is None:
                        continue

                    try:
                        value = float(raw_val.strip())
                    except (ValueError, AttributeError):
                        continue

                    # -999 is the dataset's missing-value sentinel (most rows carry
                    # it for the variable they do not measure). Real ALT (cm), VWC
                    # (percent), and depth (cm) are all non-negative. Filter the
                    # sentinel on the raw value, before any unit conversion below.
                    if value < 0:
                        continue

                    date_str = row.get("Date", row.get("date", row.get("DATE/TIME", "")))
                    dt = _parse_date(date_str.strip()) if date_str else None

                    # ALT is a thickness, not a point measurement at a depth; the
                    # depth_top/depth_bottom interval belongs to the soil-moisture row.
                    depth_m = (
                        None if mapped_var == Variable.ACTIVE_LAYER_THICKNESS else row_depth
                    )

                    # Emit canonical units (docs/design/06; schema.CANONICAL_UNITS):
                    # ALT cm -> m, VWC percent -> 1. The source reports VWC in percent
                    # (median ~47); storing it as a "fraction" was the VWC bug. The only
                    # mapped variables are ALT and VWC. Genuine >100% sensor errors become
                    # >1.0 and are caught downstream by QC, never pre-filtered here.
                    if mapped_var == Variable.ACTIVE_LAYER_THICKNESS:
                        value, unit = convert(value, "cm", "m"), "m"
                    else:  # VOLUMETRIC_WATER_CONTENT
                        value, unit = convert(value, "percent", "1"), "1"

                    obs = Observation(
                        obs_id=f"above_{fetch_result.dataset_id}_{i:06d}_{col_name}",
                        obs_type=ObservationType.POINT,
                        variable=mapped_var,
                        value=value,
                        unit=unit,
                        latitude=lat,
                        longitude=lon,
                        depth_m=depth_m,
                        time_start=dt,
                        time_end=dt,
                        qc_flags=[],
                        provenance=Provenance(
                            source_id=self.source_id,
                            source_url=fetch_result.source_url,
                            access_timestamp=fetch_result.access_timestamp,
                            content_checksum=fetch_result.content_checksum,
                            adapter_version=ADAPTER_VERSION,
                        ),
                        extra={
                            "site": row.get("Site", row.get("site", "")),
                            "dataset_id": fetch_result.dataset_id,
                        },
                    )
                    observations.append(obs)

        return observations


def _map_variable(col_name: str) -> Variable | None:
    normalized = col_name.lower().strip().replace(" ", "_")
    return VARIABLE_MAP.get(normalized)


def _nonneg_cm(s: str) -> float | None:
    """Parse a centimetre value, treating blanks and the -999 sentinel as missing."""
    s = s.strip()
    try:
        v = float(s)
    except ValueError:
        return None
    return v if v >= 0 else None  # -999 missing-value sentinel -> None


def _depth_m(row: dict) -> float | None:
    """Measurement depth in metres, or None.

    The real STDM CSV gives a `depth_top`/`depth_bottom` interval (cm) for
    soil-moisture rows; use its midpoint. Fall back to a single `Depth_cm` column
    if present. ALT rows (and sentinel -999 rows) have no usable depth -> None.
    """
    top = _nonneg_cm(row.get("depth_top") or row.get("Depth_top") or "")
    bot = _nonneg_cm(row.get("depth_bottom") or row.get("Depth_bottom") or "")
    if top is not None and bot is not None:
        return (top + bot) / 2.0 / 100.0
    if top is not None:
        return top / 100.0
    single = _nonneg_cm(row.get("Depth_cm") or row.get("depth_cm") or "")
    return single / 100.0 if single is not None else None


def _parse_date(date_str: str) -> datetime | None:
    if not date_str:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%m/%d/%Y", "%Y"):
        try:
            return datetime.strptime(date_str, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None
