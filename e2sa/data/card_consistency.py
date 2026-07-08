"""Validator: each built adapter's citation stays consistent with its source card.

Two artifacts describe every dataset SPADE assembles. The adapter carries the
machine-facing citation (`DatasetInfo.citation`, stamped into provenance and the
self-describing bundle); the source card (`projects/<project>/data/sources/<card>.md`)
carries the human-facing one. SPADE ships connectors and adapters, never the data,
so the citation is the attribution that must travel with each source, and the two
copies must not drift.

For every adapter in the registry this checks that:

  1. the adapter is mapped to a source card that exists,
  2. every DOI in the adapter's citation appears in that card,
  3. the citation's first-author surname appears in that card.

DOI presence (not full-string equality) is the invariant, because a card may
format the same DOI as `https://doi.org/X`, `doi:X`, or inside a PANGAEA URL. A
None citation is allowed (the never-fabricate rule: silence beats a guess) and is
reported as a skip, not an error. The engine is generic; the SPADE card mapping
and runner live in `projects/spade/tools/check_card_consistency.py`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from e2sa.data.registry import ADAPTER_REGISTRY

# Bare DOI (10.<registrant>/<suffix>). The suffix stops at whitespace, quotes,
# angle brackets, or closing punctuation so a trailing period/paren is not glued on.
_DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>)\];,]+")
_TRAILING = ".,;)]"


def extract_dois(text: str) -> list[str]:
    """Bare DOIs found in `text`, de-duplicated, trailing punctuation stripped."""
    out: list[str] = []
    for match in _DOI_RE.findall(text):
        doi = match.rstrip(_TRAILING)
        if doi not in out:
            out.append(doi)
    return out


def first_author_surname(citation: str) -> str | None:
    """The leading surname of a citation string (the token before the first comma
    or semicolon), or None if the citation does not start with a name."""
    match = re.match(r"\s*([A-Za-z][A-Za-z'\-]+)", citation)
    return match.group(1) if match else None


@dataclass
class Finding:
    """One card-consistency result for a (source_id, dataset) pair."""

    source_id: str
    card: str | None
    level: str  # "error" | "ok" | "skip"
    message: str

    @property
    def is_error(self) -> bool:
        return self.level == "error"

    def __str__(self) -> str:
        mark = {"error": "FAIL", "ok": "ok  ", "skip": "skip"}.get(self.level, "?")
        where = self.card or "(no card)"
        return f"[{mark}] {self.source_id} -> {where}: {self.message}"


def check_card_citation_consistency(
    sources_dir: Path,
    card_by_source_id: dict[str, str],
    registry: dict | None = None,
    raw_dir: Path = Path("data/raw"),
) -> list[Finding]:
    """Check every registered adapter's citation against its source card.

    Input contract: `sources_dir` holds the project's source cards; `card_by_source_id`
    maps each registered source_id to its card basename. Output: one Finding per
    dataset (plus one per unmapped/missing adapter). Side effects: none (reads cards
    and calls each adapter's cheap `list_available`). An adapter absent from
    `card_by_source_id` is an error, so a new adapter cannot silently skip a card.
    """
    reg = ADAPTER_REGISTRY if registry is None else registry
    findings: list[Finding] = []
    for source_id in sorted(reg):
        cls = reg[source_id]
        card = card_by_source_id.get(source_id)
        if card is None:
            findings.append(
                Finding(
                    source_id,
                    None,
                    "error",
                    f"no source card mapped; add {source_id!r} to the card mapping",
                )
            )
            continue
        card_path = sources_dir / card
        if not card_path.exists():
            findings.append(
                Finding(source_id, card, "error", f"mapped card does not exist under {sources_dir}")
            )
            continue
        card_text = card_path.read_text(encoding="utf-8")
        try:
            infos = cls(raw_dir=raw_dir).list_available()
        except Exception as exc:  # list_available is contracted to be cheap/offline
            findings.append(Finding(source_id, card, "error", f"list_available() failed: {exc}"))
            continue

        checked_any = False
        for info in infos:
            citation = getattr(info, "citation", None)
            if not citation:
                continue
            checked_any = True
            problems: list[str] = []
            for doi in extract_dois(citation):
                if doi not in card_text:
                    problems.append(f"citation DOI {doi} missing from card")
            surname = first_author_surname(citation)
            if surname and surname not in card_text:
                problems.append(f"first-author '{surname}' missing from card")
            if problems:
                findings.append(
                    Finding(source_id, card, "error", f"[{info.dataset_id}] " + "; ".join(problems))
                )
            else:
                findings.append(
                    Finding(source_id, card, "ok", f"[{info.dataset_id}] citation consistent")
                )
        if not checked_any:
            findings.append(
                Finding(source_id, card, "skip", "no citation declared on any dataset (allowed)")
            )
    return findings


def format_report(findings: list[Finding]) -> str:
    """Human-readable report, errors last so they are the final thing printed."""
    ordered = sorted(findings, key=lambda f: (f.is_error, f.source_id))
    lines = [str(f) for f in ordered]
    n_err = sum(f.is_error for f in findings)
    lines.append("")
    lines.append(f"{len(findings)} checks, {n_err} error(s).")
    return "\n".join(lines)
