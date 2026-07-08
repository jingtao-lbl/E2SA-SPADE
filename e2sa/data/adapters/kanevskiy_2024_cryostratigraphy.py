"""Kanevskiy 2024 cryostratigraphy adapter (NSF Arctic Data Center / DataONE).

Single archived BagIt+EML package on the NSF Arctic Data Center.
DOI 10.18739/A2H12V928 (2025-08-08), supersedes 10.18739/A2QR4NS3D.
22 CSVs of per-borehole cryostratigraphy + ground-ice content from
2018-2023 field campaigns, Alaska + Canadian Arctic sites (all emitted;
region scoping is downstream via RunConfig.bbox, not in-adapter).

Primary target: EXCESS_ICE_CONTENT (column "EIC, %"). Depth-resolved
(sample depth in cm, converted to m). PROFILE observations.

Fetch is on-disk verify-only for now: the package is a one-time archived
download (not a live API), so the adapter validates an already-downloaded
BagIt root and raises with explicit manual-download instructions if
missing. A live DataONE MN fetch is a future enhancement.

Parse handles three real schema variants (standard 11-col, +EC, +Elevation)
and explicitly skips two known-incompatible files (a no-Lat/Lon file and
a wholly-different-schema Prudhoe Bay Aug 2022 file with thicknesses only,
no EIC column).
"""

from __future__ import annotations

import csv
import re
from datetime import datetime
from pathlib import Path

from e2sa.data.base import BaseAdapter, DatasetInfo, FetchResult
from e2sa.schema import Observation, ObservationType, Provenance, Variable

ADAPTER_VERSION = "0.1.0"

DOI = "10.18739/A2H12V928"
DOI_URL = f"https://doi.org/{DOI}"
LICENSE = "CC0 1.0 Universal Public Domain Dedication"

DATASET_ID = "kanevskiy_2024_cryostratigraphy"

# Files explicitly skipped (known-incompatible SCHEMAS; see source card gotchas).
# These are parseability skips (no Lat/Lon or no EIC column), NOT geographic
# filters — the adapter is faithful and emits all sites (PI ruling 2026-06-30).
_SKIP_FILES: frozenset[str] = frozenset(
    {
        # No Lat/Lon columns at all — would require lat/lon back-fill from PDF.
        "Utqiagvik_July_2023.csv",
        # Completely different schema: reports layer thicknesses (ALU/ALF/IL/TL),
        # no EIC column. Not a target for the ice-content adapter.
        "Prudhoe_Bay_August_2022.csv",
    }
)

# Column-name aliasing: map by concept, not by exact string (source-card gotcha).
# Each tuple is the ordered list of header strings (stripped, lowered) to try.
_BOREHOLE_KEYS = (
    "borehole",
    "borehole ",
    "borehole/exposure",
    "borehole (b) exposure (e)",
    "borehole (b) or exposure (e)",
    "borehole, type of drilling",
    "exposure",
)
_DATE_KEYS = ("date",)
_LAT_KEYS = ("latitude",)
_LON_KEYS = ("longitude",)
_SAMPLE_DEPTH_KEYS = (
    "sample depth, cm",
    "sample depth,",
    "sample depth",
    "sample depth, ",
)
_EIC_KEYS = (
    "eic, %",
    "eic,",
    "eic, ",
    "eic",
)

_DATE_FORMATS = ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d")

_SAMPLE_DEPTH_RANGE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*$")


