"""Phase A: dataset package indexer.

Walks an already-downloaded dataset directory, detects the metadata standard,
parses it, and writes one row per file (package_files) and one row per
variable (dataset_variables) into the DuckDB catalog. No network access.

Two parser paths:
  - ESS-DIVE: optional FLMD + per-file ``*_dd.csv`` data dictionaries + PDF user-file
  - DataONE BagIt: ``bagit.txt`` + ``manifest-md5.txt`` + EML ``science-metadata.xml``

Dispatch on detected standard. Both paths populate the same two tables.
EML/BagIt path is stubbed here and implemented in A3.
"""
from __future__ import annotations

import csv
import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from e2sa.catalog import register_dataset_variables, register_package_files
from e2sa.schema import Variable

# Confident concept-anchored name -> Variable enum. Ambiguous names stay
# as raw_name with parseable=False.
_VAR_MAP: dict[str, Variable] = {
    "soil_temperature": Variable.SOIL_TEMPERATURE,
    # Bare "temperature" / "temp" map to soil temperature in our domain
    # (permafrost datasets; air-temperature columns are always explicitly
    # labeled, e.g. air_temperature / Tair / AirTemp). This catches Sloan's
    # 30-min dd-CSV column "temperature" and the 36 per-plot dd-CSV column
    # "Temp, deg C" (post-normalization).
    "temperature": Variable.SOIL_TEMPERATURE,
    "temp": Variable.SOIL_TEMPERATURE,
    "volumetric_soil_moisture": Variable.VOLUMETRIC_WATER_CONTENT,
    "soil_moisture": Variable.VOLUMETRIC_WATER_CONTENT,
    "thaw_depth": Variable.ACTIVE_LAYER_THICKNESS,
    "active_layer_thickness": Variable.ACTIVE_LAYER_THICKNESS,
    "air_temperature": Variable.AIR_TEMPERATURE,
    "ground_temperature": Variable.GROUND_TEMPERATURE,
    "land_surface_temperature": Variable.LAND_SURFACE_TEMPERATURE,
    "snow_depth": Variable.SNOW_DEPTH,
    "ndvi": Variable.NDVI,
    "elevation": Variable.ELEVATION,
    "precipitation": Variable.PRECIPITATION,
    "volumetric_ice_content": Variable.VOLUMETRIC_ICE_CONTENT,
    "excess_ice_content": Variable.EXCESS_ICE_CONTENT,  # EIC: distinct from total volumetric ice
    "eic": Variable.EXCESS_ICE_CONTENT,
    "vmc": Variable.VOLUMETRIC_WATER_CONTENT,  # Kanevskiy "VMC, %" = volumetric moisture
}

# E2SA-generated metadata bundle + connector-captured native metadata. Skipped by
# the indexer at the dataset-root only (they describe the data, they are not data).
_GENERATED_METADATA = frozenset(
    {"PROVENANCE.json", "CITATION.cff", "README.md", "metadata.txt", "metadata.json"}
)

_FORMAT_BY_SUFFIX = {
    ".csv": "csv",
    ".tsv": "tsv",
    ".pdf": "pdf",
    ".xml": "xml",
    ".nc": "netcdf",
    ".tif": "geotiff",
    ".tiff": "geotiff",
    ".txt": "text",
    ".json": "json",
    ".md": "markdown",
}


@dataclass
class IndexResult:
    dataset_id: str
    standard: str  # "ess_dive_dd" | "dataone_bagit" | "unknown"
    n_files: int
    n_variables: int
    md5_mismatches: list[str] = field(default_factory=list)


def _sha256_md5_file(path: Path, chunk: int = 1 << 20) -> tuple[str, str]:
    """Compute sha256 and md5 in a single disk pass. Returns (sha256_hex, md5_hex)."""
    sh = hashlib.sha256()
    md = hashlib.md5()
    with path.open("rb") as fh:
        while True:
            buf = fh.read(chunk)
            if not buf:
                break
            sh.update(buf)
            md.update(buf)
    return sh.hexdigest(), md.hexdigest()


def _file_id(dataset_id: str, relative_path: str) -> str:
    return hashlib.sha256(f"{dataset_id}|{relative_path}".encode()).hexdigest()[:16]


def _detect_format(path: Path) -> str | None:
    return _FORMAT_BY_SUFFIX.get(path.suffix.lower())


