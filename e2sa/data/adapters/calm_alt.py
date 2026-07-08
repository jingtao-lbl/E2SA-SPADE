"""CALM (Circumpolar Active Layer Monitoring) data adapter.

Downloads the PANGAEA ALT dataset (DOI: 10.1594/PANGAEA.972777) and parses
site-average annual active layer thickness measurements into Observation records.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime

from e2sa.data.base import BaseAdapter, DatasetInfo, FetchResult
from e2sa.harmonize.units import convert
from e2sa.schema import Observation, ObservationType, Provenance, Variable

PANGAEA_DOI = "10.1594/PANGAEA.972777"
PANGAEA_URL = f"https://doi.pangaea.de/{PANGAEA_DOI}?format=textfile"
DATASET_ID = "calm_alt"
ADAPTER_VERSION = "0.1.0"


class CALMAdapter(BaseAdapter):
    source_id = DATASET_ID
    adapter_version = ADAPTER_VERSION
    data_center = "pangaea"
    serves = frozenset({Variable.ACTIVE_LAYER_THICKNESS})

    def list_available(self) -> list[DatasetInfo]:
        return [
            DatasetInfo(
                dataset_id=DATASET_ID,
                name="CALM ALT Northern Hemisphere (PANGAEA)",
                description=(
                    "Site-average annual active layer thickness, 263 time series, 1990-2024"
                ),
                variables=["active_layer_thickness"],
                spatial_coverage=(
                    "Northern Hemisphere (all stations emitted; scope to a "
                    "region downstream via RunConfig.bbox)"
                ),
                temporal_coverage="1990-2024",
                format="TSV",
                url=PANGAEA_URL,
                license="CC-BY-4.0",
                citation=(
                    "Streletskiy, Dmitry A; CALM; GTN-P; Wieczorek, Mareike; Heim, "
                    "Birgit; Bartsch, Annett (2025): GTN-P CALM: 35 years of Active "
                    "Layer Thickness (ALT) across latitudinal and elevational "
                    "gradients in the Northern Hemisphere [dataset]. PANGAEA, "
                    f"https://doi.org/{PANGAEA_DOI}"
                ),
                references=[
                    "Nelson, F.E., Shiklomanov, N.I., Nyland, K.E. (2021): Cool, "
                    "CALM, collected: the Circumpolar Active Layer Monitoring "
                    "program and network. Polar Geography 44(3), 155-166, "
                    "https://doi.org/10.1080/1088937X.2021.1988001",
                    "Westermann, S., et al. (2024): ESA Permafrost_cci active layer "
                    "thickness for the Northern Hemisphere, v4.0 [dataset]. CEDA, "
                    "https://doi.org/10.5285/D34330CE3F604E368C06D76DE1987CE5",
                ],
                keywords=["Active Layer Thickness", "CALM", "GTN-P", "ESA CCI"],
            )
        ]

    def parse_to_schema(self, fetch_result: FetchResult) -> list[Observation]:
        text = fetch_result.local_path.read_text(encoding="utf-8")
        data_lines = _skip_pangaea_header(text)
        reader = csv.DictReader(io.StringIO(data_lines), delimiter="\t")

        observations: list[Observation] = []
        for row in reader:
            # Faithful adapter: emit ALL stations the source has (CALM is
            # Northern-Hemisphere-wide), with NO in-adapter geographic filter.
            # Region scoping (e.g. to Alaska) is applied downstream via
            # RunConfig.bbox, uniformly across adapters (PI ruling 2026-06-30,
            # F3/A3; dev logs 20260629b / 20260630*). Do not re-add a country
            # filter here.
            alt_str = row.get("ALD [cm]", "").strip()
            if not alt_str or alt_str == "-":
                continue

            try:
                alt_cm = float(alt_str)
            except ValueError:
                continue

            # Column names differ between the older fixture/export ("Event
            # label", "Latitude of event", "DATE/TIME", "Identification") and
            # the real 2025 PANGAEA export ("Event", "Latitude", "Date/Time",
            # "ID"). Look up both for each field.
            event = (row.get("Event label") or row.get("Event") or "").strip()
            site_code = row.get("Site", "").strip()
            site_name = row.get("Name", "").strip()
            gtnp_id = (row.get("Identification") or row.get("ID") or "").strip()
            date_str = (row.get("DATE/TIME") or row.get("Date/Time") or "").strip()

            try:
                lat_raw = row.get("Latitude of event") or row.get("Latitude") or ""
                lon_raw = row.get("Longitude of event") or row.get("Longitude") or ""
                lat = float(lat_raw.strip())
                lon = float(lon_raw.strip())
            except (ValueError, AttributeError):
                continue

            dt = _parse_date(date_str)

            qc_flags: list[str] = []
            if alt_cm >= 150:  # physical probe-refusal threshold on the raw cm value
                qc_flags.append("possible_probe_refusal")

            obs = Observation(
                obs_id=f"calm_{event}_{date_str}",
                obs_type=ObservationType.POINT,
                variable=Variable.ACTIVE_LAYER_THICKNESS,
                value=convert(alt_cm, "cm", "m"),  # canonical unit is m (docs/design/06)
                unit="m",
                latitude=lat,
                longitude=lon,
                depth_m=0.0,
                time_start=dt,
                time_end=dt,
                qc_flags=qc_flags,
                provenance=Provenance(
                    source_id=self.source_id,
                    source_url=fetch_result.source_url,
                    access_timestamp=fetch_result.access_timestamp,
                    content_checksum=fetch_result.content_checksum,
                    adapter_version=ADAPTER_VERSION,
                ),
                extra={
                    "event_label": event,
                    "site_code": site_code,
                    "site_name": site_name,
                    "gtnp_id": gtnp_id,
                    "area_locality": (row.get("Area/locality") or "").strip(),
                    "sample_comment": (row.get("Sample comment") or "").strip(),
                    "comment": (row.get("Comment") or "").strip(),
                },
            )
            observations.append(obs)

        return observations


def _skip_pangaea_header(text: str) -> str:
    """Strip PANGAEA comment lines (/* ... */) and return from the header row onward."""
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
