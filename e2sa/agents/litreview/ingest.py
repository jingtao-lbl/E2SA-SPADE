"""Ingest papers into the LanceDB papers table."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Iterable

import lancedb

from e2sa.rag.store import list_table_names

from .models import Paper


def chunk_id_for(paper: Paper) -> str:
    """Stable chunk identifier (paper_id + sha256 of abstract)."""
    abstract_hash = hashlib.sha256(
        (paper.abstract or "").encode("utf-8")
    ).hexdigest()[:12]
    return f"{paper.paper_id}_abstract_{abstract_hash}"


def existing_chunk_ids(db: lancedb.DBConnection) -> set[str]:
    """Return all chunk_ids currently in the papers table for dedup."""
    if "papers" not in list_table_names(db):
        return set()
    table = db.open_table("papers")
    if table.count_rows() == 0:
        return set()
    arrow_table = table.to_arrow()
    if "chunk_id" not in arrow_table.schema.names:
        return set()
    return {v for v in arrow_table.column("chunk_id").to_pylist() if v}


def papers_to_rows(papers: Iterable[Paper], embedding_dim: int = 384) -> list[dict]:
    """Convert Paper records to LanceDB row dicts. Embedding is null."""
    rows = []
    now = datetime.now(tz=timezone.utc)
    for paper in papers:
        rows.append(
            {
                "chunk_id": chunk_id_for(paper),
                "paper_id": paper.paper_id,
                "doi": paper.doi or "",
                "title": paper.title,
                "authors": paper.authors,
                "year": paper.year if paper.year is not None else 0,
                "venue": paper.venue or "",
                "region": "",
                "variables": [],
                "section": "abstract",
                "text": paper.abstract or "",
                "source_url": paper.source_url or "",
                "citation_count": paper.citation_count or 0,
                "verified": paper.verified,
                "embedding": None,
                "ingested_at": now,
            }
        )
    return rows


def ingest_papers(
    db: lancedb.DBConnection,
    papers: list[Paper],
    embedding_dim: int = 384,
) -> tuple[int, int]:
    """Insert papers into the papers table, skipping duplicates by chunk_id.

    Returns:
        (ingested_count, duplicates_skipped)
    """
    if not papers:
        return (0, 0)

    existing = existing_chunk_ids(db)
    new_rows = []
    duplicates = 0
    for paper in papers:
        cid = chunk_id_for(paper)
        if cid in existing:
            duplicates += 1
            continue
        new_rows.append(paper)
        existing.add(cid)

    if not new_rows:
        return (0, duplicates)

    rows = papers_to_rows(new_rows, embedding_dim=embedding_dim)
    table = db.open_table("papers")
    table.add(rows)
    return (len(rows), duplicates)
