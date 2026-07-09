"""TSP North America ground-temperature adapter (NSF Arctic Data Center / DataONE).

Thermal State of Permafrost (TSP) in North America - annually observed ground
temperatures (Romanovsky group, UAF), the US contribution to GTN-P. A *series*
of 10 annual BagIt+EML packages on the NSF Arctic Data Center, 2016-2025, one
DOI per year. Each package is a site roster CSV plus one per-borehole
`Depth_m,Temperature_C` snapshot profile.

This is a **second provider of GROUND_TEMPERATURE** (GTN-P is the first). The
roster carries a GTNP_ID column, so co-located sites match GTN-P exactly; that
cross-source match/dedup happens downstream at assemble()/harmonize, not here
(faithful-adapter policy).

One adapter, many datasets: source_id is the series slug, and list_available()
returns one DatasetInfo per year (dataset_id = tsp_<year>_ground_temperature).
acquire(source_id, dataset_id) fetches a single year; fetch delegates to the
arctic_data_center connector (the year's DOI is registered in the connector's
_KNOWN_DATASETS). See source card projects/spade/data/sources/tsp_north_america.md.

Parse gotchas handled: UTF-8 BOM on the data CSVs (utf-8-sig); the roster
`Filename` column is authoritative for linkage (SiteCode can differ, e.g.
US_BRW_102 -> US_BRW_201_...csv); the per-borehole file is a single-date
snapshot (date from the roster ObservationDate, with a filename-date fallback);
depth is already in metres.
"""

from __future__ import annotations

import csv
import re
from datetime import datetime
from pathlib import Path

from e2sa.data.base import BaseAdapter, DatasetInfo, FetchResult
from e2sa.schema import Observation, ObservationType, Provenance, Variable

ADAPTER_VERSION = "0.1.0"

SOURCE_ID = "tsp_north_america_ground_temperature"
LICENSE = "CC0 1.0 Universal Public Domain Dedication"

#: The annual series: year -> Arctic Data Center version DOI. Enumerated live from
#: the DataONE Solr index (current versions, -obsoletedBy:*) on 2026-07-06.
YEAR_DOI: dict[int, str] = {
    2016: "10.18739/A2W08WG7P",
    2017: "10.18739/A20R9M42C",
    2018: "10.18739/A2HX15Q8V",
    2019: "10.18739/A20R9M47S",
    2020: "10.18739/A2MW28G02",
    2021: "10.18739/A29G5GF7P",
    2022: "10.18739/A2H70823W",
    2023: "10.18739/A2DB7VR9J",
    2024: "10.18739/A2X05XF3W",
    2025: "10.18739/A2SF2MD87",
}

#: Verified full author list (from the 2023 EML). Other years' exact author lists
#: are NOT verified here, so their citation is left None and the native EML staged
#: in the BagIt package is the source of truth (never fabricate authors).
_CITATION_2023 = (
    "Romanovsky, V., A. Kholodov, D. Nicolsky, and T. Wright. 2023. Thermal state "
    "of permafrost in North America - annually observed ground temperatures, "
    "Alaska, 2023. Arctic Data Center. https://doi.org/10.18739/A2DB7VR9J"
)


def dataset_id_for_year(year: int) -> str:
    """tsp_<year>_ground_temperature (matches the raw-folder + connector key)."""
    return f"tsp_{year}_ground_temperature"


_FILENAME_DATE_RE = re.compile(r"(\d{4})[_-](\d{2})[_-](\d{2})")
_DATE_FORMATS = ("%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d", "%Y_%m_%d")


