"""GTN-P (Global Terrestrial Network for Permafrost) borehole temperature adapter.

Downloads the PANGAEA 2025 MAGT product (DOI: 10.1594/PANGAEA.972992) and parses
borehole temperature profiles into Observation records. One row per
(borehole, depth, year) measurement.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime

from e2sa.data.base import BaseAdapter, DatasetInfo, FetchResult
from e2sa.schema import Observation, ObservationType, Provenance, Variable

PANGAEA_DOI = "10.1594/PANGAEA.972992"
PANGAEA_URL = f"https://doi.pangaea.de/{PANGAEA_DOI}?format=textfile"
DATASET_ID = "gtnp_magt"
ADAPTER_VERSION = "0.1.0"


class GTNPAdapter(BaseAdapter):
    source_id = DATASET_ID
    adapter_version = ADAPTER_VERSION
    data_center = "pangaea"
    # GROUND_TEMPERATURE is the same physical quantity as SOIL_TEMPERATURE (PI,
    # 2026-06-22); the registry's VARIABLE_EQUIVALENCE routes the two together.
    serves = frozenset({Variable.GROUND_TEMPERATURE})

    def list_available(self) -> list[DatasetInfo]:
        return [
            DatasetInfo(
                dataset_id=DATASET_ID,
                name="GTN-P MAGT Northern Hemisphere 2025 (PANGAEA)",
                description=(
                    "Mean Annual Ground Temperature at 311 stations, "
                    "23 standardized depths (0-20 m), 1980-2021"
                ),
                variables=["ground_temperature"],
                spatial_coverage="Northern Hemisphere",
                temporal_coverage="1980-2021",
                format="TSV",
                url=PANGAEA_URL,
                license="CC-BY-4.0",
                citation=(
                    "Wieczorek, Mareike; GTN-P; Lewkowicz, Antoni G; Kholodov, "
                    "Alexander L; Romanovsky, Vladimir E; Nicolsky, Dmitry; "
                    "Streletskiy, Dmitry A; Boike, Julia; Heim, Birgit; Bartsch, "
                    "Annett; Biskaborn, Boris K; Christiansen, Hanne Hvidtfeldt; "
                    "Elger, Kirsten; Irrgang, Anna Maria (2025): GTN-P: 41 years of "
                    "Mean Annual Ground Temperature (MAGT) across latitudinal and "
                    "elevational gradients in the Northern Hemisphere, v1.0 [dataset]. "
                    f"PANGAEA, https://doi.org/{PANGAEA_DOI}"
                ),
                keywords=["Mean Annual Ground Temperature", "GTN-P", "permafrost"],
            )
        ]

    def parse_to_schema(
        self,
        fetch_result: FetchResult,
        country_filter: str | None = None,
    ) -> list[Observation]:
        text = fetch_result.local_path.read_text(encoding="utf-8")
        data_lines = _skip_pangaea_header(text)
        reader = csv.DictReader(io.StringIO(data_lines), delimiter="\t")

        observations: list[Observation] = []
        for row in reader:
            # Real PANGAEA column name for this dataset is "MAGT [°C]"
            # (Mean Annual Ground Temperature). The older "Temp [°C]" /
            # "Temperature, ground, annual mean [°C]" variants are kept as
            # fallbacks for other PANGAEA exports.
            temp_str = row.get("MAGT [°C]", "").strip()
            if not temp_str:
                temp_str = row.get("Temp [°C]", "").strip()
            if not temp_str:
                temp_str = row.get("Temperature, ground, annual mean [°C]", "").strip()
            if not temp_str or temp_str == "-":
                continue

            try:
                temp_c = float(temp_str)
            except ValueError:
                continue

            try:
                lat = float(row.get("Latitude of event", row.get("Latitude", "")).strip())
                lon = float(row.get("Longitude of event", row.get("Longitude", "")).strip())
            except (ValueError, AttributeError, TypeError):
                continue

            depth_str = row.get("DEPTH, sediment/rock [m]", "").strip()
            if not depth_str:
                depth_str = row.get("Depth sed [m]", "").strip()
            try:
                depth_m = float(depth_str) if depth_str else None
            except ValueError:
                depth_m = None

            # Same OR-chained-fallback pattern as the lat/lon lookups above:
            # fixture/older schema → real 2025 PANGAEA schema.
            event = (row.get("Event label") or row.get("Event") or "").strip()
            name = row.get("Name", "").strip()
            gtnp_id = (row.get("Identification") or row.get("ID") or "").strip()
            date_str = (row.get("DATE/TIME") or row.get("Date/Time") or "").strip()
            frequency = (
                row.get("Frequency")
                or row.get("Frequency (Measurement frequency of orig...)")
                or ""
            ).strip()
            provenance_source = (row.get("Provenance/source") or row.get("Source") or "").strip()
            authors = (
                row.get("Author(s)") or row.get("Author(s) (Author of original data)") or ""
            ).strip()
            ref_orig = (
                row.get("Reference/source")
                or row.get("Reference (Reference to original data)")
                or ""
            ).strip()

            dt = _parse_date(date_str)

            # obs_id must be unique per (station, depth, time). Event label
            # alone collides across stations (the 2025 PANGAEA export reuses
            # event labels like "MAGT_06_24" for many stations), so include
            # station name + precise coords. Live evidence (2026-06-18): the
            # event-only id collapsed 4,088 input rows to 715 catalog rows.
            obs = Observation(
                obs_id=(f"gtnp_{event}_{name}_{depth_str}m_{date_str}_{lat:.4f}_{lon:.4f}"),
                obs_type=ObservationType.PROFILE,
                variable=Variable.GROUND_TEMPERATURE,
                value=temp_c,
                unit="degC",
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
                    "event_label": event,
                    "station_name": name,
                    "gtnp_id": gtnp_id,
                    "frequency": frequency,
                    "provenance_source": provenance_source,
                    "authors": authors,
                    "reference_original": ref_orig,
                },
            )
            observations.append(obs)

        return observations


def _skip_pangaea_header(text: str) -> str:
    lines = text.splitlines(keepends=True)
    data_start = 0
    in_comment = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("/*"):
            in_comment = True
        if in_comment:
            if stripped.endswith("*/"):
                in_comment = False
            continue
        data_start = i
        break
    return "".join(lines[data_start:])


def _parse_date(date_str: str) -> datetime | None:
    if not date_str:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%Y"):
        try:
            return datetime.strptime(date_str, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None