def _detect_role(rel: str) -> str:
    name = Path(rel).name.lower()
    if name in ("bagit.txt", "bag-info.txt", "manifest-md5.txt", "tagmanifest-md5.txt"):
        return "bagit"
    if name == "flmd.csv" or name.endswith("_flmd.csv"):
        return "flmd"
    if name.endswith("_dd.csv"):
        return "dictionary"
    if "science-metadata" in name and name.endswith(".xml"):
        return "eml"
    if name.endswith(".xml"):
        return "metadata"
    if "user_file" in name and name.endswith(".pdf"):
        return "readme"
    if name.endswith(".pdf"):
        return "aux"
    if name.endswith((".csv", ".tsv", ".nc", ".tif", ".tiff")):
        return "data"
    return "aux"


def _map_variable(raw_name: str) -> Variable | None:
    """Concept-anchored lookup. Tries the raw name as-is, then a normalized form
    (strip ", %"-style suffixes, replace spaces/hyphens with underscores) so EML
    names like "EIC, %" and ESS-DIVE names like volumetric_soil_moisture both hit.
    """
    key = raw_name.strip().lower()
    if key in _VAR_MAP:
        return _VAR_MAP[key]
    # Drop trailing ", unit", " (unit)", "[unit]" suffixes (common in EML attributeNames).
    normalized = re.sub(r"[,(\[].*$", "", key).strip()
    normalized = re.sub(r"[\s\-]+", "_", normalized)
    if normalized in _VAR_MAP:
        return _VAR_MAP[normalized]
    if normalized.startswith("soil_temperature") or "soil_temp" in normalized:
        return Variable.SOIL_TEMPERATURE
    return None


def detect_standard(dataset_dir: Path) -> str:
    if (dataset_dir / "bagit.txt").is_file():
        return "dataone_bagit"
    for p in dataset_dir.iterdir():
        n = p.name.lower()
        if n.endswith("_dd.csv") or n == "flmd.csv" or n.endswith("_flmd.csv"):
            return "ess_dive_dd"
    return "unknown"


def index_package(
    conn: duckdb.DuckDBPyConnection,
    dataset_id: str,
    dataset_dir: Path,
) -> IndexResult:
    """Walk a downloaded dataset directory (or single file) and populate the catalog.

    Two shapes are supported:
        - Directory: walk recursively, detect ESS-DIVE FLMD / DataONE BagIt
          metadata standard, register every file + every declared variable.
        - Single file: register one package_files row for the file itself
          (sha256, size, format, role). No dataset_variables (we cannot
          introspect without a dd-CSV/EML alongside). Standard reported as
          "single_file". Lets adapters that hand back a one-file FetchResult
          (Alaska Thaw DB zip, CALM TSV, etc.) flow through acquire() without
          a directory wrapper.

    Idempotent: re-running on the same path is a no-op (upsert by file_id).
    """
    dataset_dir = Path(dataset_dir)
    if dataset_dir.is_file():
        return _index_single_file(conn, dataset_id, dataset_dir)
    if not dataset_dir.is_dir():
        raise FileNotFoundError(f"Not a file or directory: {dataset_dir}")

    standard = detect_standard(dataset_dir)
    access_ts = datetime.now(tz=UTC)

    file_rows: list[dict] = []
    rel_to_id: dict[str, str] = {}
    rel_to_md5: dict[str, str] = {}
    for p in sorted(dataset_dir.rglob("*")):
        if not p.is_file():
            continue
        # Skip dot-prefixed files (UNIX hidden-file convention). Adapters use
        # these for internal state (e.g., .essdive_package_id) that should not
        # appear in the catalog as a data file.
        if p.name.startswith("."):
            continue
        # Skip the E2SA-generated metadata bundle (PROVENANCE.json/CITATION.cff/
        # README.md) + connector-captured native metadata, but only at the
        # dataset root where they are written — a dataset's own nested READMEs
        # (e.g. inside an extracted zip) are still indexed.
        if p.parent == dataset_dir and p.name in _GENERATED_METADATA:
            continue
        rel = p.relative_to(dataset_dir).as_posix()
        fid = _file_id(dataset_id, rel)
        rel_to_id[rel] = fid
        sha256_hex, md5_hex = _sha256_md5_file(p)
        rel_to_md5[rel] = md5_hex
        file_rows.append(
            {
                "file_id": fid,
                "dataset_id": dataset_id,
                "relative_path": rel,
                "role": _detect_role(rel),
                "format": _detect_format(p),
                "bytes": p.stat().st_size,
                "content_checksum": sha256_hex,
                "access_timestamp": access_ts,
                "missing_sentinel": None,
                "time_zone": None,
            }
        )

    if standard == "ess_dive_dd":
        var_rows, per_file_meta = _parse_ess_dive_variables(
            dataset_id, dataset_dir, rel_to_id
        )
    elif standard == "dataone_bagit":
        var_rows, per_file_meta = _parse_bagit_eml_variables(
            dataset_id, dataset_dir, rel_to_id
        )
    else:
        var_rows, per_file_meta = [], {}

    # Merge per-file metadata (sentinels, tz) into the file rows before writing.
    for row in file_rows:
        meta = per_file_meta.get(row["file_id"], {})
        if meta.get("missing_sentinel"):
            row["missing_sentinel"] = meta["missing_sentinel"]
        if meta.get("time_zone"):
            row["time_zone"] = meta["time_zone"]

    # BagIt integrity check: any disk file whose md5 differs from manifest.
    md5_mismatches: list[str] = []
    if standard == "dataone_bagit":
        manifest = _read_bagit_manifest(dataset_dir / "manifest-md5.txt")
        declared = {rel: md5 for md5, rel in manifest.items()}
        for rel, disk_md5 in rel_to_md5.items():
            declared_md5 = declared.get(rel)
            if declared_md5 and declared_md5.lower() != disk_md5.lower():
                md5_mismatches.append(rel)

    register_package_files(conn, file_rows)
    register_dataset_variables(conn, var_rows)

    return IndexResult(
        dataset_id=dataset_id,
        standard=standard,
        n_files=len(file_rows),
        n_variables=len(var_rows),
        md5_mismatches=md5_mismatches,
    )


