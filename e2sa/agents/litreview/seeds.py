"""Seed reference loader for LitReviewAgent.

Reads a curated list of known-good papers from a Markdown, BibTeX, or
CSV file, extracts DOIs, and enriches each one via CrossRef into a
full Paper record. The resulting Paper objects are marked as seeds
(via `extra["is_seed"] = True`) so downstream code can distinguish
them from search-derived papers.

Seeds serve three roles in the review pipeline:

1. Anchoring: ingested into the LanceDB store first as ground truth
2. Decomposition hint: their titles can inform theme generation
3. Screening positive examples: passed to the relevance screener so
   the LLM uses them as concrete examples of what HIGH relevance
   looks like for this topic

Mirrors the role of `Reference.md` in Jing's manual phosphorus
literature review workflow.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

from .models import Paper
from .verify import CrossRefVerifier

# DOI regex per the Crossref guidelines. Permissive on the suffix.
DOI_PATTERN = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", re.IGNORECASE)


def load_seeds(
    path: Path | str,
    verifier: CrossRefVerifier | None = None,
    enrich: bool = True,
) -> list[Paper]:
    """Load seed papers from a Markdown / CSV / BibTeX / WoS export.

    Auto-detects format by extension, falling back to DOI extraction
    on the raw text. Each unique DOI is converted into a Paper record.
    If `enrich=True` (default), each Paper is enriched via CrossRef
    to populate title, authors, year, and venue.

    Args:
        path: Path to the seed file.
        verifier: Optional CrossRefVerifier instance. Constructed if None.
        enrich: When True, call CrossRef for each DOI. Disable for tests
            or when offline.

    Returns:
        A list of Paper records with `extra["is_seed"] = True`. The list
        preserves the order of first occurrence in the source file.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Seed file not found: {p}")

    suffix = p.suffix.lower()
    if suffix == ".csv":
        dois, titles = _extract_from_csv(p)
    elif suffix in {".bib", ".bibtex"}:
        dois, titles = _extract_from_bibtex(p)
    else:
        # Markdown, txt, WoS export, anything else: regex DOIs
        dois, titles = _extract_from_freetext(p)

    seen: set[str] = set()
    unique: list[tuple[str, str]] = []
    for doi, title in zip(dois, titles):
        normalized = doi.strip().rstrip(".,;:)")
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append((normalized, title))

    if not unique:
        return []

    if verifier is None and enrich:
        verifier = CrossRefVerifier()

    papers: list[Paper] = []
    for doi, fallback_title in unique:
        paper = Paper(
            paper_id=doi,
            doi=doi,
            title=fallback_title or "(seed; title pending)",
            source_backend="seed",
            verified=False,
            extra={"is_seed": True, "seed_source": str(p)},
        )
        if enrich and verifier is not None:
            try:
                paper = verifier.enrich_paper(paper)
            except Exception:  # noqa: BLE001
                pass
            paper = paper.model_copy(
                update={
                    "extra": {**paper.extra, "is_seed": True, "seed_source": str(p)},
                }
            )
        papers.append(paper)
    return papers


def _extract_from_freetext(path: Path) -> tuple[list[str], list[str]]:
    """Extract DOIs and a best-effort matching title from any text file.

    Looks for DOIs anywhere in the text. For each DOI, scans the same
    line and the line above for a likely title (anything in **bold**
    or quotes, or the longest text segment).
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    dois: list[str] = []
    titles: list[str] = []

    for i, line in enumerate(lines):
        for match in DOI_PATTERN.finditer(line):
            doi = match.group(0)
            dois.append(doi)
            title = _guess_title(lines, i)
            titles.append(title)
    return dois, titles


def _guess_title(lines: list[str], doi_line_idx: int) -> str:
    """Best-effort title extraction from the line containing the DOI or the line above."""
    candidates = []
    for idx in (doi_line_idx, doi_line_idx - 1, doi_line_idx - 2):
        if idx < 0 or idx >= len(lines):
            continue
        line = lines[idx]
        # Strip markdown bullet markers and ordinal numbers
        stripped = re.sub(r"^[\s\d\-\*\.\):#]+", "", line).strip()
        # Strip the DOI itself if present
        stripped = DOI_PATTERN.sub("", stripped).strip()
        # Strip URL prefix
        stripped = re.sub(r"https?://\S+", "", stripped).strip()
        # Bold or italic markdown
        bold = re.search(r"\*\*([^*]+)\*\*", stripped)
        if bold:
            return bold.group(1).strip()
        if 5 < len(stripped) < 200:
            candidates.append(stripped)
    return candidates[0] if candidates else ""


def _extract_from_csv(path: Path) -> tuple[list[str], list[str]]:
    """Extract DOIs and titles from a CSV with at least a `doi` column."""
    dois: list[str] = []
    titles: list[str] = []

    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            return dois, titles
        doi_field = _pick_field(reader.fieldnames, ["doi", "DOI", "Doi"])
        title_field = _pick_field(reader.fieldnames, ["title", "Title", "TI"])
        for row in reader:
            doi_value = (row.get(doi_field, "") if doi_field else "") or ""
            for match in DOI_PATTERN.finditer(doi_value):
                dois.append(match.group(0))
                titles.append(row.get(title_field, "") if title_field else "")
    return dois, titles


def _extract_from_bibtex(path: Path) -> tuple[list[str], list[str]]:
    """Extract DOIs and titles from a BibTeX file using a small parser."""
    text = path.read_text(encoding="utf-8", errors="replace")
    entries = re.split(r"@\w+\s*\{", text)
    dois: list[str] = []
    titles: list[str] = []
    for entry in entries[1:]:
        doi_match = re.search(r"doi\s*=\s*\{([^}]+)\}", entry, re.IGNORECASE)
        if not doi_match:
            continue
        title_match = re.search(r"title\s*=\s*\{([^}]+)\}", entry, re.IGNORECASE)
        for d in DOI_PATTERN.finditer(doi_match.group(1)):
            dois.append(d.group(0))
            titles.append(title_match.group(1).strip() if title_match else "")
    return dois, titles


def _pick_field(fieldnames: list[str], candidates: list[str]) -> str | None:
    for c in candidates:
        if c in fieldnames:
            return c
    return None
