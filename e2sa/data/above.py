"""NASA ABoVE data adapter via ORNL DAAC.

Uses the earthaccess library for NASA Earthdata authentication, CMR search,
and download. Starts with the STDM compilation (DOI: 10.3334/ORNLDAAC/1903),
with a config-driven registry for adding more ABoVE datasets later.
"""
from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from e2sa.data.base import BaseAdapter, DatasetInfo, FetchResult
from e2sa.schema import Observation, ObservationType, Provenance, Variable

ADAPTER_VERSION = "0.1.0"

VARIABLE_MAP = {
    "active_layer_thickness": Variable.ACTIVE_LAYER_THICKNESS,
    "alt": Variable.ACTIVE_LAYER_THICKNESS,
    "thaw_depth": Variable.ACTIVE_LAYER_THICKNESS,
    "soil_temperature": Variable.SOIL_TEMPERATURE,
    "soil_temp": Variable.SOIL_TEMPERATURE,
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
    extra: dict[str, Any] = field(default_factory=dict)


DATASET_REGISTRY: dict[str, ABoVEDatasetConfig] = {
    "stdm_1903": ABoVEDatasetConfig(
        dataset_id="above_stdm_1903",
        doi="10.3334/ORNLDAAC/1903",
        name="ABoVE STDM Soil Moisture and ALT Compilation",
        description="352,719 observations (206K ALT measurements via probing and GPR), 2008-2020",
        variables=["active_layer_thickness", "volumetric_water_content", "soil_temperature"],
        format="CSV",
        spatial_coverage="Alaska and NWT",
        temporal_coverage="2008-2020",
    ),
}


class ABoVEAdapter(BaseAdapter):
    source_id = "above"
    adapter_version = ADAPTER_VERSION

    def __init__(self, raw_dir: Path = Path("data/raw")) -> None:
        super().__init__(raw_dir)
        self._earthaccess_logged_in = False

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
            )
            for cfg in DATASET_REGISTRY.values()
        ]

    def fetch(self, dataset_id: str = "above_stdm_1903") -> FetchResult:
        registry_key = _find_registry_key(dataset_id)
        cfg = DATASET_REGISTRY[registry_key]
        dataset_dir = self.raw_dir / registry_key

        existing = list(dataset_dir.glob("*.csv")) if dataset_dir.exists() else []
        if existing:
            main_file = existing[0]
            checksum = _sha256(main_file)
            return FetchResult(
                dataset_id=dataset_id,
                local_path=main_file,
                bytes_downloaded=main_file.stat().st_size,
                access_timestamp=datetime.fromtimestamp(
                    main_file.stat().st_mtime, tz=timezone.utc
                ),
                content_checksum=checksum,
                source_url=f"https://doi.org/{cfg.doi}",
            )

        try:
            import earthaccess
        except ImportError as e:
            raise ImportError(
                "earthaccess is required for ABoVE downloads. "
                "Install with: pip install earthaccess"
            ) from e

        if not self._earthaccess_logged_in:
            earthaccess.login()
            self._earthaccess_logged_in = True

        results = earthaccess.search_data(doi=cfg.doi)
        if not results:
            raise RuntimeError(f"No granules found for DOI {cfg.doi}")

        dataset_dir.mkdir(parents=True, exist_ok=True)
        downloaded = earthaccess.download(results, local_path=str(dataset_dir))

        if not downloaded:
            raise RuntimeError(f"Download returned no files for {cfg.doi}")

        main_file = Path(downloaded[0])
        return FetchResult(
            dataset_id=dataset_id,
            local_path=main_file,
            bytes_downloaded=sum(Path(f).stat().st_size for f in downloaded),
            access_timestamp=datetime.now(tz=timezone.utc),
            content_checksum=_sha256(main_file),
            source_url=f"https://doi.org/{cfg.doi}",
        )

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

                    date_str = row.get("Date", row.get("date", row.get("DATE/TIME", "")))
                    dt = _parse_date(date_str.strip()) if date_str else None

                    depth_str = row.get("Depth_cm", row.get("depth_cm", ""))
                    try:
                        depth_m = float(depth_str.strip()) / 100.0 if depth_str.strip() else None
                    except ValueError:
                        depth_m = None

                    unit = "cm" if mapped_var == Variable.ACTIVE_LAYER_THICKNESS else "degC"
                    if mapped_var == Variable.VOLUMETRIC_WATER_CONTENT:
                        unit = "fraction"

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
                            source_id="above",
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


def _find_registry_key(dataset_id: str) -> str:
    for key, cfg in DATASET_REGISTRY.items():
        if cfg.dataset_id == dataset_id or key == dataset_id:
            return key
    raise KeyError(f"Unknown dataset_id: {dataset_id}. Available: {list(DATASET_REGISTRY)}")


def _map_variable(col_name: str) -> Variable | None:
    normalized = col_name.lower().strip().replace(" ", "_")
    return VARIABLE_MAP.get(normalized)


def _parse_date(date_str: str) -> datetime | None:
    if not date_str:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%m/%d/%Y", "%Y"):
        try:
            return datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()
