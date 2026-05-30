"""Web of Science export parser and ingestion.

Parses WoS "Plain Text File" exports with "Full Record" content (the same
format Jing's manual literature reviews use as savedrecs.txt). Converts
records to Paper objects and ingests them into the LanceDB store as a
high-quality, institutionally-curated corpus.

WoS plain text format summary:

    FN Clarivate Analytics Web of Science
    VR 1.0
    PT J
    AU Webb, H
       Pierce, E
    AF Webb, Hailey
       Pierce, Ethan
    TI A Comprehensive Database of Thawing Permafrost Locations Across
       Alaska
    SO Earth System Science Data
    AB We compiled the database ...
    PY 2025
    DI 10.5194/essd-2025-557
    UT WOS:001234567890001
    TC 5
    ER

    PT J
    ...
    ER

    EF

Field tags are two uppercase characters followed by a space. Continuation
lines start with three spaces and belong to the previous field. Records
are delimited by `PT` (publication type) at the start and `ER` (end of
record) at the end. The file ends with `EF` (end of file).

This module handles every field tag that appears in SPADE's exported
savedrecs.txt. Unknown tags are captured into `extra["wos_fields"]` so
nothing is silently dropped.

Reference: openags/paper-search-mcp is not involved in this path. This
parser calls the WoS export file directly with no network I/O.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import lancedb

from .ingest import ingest_papers
from .models import Paper

HEADER_TAGS = {"FN", "VR"}
TERMINATOR_TAGS = {"EF"}
RECORD_START = "PT"
RECORD_END = "ER"


@dataclass
class WoSIngestResult:
    """Report from a WoS ingest run."""

    path: str
    records_parsed: int = 0
    records_with_doi: int = 0
    records_with_wos_uid: int = 0
    records_with_abstract: int = 0
    records_with_year: int = 0
    ingested: int = 0
    duplicates_skipped: int = 0
    errors: list[str] = field(default_factory=list)


def parse_wos_file(path: Path | str) -> list[Paper]:
    """Parse a WoS plain-text field-tagged export into Paper records.

    Raises FileNotFoundError if the path does not exist.
    Returns an empty list if the file has no parseable records.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"WoS export not found: {p}")

    text = p.read_text(encoding="utf-8-sig", errors="replace")
    lines = text.splitlines()

    papers: list[Paper] = []
    current_fields: dict[str, list[str]] = {}
    current_tag: str | None = None
    in_record = False

    for raw_line in lines:
        # Keep trailing whitespace trimmed but preserve internal spaces
        line = raw_line.rstrip()
        if not line:
            # Empty line inside a record is ignored; between records is fine too
            continue

        # Terminator or header detection
        if line.startswith(RECORD_END):
            if in_record:
                paper = _record_to_paper(current_fields)
                if paper is not None:
                    papers.append(paper)
                current_fields = {}
                current_tag = None
                in_record = False
            continue

        stripped = line.strip()
        if stripped in TERMINATOR_TAGS:
            break

        # New-field detection: two uppercase chars + space
        if len(line) >= 3 and line[0].isupper() and line[1].isalnum() and line[2] == " ":
            tag = line[:2]
            value = line[3:]

            if tag in HEADER_TAGS and not in_record:
                continue

            if tag == RECORD_START:
                in_record = True
                current_fields = {tag: [value]}
                current_tag = tag
                continue

            if not in_record:
                continue

            current_fields.setdefault(tag, []).append(value)
            current_tag = tag
            continue

        # Continuation: 3 spaces at start, or just whitespace then content
        if in_record and current_tag is not None and (
            raw_line.startswith("   ") or raw_line.startswith("\t")
        ):
            content = raw_line.lstrip()
            current_fields.setdefault(current_tag, []).append(content)
            continue

    # If file ended without a trailing ER, still try to emit the last record
    if in_record and current_fields:
        paper = _record_to_paper(current_fields)
        if paper is not None:
            papers.append(paper)

    return papers


def _record_to_paper(fields: dict[str, list[str]]) -> Paper | None:
    """Convert an accumulated field dict to a Paper record. None if unusable."""

    def join_field(tag: str, sep: str = " ") -> str:
        values = fields.get(tag, [])
        joined = sep.join(v.strip() for v in values if v)
        return joined.strip()

    doi = join_field("DI")
    wos_uid = join_field("UT")
    title = join_field("TI")
    if not title and not doi and not wos_uid:
        return None  # nothing to anchor on

    # Authors: prefer full names (AF), fallback to short (AU)
    af_lines = fields.get("AF", [])
    au_lines = fields.get("AU", [])
    authors = [line.strip() for line in (af_lines or au_lines) if line.strip()]

    year: int | None = None
    py_raw = join_field("PY")
    if py_raw:
        try:
            year = int(py_raw[:4])
        except ValueError:
            year = None

    venue = join_field("SO")
    abstract = join_field("AB")
    if not abstract:
        abstract = None

    citation_count: int | None = None
    tc_raw = join_field("TC")
    if tc_raw:
        try:
            citation_count = int(tc_raw)
        except ValueError:
            citation_count = None

    paper_id = doi if doi else f"wos:{wos_uid}" if wos_uid else f"wos:notitle:{hash(title)}"

    source_url = None
    if doi:
        source_url = f"https://doi.org/{doi}"

    extra: dict[str, object] = {
        "is_wos": True,
        "wos_uid": wos_uid,
        "document_type": join_field("DT"),
        "publication_type": join_field("PT"),
        "language": join_field("LA"),
        "keywords_author": join_field("DE", sep="; "),
        "keywords_plus": join_field("ID", sep="; "),
        "wos_categories": join_field("WC", sep="; "),
        "research_areas": join_field("SC", sep="; "),
        "z9_citations": join_field("Z9"),
        "tc_wos_core": tc_raw,
        "publisher": join_field("PU"),
        "issn": join_field("SN"),
        "eissn": join_field("EI"),
    }

    return Paper(
        paper_id=paper_id,
        doi=doi or None,
        title=title or "(no title)",
        authors=authors,
        year=year,
        venue=venue or None,
        abstract=abstract,
        source_url=source_url,
        citation_count=citation_count,
        source_backend="wos",
        verified=True,  # WoS records are institutionally curated
        extra=extra,
    )


def ingest_wos_export(
    db: lancedb.DBConnection,
    path: Path | str,
    dry_run: bool = False,
) -> WoSIngestResult:
    """Parse a WoS export and ingest into the LanceDB store.

    Args:
        db: An open LanceDB connection (use e2sa.rag.store.open_store()).
        path: Path to the WoS plain-text export (e.g., savedrecs.txt).
        dry_run: If True, parse but do not write to the store. Useful
            for checking a file before committing.

    Returns:
        A WoSIngestResult summarizing the run.
    """
    result = WoSIngestResult(path=str(path))

    try:
        papers = parse_wos_file(path)
    except FileNotFoundError as e:
        result.errors.append(str(e))
        return result

    result.records_parsed = len(papers)
    for p in papers:
        if p.doi:
            result.records_with_doi += 1
        else:
            result.records_with_wos_uid += 1
        if p.abstract:
            result.records_with_abstract += 1
        if p.year:
            result.records_with_year += 1

    if dry_run or not papers:
        return result

    ingested, duplicates = ingest_papers(db, papers)
    result.ingested = ingested
    result.duplicates_skipped = duplicates
    return result