def _index_single_file(
    conn: duckdb.DuckDBPyConnection,
    dataset_id: str,
    file_path: Path,
) -> IndexResult:
    """Register one file as a one-row package_files entry.

    Used when an adapter returns FetchResult.local_path pointing at a single
    file (zip, csv, etc.) rather than a directory. Records the file's sha256,
    size, format, and role. No dataset_variables are emitted since we cannot
    introspect column structure without a dd-CSV/EML companion.
    """
    rel = file_path.name
    sha256_hex, _md5_hex = _sha256_md5_file(file_path)
    row = {
        "file_id": _file_id(dataset_id, rel),
        "dataset_id": dataset_id,
        "relative_path": rel,
        "role": _detect_role(rel),
        "format": _detect_format(file_path),
        "bytes": file_path.stat().st_size,
        "content_checksum": sha256_hex,
        "access_timestamp": datetime.now(tz=UTC),
        "missing_sentinel": None,
        "time_zone": None,
    }
    register_package_files(conn, [row])
    return IndexResult(
        dataset_id=dataset_id,
        standard="single_file",
        n_files=1,
        n_variables=0,
        md5_mismatches=[],
    )


# ---------- ESS-DIVE: optional FLMD + per-file dd-CSV ----------

_DD_REQUIRED_COLS = {"Column_or_Row_Name", "Unit", "Definition"}


def _extract_sentinel(definition: str) -> str | None:
    if not definition:
        return None
    needle = "missing values ="
    idx = definition.lower().find(needle)
    if idx < 0:
        return None
    tail = definition[idx + len(needle):].strip()
    end = len(tail)
    for stop in (".", "\n"):
        i = tail.find(stop)
        if 0 <= i < end:
            end = i
    return tail[:end].strip().strip("'\"‘’") or None


def _parse_dd_csv(path: Path) -> list[dict]:
    out: list[dict] = []
    with path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames or not _DD_REQUIRED_COLS.issubset(set(reader.fieldnames)):
            return out
        for row in reader:
            raw = (row.get("Column_or_Row_Name") or "").strip()
            if not raw:
                continue
            unit = (row.get("Unit") or "").strip() or None
            if unit == "N/A":
                unit = None
            definition = (row.get("Definition") or "").strip()
            out.append(
                {
                    "raw_name": raw,
                    "unit": unit,
                    "definition": definition,
                    "data_type": (row.get("Data_Type") or "").strip().lower() or None,
                    "missing_sentinel": _extract_sentinel(definition),
                }
            )
    return out


