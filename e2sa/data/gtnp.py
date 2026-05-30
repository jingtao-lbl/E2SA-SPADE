"""GTN-P (Global Terrestrial Network for Permafrost) borehole temperature adapter.

Downloads the PANGAEA 2025 MAGT product (DOI: 10.1594/PANGAEA.972992) and parses
borehole temperature profiles into Observation records. One row per
(borehole, depth, year) measurement.
"""
from __future__ import annotations

import csv
import hashlib
import io
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

from e2sa.data.base import BaseAdapter, DatasetInfo, FetchResult
from e2sa.schema import Observation, ObservationType, Provenance, Variable

PANGAEA_DOI = "10.1594/PANGAEA.972992"
PANGAEA_URL = f"https://doi.pangaea.de/{PANGAEA_DOI}?format=textfile"
DATASET_ID = "gtnp_pangaea_972992"
ADAPTER_VERSION = "0.1.0"


class GTNPAdapter(BaseAdapter):
    source_id = "gtnp"
    adapter_version = ADAPTER_VERSION

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
            )
        ]

    def fetch(self, dataset_id: str = DATASET_ID) -> FetchResult:
        out_path = self.raw_dir / "gtnp_pangaea_magt2025.tsv"

        if out_path.exists():
            checksum = _sha256(out_path)
            return FetchResult(
                dataset_id=dataset_id,
                local_path=out_path,
                bytes_downloaded=out_path.stat().st_size,
                access_timestamp=datetime.fromtimestamp(
                    out_path.stat().st_mtime, tz=timezone.utc
                ),
                content_checksum=checksum,
                source_url=PANGAEA_URL,
            )

        response = urlopen(PANGAEA_URL)  # noqa: S310
        raw_bytes = response.read()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(raw_bytes)

        return FetchResult(
            dataset_id=dataset_id,
            local_path=out_path,
            bytes_downloaded=len(raw_bytes),
            access_timestamp=datetime.now(tz=timezone.utc),
            content_checksum=_sha256(out_path),
            source_url=PANGAEA_URL,
        )

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

            event = row.get("Event label", row.get("Event", "")).strip()
            name = row.get("Name", "").strip()
            gtnp_id = row.get("Identification", "").strip()
            date_str = row.get("DATE/TIME", "").strip()
            frequency = row.get("Frequency", "").strip()
            provenance_source = row.get("Provenance/source", "").strip()
            authors = row.get("Author(s)", "").strip()
            ref_orig = row.get("Reference/source", "").strip()

            dt = _parse_date(date_str)

            obs = Observation(
                obs_id=f"gtnp_{event}_{depth_str}m_{date_str}",
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
                    source_id="gtnp",
                    source_url=PANGAEA_URL,
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