def _parse_coord(raw: str) -> float | None:
    """Latitude/longitude cell to float, tolerating a degree symbol + whitespace.

    Some campaign files (e.g. Tuktoyaktuk_September_2019) write coordinates as
    '69.015 ' / '-133.279' decorated with a degree mark; a bare float() throws
    on the degree char so every such row would be silently dropped. Strip the
    degree mark(s) (U+00B0 / U+00BA) and surrounding whitespace first.
    """
    if not raw:
        return None
    cleaned = raw.replace("°", "").replace("º", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


class KanevskiyCryostratigraphyAdapter(BaseAdapter):
    """Adapter for Kanevskiy et al. 2024 cryostratigraphy + ground-ice content.

    NSF Arctic Data Center DOI 10.18739/A2H12V928. Fetched manually
    (DataONE one-time archive), parsed into EXCESS_ICE_CONTENT
    Observations with depth_m populated.
    """

    source_id = DATASET_ID
    adapter_version = ADAPTER_VERSION
    data_center = "arctic_data_center"
    serves = frozenset({Variable.EXCESS_ICE_CONTENT})

    def list_available(self) -> list[DatasetInfo]:
        return [
            DatasetInfo(
                dataset_id=DATASET_ID,
                name=(
                    "Kanevskiy et al. 2024: Cryostratigraphy and ground-ice "
                    "content, multiple Alaska + Canadian Arctic sites, 2018-2023"
                ),
                description=(
                    "Per-borehole cryostratigraphy with gravimetric moisture "
                    "content (GMC), volumetric moisture content (VMC), and "
                    "excess ice content (EIC). 22 CSV files across 10 sites "
                    "(Alaska + Canadian Arctic), all parseable sites emitted "
                    "faithfully; 2 schema-incompatible files skipped (no Lat/Lon "
                    "or no EIC column). Depth-resolved PROFILE observations."
                ),
                variables=["excess_ice_content"],
                spatial_coverage=(
                    "Alaska North Slope (Utqiagvik, Teshekpuk, Prudhoe Bay, "
                    "Anaktuvuk River, Point Lay, Toolik, Itkillik, Jago) + "
                    "Canadian Arctic (Tuktoyaktuk NWT, Bylot Island Nunavut). "
                    "All sites emitted; scope to a region downstream via "
                    "RunConfig.bbox."
                ),
                temporal_coverage="2018-2023",
                format="CSV (BagIt+EML package)",
                url=DOI_URL,
                license=LICENSE,
                citation=(
                    "Kanevskiy, M., Y. Shur, B. Jones, and M. T. Jorgenson. 2024. "
                    "Cryostratigraphy and ground-ice content of the upper permafrost "
                    "in Alaska and Northern Canada, 2018-2023. NSF Arctic Data "
                    f"Center. {DOI_URL}"
                ),
                keywords=[
                    "excess ice content",
                    "cryostratigraphy",
                    "permafrost",
                    "ground ice",
                ],
            )
        ]

    def parse_to_schema(self, fetch_result: FetchResult) -> list[Observation]:
        data_dir = fetch_result.local_path / "data"
        if not data_dir.is_dir():
            raise FileNotFoundError(
                f"Expected data/ subdirectory in {fetch_result.local_path}, "
                f"not found. Re-run fetch() to validate the BagIt layout."
            )

        provenance = Provenance(
            source_id=self.source_id,
            source_url=fetch_result.source_url,
            access_timestamp=fetch_result.access_timestamp,
            content_checksum=fetch_result.content_checksum,
            license=LICENSE,
            adapter_version=ADAPTER_VERSION,
        )

        obs: list[Observation] = []
        for csv_path in sorted(data_dir.glob("*.csv")):
            name = csv_path.name
            if name in _SKIP_FILES:
                continue
            # Faithful adapter: emit ALL sites (Alaska + Canadian Arctic), with
            # NO in-adapter geographic filter. Region scoping is applied
            # downstream via RunConfig.bbox, uniformly across adapters (PI ruling
            # 2026-06-30, F3/A3). _SKIP_FILES above is a SCHEMA-incompatibility
            # skip (no Lat/Lon or no EIC column), not a geographic one, so it
            # stays. Do not re-add a Canadian-site filter here.
            obs.extend(_parse_kanevskiy_csv(csv_path, provenance))

        # Dedupe by obs_id. Kanevskiy publishes per-campaign files that re-include
        # earlier campaign measurements at the same boreholes (e.g. Anaktuvuk
        # Aug 2022 contains all June 2021 rows). Duplicates are byte-identical
        # in our schema (same borehole/date/depth/value), so keep first.
        seen: set[str] = set()
        deduped: list[Observation] = []
        for o in obs:
            if o.obs_id in seen:
                continue
            seen.add(o.obs_id)
            deduped.append(o)
        return deduped


def _parse_kanevskiy_csv(csv_path: Path, provenance: Provenance) -> list[Observation]:
    """Parse one Kanevskiy CSV. Tolerates the three standard schema variants.

    File shape:
        Row 1: title (skip)
        Row 2: blank (skip)
        Row 3: main header row (Borehole, Date, Coordinates, ...)
        Row 4: sub-header row (blank, blank, Latitude, Longitude, ...)
        Row 5+: data rows
    """
    rows = _read_csv_rows(csv_path)
    if len(rows) < 5:
        return []

    col_index = _build_column_index_two_rows(rows[2], rows[3])

    needed = ("borehole", "date", "latitude", "longitude", "sample_depth", "eic")
    if any(col_index.get(k) is None for k in needed):
        # Schema we cannot parse (e.g., no-Lat/Lon file or different schema).
        return []

    obs: list[Observation] = []
    for row in rows[4:]:
        ob = _row_to_observation(row, col_index, csv_path, provenance)
        if ob is not None:
            obs.append(ob)
    return obs


def _read_csv_rows(csv_path: Path) -> list[list[str]]:
    """Read CSV with UTF-8 then latin-1 fallback (source-card encoding gotcha)."""
    try:
        with open(csv_path, encoding="utf-8") as f:
            return list(csv.reader(f))
    except UnicodeDecodeError:
        with open(csv_path, encoding="latin-1") as f:
            return list(csv.reader(f))


def _build_column_index_two_rows(main: list[str], sub: list[str]) -> dict[str, int | None]:
    """Map our concept names to the matching column index, or None if absent.

    Searches BOTH header rows per column (Kanevskiy CSVs use 2-row merged
    headers where the main row carries the concept ('Sample depth,', 'EIC,')
    and the sub row carries the unit ('cm', '%'), or vice versa for
    Coordinates/Latitude/Longitude).
    """
    n = max(len(main), len(sub))
    per_col_names: list[list[str]] = []
    for i in range(n):
        names: list[str] = []
        if i < len(main):
            m = main[i].strip().lower()
            if m:
                names.append(m)
        if i < len(sub):
            s = sub[i].strip().lower()
            if s:
                names.append(s)
        # Also consider concatenated forms like "sample depth, cm" or "eic, %".
        if i < len(main) and i < len(sub):
            joined = f"{main[i].strip()} {sub[i].strip()}".strip().lower()
            if joined and joined not in names:
                names.append(joined)
        per_col_names.append(names)

    def find(keys: tuple[str, ...]) -> int | None:
        for k in keys:
            for i, names in enumerate(per_col_names):
                if k in names:
                    return i
        return None

    out: dict[str, int | None] = {
        "borehole": find(_BOREHOLE_KEYS),
        "date": find(_DATE_KEYS),
        "latitude": find(_LAT_KEYS),
        "longitude": find(_LON_KEYS),
        "sample_depth": find(_SAMPLE_DEPTH_KEYS),
        "eic": find(_EIC_KEYS),
    }
    # Fallback: a few files have "Coordinates" in the main header but blank
    # sub-row cells where "Latitude"/"Longitude" should be. Infer positionally.
    if out["latitude"] is None or out["longitude"] is None:
        coords_idx = find(("coordinates",))
        if coords_idx is not None:
            if out["latitude"] is None:
                out["latitude"] = coords_idx
            if out["longitude"] is None:
                out["longitude"] = coords_idx + 1
    return out


def _row_to_observation(
    row: list[str],
    col: dict[str, int | None],
    csv_path: Path,
    provenance: Provenance,
) -> Observation | None:
    def cell(key: str) -> str:
        idx = col[key]
        if idx is None or idx >= len(row):
            return ""
        return row[idx].strip()

    eic_raw = cell("eic")
    if eic_raw == "":
        return None  # missing EIC (blank); KEEP eic=0 as real data
    try:
        eic_pct = float(eic_raw)
    except ValueError:
        return None

    sample_depth_raw = cell("sample_depth")
    depth_cm = _parse_sample_depth_cm(sample_depth_raw)
    if depth_cm is None:
        return None

    lat = _parse_coord(cell("latitude"))
    lon = _parse_coord(cell("longitude"))
    if lat is None or lon is None:
        return None

    date_raw = cell("date")
    parsed_date = _parse_date(date_raw)
    if parsed_date is None:
        return None

    borehole = cell("borehole")
    if not borehole:
        return None

    obs_id = (
        f"kanevskiy_{_slug(borehole)}_{lat:.4f}_{lon:.4f}_"
        f"{int(round(depth_cm))}cm_{parsed_date.strftime('%Y%m%d')}"
    )

    return Observation(
        obs_id=obs_id,
        obs_type=ObservationType.PROFILE,
        variable=Variable.EXCESS_ICE_CONTENT,
        value=eic_pct / 100.0,  # % -> fraction in [0, 1]
        unit="1",  # canonical dimensionless unit (docs/design/06); value already a fraction
        latitude=lat,
        longitude=lon,
        depth_m=depth_cm / 100.0,
        time_start=parsed_date,
        time_end=parsed_date,
        qc_flags=[],
        provenance=provenance,
        extra={
            "dataset_id": DATASET_ID,
            "borehole": borehole,
            "source_file": csv_path.name,
            "raw_eic_pct": eic_pct,
            "raw_sample_depth": sample_depth_raw,
        },
    )


def _parse_sample_depth_cm(raw: str) -> float | None:
    """Parse a Sample Depth value: single number or 'a-b' range (midpoint)."""
    s = raw.strip()
    if not s:
        return None
    m = _SAMPLE_DEPTH_RANGE_RE.match(s)
    if m:
        a = float(m.group(1))
        b = float(m.group(2))
        return (a + b) / 2.0
    try:
        return float(s)
    except ValueError:
        return None


def _parse_date(raw: str) -> datetime | None:
    s = raw.strip()
    if not s:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


_SLUG_RE = re.compile(r"[^A-Za-z0-9]+")


def _slug(s: str) -> str:
    return _SLUG_RE.sub("_", s.strip()).strip("_") or "unknown"