def _parse_ess_dive_variables(
    dataset_id: str,
    dataset_dir: Path,
    rel_to_id: dict[str, str],
) -> tuple[list[dict], dict[str, dict]]:
    """One row per (variable, file_id), with raw_names aggregated.

    Pairs each ``*_dd.csv`` to data files by filename prefix; multiple raw
    columns that map to the same Variable enum (e.g. soil_temperature_5cm,
    _15cm, _25cm) collapse to one row per file. Also returns per-file metadata
    (missing_sentinel collected from dd-CSV definitions) keyed by file_id.
    """
    dd_files = [p for p in dataset_dir.rglob("*_dd.csv") if p.is_file()]
    data_files = [
        p
        for p in dataset_dir.rglob("*.csv")
        if p.is_file()
        and not p.name.lower().endswith("_dd.csv")
        and p.name.lower() != "flmd.csv"
        and not p.name.lower().endswith("_flmd.csv")
    ]

    agg: dict[tuple[str, str], dict] = {}
    sentinels_per_file: dict[str, list[str]] = {}

    for dd in dd_files:
        dd_rel = dd.relative_to(dataset_dir).as_posix()
        dd_id = rel_to_id.get(dd_rel)
        if dd_id is None:
            continue
        prefix = dd.name[: -len("_dd.csv")]
        matched = [
            p for p in data_files
            if p.parent == dd.parent and p.name.startswith(prefix)
        ]
        target_ids = (
            [rel_to_id[p.relative_to(dataset_dir).as_posix()] for p in matched]
            or [dd_id]
        )

        for var in _parse_dd_csv(dd):
            mapped = _map_variable(var["raw_name"])
            variable_key = mapped.value if mapped else var["raw_name"]
            for fid in target_ids:
                key = (variable_key, fid)
                slot = agg.setdefault(
                    key,
                    {
                        "raw_names": [],
                        "units": [],
                        "parseable": mapped is not None,
                    },
                )
                if var["raw_name"] not in slot["raw_names"]:
                    slot["raw_names"].append(var["raw_name"])
                if var["unit"] and var["unit"] not in slot["units"]:
                    slot["units"].append(var["unit"])

                if var["missing_sentinel"]:
                    for fid_s in target_ids:
                        bucket = sentinels_per_file.setdefault(fid_s, [])
                        if var["missing_sentinel"] not in bucket:
                            bucket.append(var["missing_sentinel"])

    rows: list[dict] = []
    for (variable_key, fid), slot in agg.items():
        rows.append(
            {
                "dataset_id": dataset_id,
                "variable": variable_key,
                "raw_name": ", ".join(slot["raw_names"]),
                "unit": ", ".join(slot["units"]) if slot["units"] else None,
                "file_id": fid,
                "crs_tier": "pdf",  # ESS-DIVE convention: CRS lives in PDF user-file.
                "parseable": slot["parseable"],
            }
        )

    per_file_meta = {
        fid: {"missing_sentinel": ", ".join(sents)}
        for fid, sents in sentinels_per_file.items()
    }
    return rows, per_file_meta


# ---------- DataONE BagIt + EML ----------

_EML_NAME = "science-metadata.xml"


def _find_eml(dataset_dir: Path) -> Path | None:
    """Locate the EML metadata XML within a DataONE BagIt package.

    DataONE BagIt layout varies across archives and across versions of the same
    dataset. The original Kanevskiy predecessor placed it at
    ``metadata/science-metadata.xml``; the current version (DOI A2H12V928) ships
    it at the package root under a title-derived name. Prefer the known path,
    then fall back to any ``.xml`` whose root is an EML document (root tag ``eml``
    or containing a ``<dataTable>``). The ``.rdf`` resource map is skipped (not
    ``.xml``). General lesson: identify by content, not by declared filename.
    """
    preferred = dataset_dir / "metadata" / _EML_NAME
    if preferred.is_file():
        return preferred
    for p in sorted(dataset_dir.rglob("*.xml")):
        try:
            root = ET.parse(p).getroot()
        except ET.ParseError:
            continue
        tag = root.tag.rsplit("}", 1)[-1]  # strip any namespace
        if tag == "eml" or root.find(".//dataTable") is not None:
            return p
    return None


