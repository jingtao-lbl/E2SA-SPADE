"""Write the self-describing metadata bundle into a staged dataset folder.

A staged dataset is not "done" as a bare data file (PI requirement, 2026-06-23): every
`raw/<data_center>/<dataset_id>/` folder must carry, alongside the data:

  - PROVENANCE.json  -- uniform machine record (source, DOI, citation, description,
                        references, license, coverage, variables, checksum, timestamps)
  - CITATION.cff     -- how to cite (CFF 1.2.0)
  - README.md        -- human-readable: source link, citation, description, files

The source's *native* metadata (PANGAEA `/* */` header -> metadata.txt; ESS-DIVE
JSON-LD -> metadata.json; DataONE EML already in the BagIt package) is captured
separately by each connector during fetch. This module writes the uniform, derived
records from a DatasetInfo + FetchResult. `acquire()` calls it after fetch + index.
"""
from __future__ import annotations

import json
from pathlib import Path

from e2sa.data.base import DatasetInfo, FetchResult

BUNDLE_FILES = ("PROVENANCE.json", "CITATION.cff", "README.md")


def _doi(*texts: str | None) -> str | None:
    """Extract a DOI from any of the given strings (URL or citation)."""
    for t in texts:
        if t and "doi.org/" in t:
            tail = t.split("doi.org/", 1)[-1].strip().strip("/")
            return tail.split()[0] if tail else None  # first token only
    return None


def _dataset_dir(fr: FetchResult) -> Path:
    """The dataset folder: local_path if a dir, else its parent (single-file)."""
    return fr.local_path if fr.local_path.is_dir() else fr.local_path.parent


def write_metadata_bundle(
    fr: FetchResult, source_id: str, info: DatasetInfo | None
) -> list[Path]:
    """Write PROVENANCE.json + CITATION.cff + README.md into the dataset folder.

    Returns the paths written. Tolerant of a missing DatasetInfo (then citation /
    description are empty and the record is built from the FetchResult alone).
    """
    folder = _dataset_dir(fr)
    data_center = folder.parent.name  # raw/<data_center>/<dataset_id>/
    doi = _doi(
        info.url if info else None,
        fr.source_url,
        info.citation if info else None,
    )
    files = [p.name for p in fr.files] or [fr.local_path.name]

    prov = {
        "source_id": source_id,
        "dataset_id": fr.dataset_id,
        "data_center": data_center,
        "source_url": fr.source_url,
        "landing_page": info.url if info else fr.source_url,
        "doi": doi,
        "title": info.name if info else fr.dataset_id,
        "citation": info.citation if info else None,
        "description": info.description if info else "",
        "keywords": info.keywords if info else [],
        "references": info.references if info else [],
        "license": info.license if info else None,
        "variables": info.variables if info else [],
        "spatial_coverage": info.spatial_coverage if info else None,
        "temporal_coverage": info.temporal_coverage if info else None,
        "format": info.format if info else None,
        "access_timestamp": fr.access_timestamp.isoformat(),
        "content_checksum_sha256": fr.content_checksum,
        "bytes_downloaded": fr.bytes_downloaded,
        "files": files,
        "retrieved_via": "e2sa acquire (connector/adapter)",
    }
    prov_path = folder / "PROVENANCE.json"
    prov_path.write_text(json.dumps(prov, indent=2, ensure_ascii=False) + "\n")

    cff_path = folder / "CITATION.cff"
    cff_path.write_text(_render_cff(prov))

    readme_path = folder / "README.md"
    readme_path.write_text(_render_readme(prov))

    return [prov_path, cff_path, readme_path]


def _yaml_str(s: str) -> str:
    """Minimal YAML double-quoted scalar (escape backslash + quote)."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _render_cff(prov: dict) -> str:
    # Never synthesize a citation. If the adapter did not supply the real one,
    # point to the authoritative source instead of inventing "Title. URL".
    if prov["citation"]:
        message = "If you use this dataset, please cite: " + prov["citation"]
    else:
        where = prov["landing_page"] or prov["source_url"] or prov["doi"]
        message = (
            f"If you use this dataset, cite it per the official citation at {where}"
        )
    lines = [
        "cff-version: 1.2.0",
        f"message: {_yaml_str(message)}",
        f"title: {_yaml_str(prov['title'])}",
        "type: dataset",
    ]
    if prov["doi"]:
        lines.append(f"doi: {_yaml_str(prov['doi'])}")
    if prov["landing_page"]:
        lines.append(f"url: {_yaml_str(prov['landing_page'])}")
    if prov["license"]:
        lines.append(f"license: {_yaml_str(prov['license'])}")
    return "\n".join(lines) + "\n"


def _render_readme(prov: dict) -> str:
    out = [f"# {prov['title']}", ""]
    out.append(f"**Source:** {prov['data_center']} — {prov['landing_page']}  ")
    if prov["doi"]:
        out.append(f"**DOI:** {prov['doi']}  ")
    out.append(f"**License:** {prov['license'] or 'see source'}  ")
    cov = " | ".join(
        x for x in (prov["spatial_coverage"], prov["temporal_coverage"]) if x
    )
    if cov:
        out.append(f"**Coverage:** {cov}  ")
    out.append(
        f"**Retrieved:** {prov['access_timestamp']} "
        f"(sha256 {prov['content_checksum_sha256'][:16]}…)  "
    )
    if prov["variables"]:
        out.append(f"**Variables:** {', '.join(prov['variables'])}  ")
    if prov["citation"]:
        out += ["", "## Citation", "", prov["citation"]]
    if prov["description"]:
        out += ["", "## Description", "", prov["description"]]
    if prov["references"]:
        out += ["", "## References", ""] + [f"- {r}" for r in prov["references"]]
    out += ["", "## Files", ""] + [f"- `{f}`" for f in prov["files"]]
    out += [
        "",
        "---",
        "_Generated by E2SA `acquire()`. See `PROVENANCE.json` for the machine-readable "
        "record and the native source metadata (`metadata.txt`/`metadata.json`/the EML "
        "in the package) for the publisher's own record._",
    ]
    return "\n".join(out) + "\n"
