"""CALM (Circumpolar Active Layer Monitoring) data adapter.

Downloads the PANGAEA ALT dataset (DOI: 10.1594/PANGAEA.972777) and parses
site-average annual active layer thickness measurements into Observation records.
"""
from __future__ import annotations

import csv
import hashlib
import io
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import urlopen

from e2sa.data.base import BaseAdapter, DatasetInfo, FetchResult
from e2sa.schema import Observation, ObservationType, Provenance, Variable

PANGAEA_DOI = "10.1594/PANGAEA.972777"
PANGAEA_URL = f"https://doi.pangaea.de/{PANGAEA_DOI}?format=textfile"
DATASET_ID = "calm_pangaea_972777"
ADAPTER_VERSION = "0.1.0"


class CALMAdapter(BaseAdapter):
    source_id = "calm"
    adapter_version = ADAPTER_VERSION

    def list_available(self) -> list[DatasetInfo]:
        return [
            DatasetInfo(
                dataset_id=DATASET_ID,
                name="CALM ALT Northern Hemisphere (PANGAEA)",
                description=(
                    "Site-average annual active layer thickness, "
                    "263 time series, 1990-2024"
                ),
                variables=["active_layer_thickness"],
                spatial_coverage="Northern Hemisphere (filter to US for Alaska)",
                temporal_coverage="1990-2024",
                format="TSV",
                url=PANGAEA_URL,
                license="CC-BY-4.0",
            )
        ]

    def fetch(self, dataset_id: str = DATASET_ID) -> FetchResult:
        out_path = self.raw_dir / "calm_pangaea.tsv"

        if out_path.exists():
            checksum = _sha256(out_path)
            return FetchResult(
                dataset_id=dataset_id,
                local_path=out_path,
                bytes_downloaded=out_path.stat().st_size,
                access_timestamp=datetime.fromtimestamp(
                    out_path.stat().st_mtime, tz=UTC
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
            access_timestamp=datetime.now(tz=UTC),
            content_checksum=_sha256(out_path),
            source_url=PANGAEA_URL,
        )

    def parse_to_schema(self, fetch_result: FetchResult) -> list[Observation]:
        text = fetch_result.local_path.read_text(encoding="utf-8")
        data_lines = _skip_pangaea_header(text)
        reader = csv.DictReader(io.StringIO(data_lines), delimiter="\t")

        observations: list[Observation] = []
        for row in reader:
            # Accept both the real PANGAEA value "United States (Alaska)" and
            # the bare "United States" (used by older PANGAEA exports + the
            # test fixture). Skip anything else — CALM has many non-US sites
            # but SPADE only cares about Alaska.
            country = row.get("Country", "").strip()
            if not (country.startswith("United States") or "Alaska" in country):
                continue

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
            if alt_cm >= 150:
                qc_flags.append("possible_probe_refusal")

            obs = Observation(
                obs_id=f"calm_{event}_{date_str}",
                obs_type=ObservationType.POINT,
                variable=Variable.ACTIVE_LAYER_THICKNESS,
                value=alt_cm,
                unit="cm",
                latitude=lat,
                longitude=lon,
                depth_m=0.0,
                time_start=dt,
                time_end=dt,
                qc_flags=qc_flags,
                provenance=Provenance(
                    source_id="calm",
                    source_url=PANGAEA_URL,
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


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()