def _read_bagit_manifest(manifest_path: Path) -> dict[str, str]:
    """Return md5 -> relative_path map from a BagIt manifest-md5.txt."""
    out: dict[str, str] = {}
    if not manifest_path.is_file():
        return out
    for line in manifest_path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2:
            out[parts[0]] = parts[1]
    return out


def _fuzzy_basename_key(name: str) -> str:
    return re.sub(r"[\s\-_]+", "", name).lower()


def _eml_unit(attr: ET.Element) -> str | None:
    for tag in ("standardUnit", "customUnit"):
        el = attr.find(f".//unit/{tag}")
        if el is not None and el.text:
            return el.text.strip()
    return None


def _parse_bagit_eml_variables(
    dataset_id: str,
    dataset_dir: Path,
    rel_to_id: dict[str, str],
) -> tuple[list[dict], dict[str, dict]]:
    """DataONE BagIt + EML path.

    Reads metadata/science-metadata.xml; for each <dataTable>, matches the
    declared <entityName> to a disk file by basename (exact, then fuzzy), and
    enumerates <attribute>s into dataset_variables rows. Filename matching is
    cross-checked against the BagIt manifest for content-based identification.
    Per-file metadata captures any <missingValueCode> declared per dataTable.
    """
    eml_path = _find_eml(dataset_dir)
    if eml_path is None:
        return [], {}

    # Disk basename -> file_id (the authoritative truth).
    basename_to_id: dict[str, str] = {}
    fuzzy_to_id: dict[str, str] = {}
    for rel, fid in rel_to_id.items():
        bn = Path(rel).name
        basename_to_id[bn] = fid
        fuzzy_to_id[_fuzzy_basename_key(bn)] = fid

    # BagIt manifest cross-check (informational; ensures every declared file
    # has a content checksum on disk).
    _read_bagit_manifest(dataset_dir / "manifest-md5.txt")

    try:
        root = ET.parse(eml_path).getroot()
    except ET.ParseError:
        return [], {}

    agg: dict[tuple[str, str], dict] = {}
    sentinels_per_file: dict[str, list[str]] = {}

    for dt in root.iter("dataTable"):
        entity = (dt.findtext("entityName") or "").strip()
        if not entity:
            continue
        target_id = basename_to_id.get(entity) or fuzzy_to_id.get(_fuzzy_basename_key(entity))
        if target_id is None:
            continue

        attr_list = dt.find("attributeList")
        if attr_list is None:
            continue
        for attr in attr_list.findall("attribute"):
            raw = (attr.findtext("attributeName") or "").strip()
            if not raw:
                continue
            unit = _eml_unit(attr)
            mapped = _map_variable(raw)
            variable_key = mapped.value if mapped else raw
            key = (variable_key, target_id)
            slot = agg.setdefault(
                key,
                {"raw_names": [], "units": [], "parseable": mapped is not None},
            )
            if raw not in slot["raw_names"]:
                slot["raw_names"].append(raw)
            if unit and unit not in slot["units"]:
                slot["units"].append(unit)

            # Per-file sentinel from <missingValueCode>; Kanevskiy doesn't declare
            # any (blank == missing), but other DataONE archives do.
            for code_el in attr.findall(".//missingValueCode/code"):
                if code_el.text:
                    bucket = sentinels_per_file.setdefault(target_id, [])
                    sentinel = code_el.text.strip()
                    if sentinel and sentinel not in bucket:
                        bucket.append(sentinel)

    rows: list[dict] = []
    for (variable_key, fid), slot in agg.items():
        rows.append(
            {
                "dataset_id": dataset_id,
                "variable": variable_key,
                "raw_name": ", ".join(slot["raw_names"]),
                "unit": ", ".join(slot["units"]) if slot["units"] else None,
                "file_id": fid,
                "crs_tier": "assumed-wgs84",  # EML omits CRS for Kanevskiy.
                "parseable": slot["parseable"],
            }
        )

    per_file_meta = {
        fid: {"missing_sentinel": ", ".join(sents)}
        for fid, sents in sentinels_per_file.items()
    }
    return rows, per_file_meta