def _parse_coord(raw: str) -> float | None:
    """Coordinate cell to float, tolerating a degree mark + whitespace."""
    if not raw:
        return None
    cleaned = raw.replace("°", "").replace("º", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_date(raw: str, filename: str) -> datetime | None:
    """Roster ObservationDate (MM/DD/YY) with a filename YYYY_MM_DD fallback."""
    s = (raw or "").strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    m = _FILENAME_DATE_RE.search(filename or "")
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


_SLUG_RE = re.compile(r"[^A-Za-z0-9]+")


def _slug(s: str) -> str:
    return _SLUG_RE.sub("_", (s or "").strip()).strip("_") or "unknown"


class TSPNorthAmericaGroundTemperatureAdapter(BaseAdapter):
    """Adapter for the TSP North America annual ground-temperature series.

    NSF Arctic Data Center (DataONE), 10 annual DOIs 2016-2025. Emits
    GROUND_TEMPERATURE PROFILE observations (temperature vs depth) with
    depth_m populated. Connector-backed: fetch delegates to arctic_data_center.
    """

    source_id = SOURCE_ID
    adapter_version = ADAPTER_VERSION
    data_center = "arctic_data_center"
    serves = frozenset({Variable.GROUND_TEMPERATURE})

    def list_available(self) -> list[DatasetInfo]:
        out: list[DatasetInfo] = []
        for year, doi in YEAR_DOI.items():
            out.append(
                DatasetInfo(
                    dataset_id=dataset_id_for_year(year),
                    name=(
                        "Thermal state of permafrost in North America - annually "
                        f"observed ground temperatures, Alaska, {year}"
                    ),
                    description=(
                        "Per-borehole ground-temperature snapshot profiles from the "
                        "US permafrost-observatory network (Romanovsky/UAF), the US "
                        "contribution to GTN-P. Site roster + one Depth_m/Temperature_C "
                        "CSV per borehole. Depth-resolved PROFILE observations. All "
                        "sites emitted faithfully; region scoping is downstream via "
                        "RunConfig.bbox. Cite from this year's ADC landing page / EML "
                        "when not filled here."
                    ),
                    variables=["ground_temperature"],
                    spatial_coverage=(
                        "Alaska + adjacent Canada (bbox W-165.3 S62.2 E-145.5 N78.8)"
                    ),
                    temporal_coverage=str(year),
                    format="CSV (BagIt+EML package)",
                    url=f"https://doi.org/{doi}",
                    license=LICENSE,
                    citation=_CITATION_2023 if year == 2023 else None,
                    keywords=[
                        "ground temperature",
                        "permafrost temperature",
                        "thermal state of permafrost",
                        "borehole",
                        "GTN-P",
                    ],
                )
            )
        return out

    def parse_to_schema(self, fetch_result: FetchResult) -> list[Observation]:
        data_dir = fetch_result.local_path / "data"
        if not data_dir.is_dir():
            raise FileNotFoundError(
                f"Expected data/ subdirectory in {fetch_result.local_path}, not "
                f"found. Re-run fetch() to validate the BagIt layout."
            )

        roster_path = _find_roster(data_dir)
        if roster_path is None:
            raise FileNotFoundError(
                f"No *Roster*.csv found in {data_dir}; cannot map boreholes to "
                f"coordinates. Re-run fetch()."
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
        for site in _read_roster(roster_path):
            borehole_file = _resolve_borehole_file(data_dir, site)
            if borehole_file is None:
                continue  # roster row with no recoverable data file on disk
            obs.extend(
                _parse_borehole(
                    borehole_file, site, fetch_result.dataset_id, provenance
                )
            )

        # Dedupe by obs_id (defensive; a site should appear once per package).
        seen: set[str] = set()
        deduped: list[Observation] = []
        for o in obs:
            if o.obs_id in seen:
                continue
            seen.add(o.obs_id)
            deduped.append(o)
        return deduped


def _find_roster(data_dir: Path) -> Path | None:
    matches = sorted(p for p in data_dir.glob("*.csv") if "roster" in p.name.lower())
    return matches[0] if matches else None


def _resolve_borehole_file(data_dir: Path, site: dict[str, str]) -> Path | None:
    """Locate a roster row's data file, tolerating an inaccurate roster Filename.

    The roster `Filename` is usually authoritative, but a real row can declare a
    name that is not the on-disk name (2023: roster `US_CPT_101_..._.csv` while the
    file is `US_CPT_001_..._.csv`). Trusting the literal name silently drops a real
    borehole, so when the exact name is missing we recover by the shared site
    prefix (`US_<region>`) + the acquisition date, accepting only an unambiguous
    single match (the BagIt "match by content, not declared name" gotcha).
    """
    fname = site["filename"]
    # 1. Exact on-disk name (roster Filename is usually authoritative).
    if (data_dir / fname).is_file():
        return data_dir / fname
    # 2. Normalized name: the 2016 "Borehole" roster writes the date hyphenated and
    #    drops the .csv suffix (US_BLK_001_2016_08-16 vs ..._08_16.csv).
    norm = fname.replace("-", "_")
    if not norm.lower().endswith(".csv"):
        norm += ".csv"
    if (data_dir / norm).is_file():
        return data_dir / norm

    def _nonroster(paths: object) -> list[Path]:
        return [p for p in paths if "roster" not in p.name.lower()]  # type: ignore[attr-defined]

    # 3. Full site code as a prefix: unambiguous per site and tolerant of any date
    #    format (2016 same-region sites share US_<region>, so only the full code
    #    disambiguates US_BRW_101 from US_BRW_201).
    site_code = site["site_code"]
    if site_code:
        cands = _nonroster(data_dir.glob(f"{site_code}*.csv"))
        if len(cands) == 1:
            return cands[0]
    # 4. Region prefix + acquisition date: recovers a roster/disk site-number
    #    mismatch (2023: roster US_CPT_101 while the disk file is US_CPT_001).
    m = _FILENAME_DATE_RE.search(fname)
    date_tok = f"{m.group(1)}_{m.group(2)}_{m.group(3)}" if m else None
    parts = site_code.split("_")
    region = "_".join(parts[:2]) if len(parts) >= 2 else site_code
    if not region:
        return None
    cands = [
        p
        for p in _nonroster(data_dir.glob("*.csv"))
        if p.name.startswith(region) and (date_tok is None or date_tok in p.name)
    ]
    return cands[0] if len(cands) == 1 else None


def _read_csv_dicts(path: Path) -> list[dict[str, str]]:
    """Read a CSV as dicts, stripping the UTF-8 BOM (data CSVs carry one)."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _key_for(fieldnames: list[str], *wanted: str) -> str | None:
    """Case-insensitive header lookup: first field whose name matches any `wanted`.

    Skips a None fieldname: csv.DictReader inserts a None key when a data row has
    more columns than the header (real TSP CSVs have trailing-comma ragged rows).
    """
    lowered = {fn.strip().lower(): fn for fn in fieldnames if fn is not None}
    for w in wanted:
        if w in lowered:
            return lowered[w]
    # substring fallback (e.g. a depth/temperature column named slightly differently)
    for w in wanted:
        for low, orig in lowered.items():
            if w in low:
                return orig
    return None


def _read_roster(roster_path: Path) -> list[dict[str, str]]:
    """Roster rows -> normalized dicts keyed by our concept names."""
    rows = _read_csv_dicts(roster_path)
    if not rows:
        return []
    fns = list(rows[0].keys())
    k_file = _key_for(fns, "filename")
    k_lat = _key_for(fns, "latitude")
    k_lon = _key_for(fns, "longitude")
    k_date = _key_for(fns, "observationdate", "date")
    # Prefer an exact SiteCode / SiteCode_New (2018+ / 2016 rosters) before the
    # substring fallback, which would otherwise grab SiteCodeHistorical (BL1) and
    # break borehole-file linkage (2016 maps zero sites -> zero obs).
    k_site = _key_for(fns, "sitecode", "sitecode_new")
    k_gtnp = _key_for(fns, "gtnp_id", "gtnpid")
    k_name = _key_for(fns, "sitename")
    out: list[dict[str, str]] = []
    for r in rows:
        fname = (r.get(k_file, "") if k_file else "").strip()
        if not fname:
            continue
        out.append(
            {
                "filename": fname,
                "latitude": (r.get(k_lat, "") if k_lat else "").strip(),
                "longitude": (r.get(k_lon, "") if k_lon else "").strip(),
                "date": (r.get(k_date, "") if k_date else "").strip(),
                "site_code": (r.get(k_site, "") if k_site else "").strip(),
                "gtnp_id": (r.get(k_gtnp, "") if k_gtnp else "").strip(),
                "site_name": (r.get(k_name, "") if k_name else "").strip(),
            }
        )
    return out


def _parse_borehole(
    path: Path,
    site: dict[str, str],
    dataset_id: str,
    provenance: Provenance,
) -> list[Observation]:
    lat = _parse_coord(site["latitude"])
    lon = _parse_coord(site["longitude"])
    if lat is None or lon is None:
        return []
    when = _parse_date(site["date"], site["filename"])
    if when is None:
        return []

    rows = _read_csv_dicts(path)
    if not rows:
        return []
    fns = list(rows[0].keys())
    k_depth = _key_for(fns, "depth_m", "depth")
    k_temp = _key_for(fns, "temperature_c", "temperature", "temp")
    if k_depth is None or k_temp is None:
        return []

    site_key = site["site_code"] or _slug(path.stem)
    obs: list[Observation] = []
    for r in rows:
        depth_raw = (r.get(k_depth, "") or "").strip()
        temp_raw = (r.get(k_temp, "") or "").strip()
        if depth_raw == "" or temp_raw == "":
            continue
        try:
            depth_m = float(depth_raw)
            temp_c = float(temp_raw)
        except ValueError:
            continue  # non-numeric / sentinel row -> skip

        obs_id = (
            f"tsp_{_slug(site_key)}_{when.strftime('%Y%m%d')}_"
            f"{int(round(depth_m * 100))}cm"
        )
        obs.append(
            Observation(
                obs_id=obs_id,
                obs_type=ObservationType.PROFILE,
                variable=Variable.GROUND_TEMPERATURE,
                value=temp_c,
                unit="degC",  # canonical (CANONICAL_UNITS[GROUND_TEMPERATURE])
                latitude=lat,
                longitude=lon,
                depth_m=depth_m,  # already metres, positive downward
                time_start=when,
                time_end=when,
                qc_flags=[],
                provenance=provenance,
                extra={
                    "dataset_id": dataset_id,
                    "site_code": site["site_code"],
                    "site_name": site["site_name"],
                    "gtnp_id": site["gtnp_id"],
                    "source_file": path.name,
                },
            )
        )
    return obs
