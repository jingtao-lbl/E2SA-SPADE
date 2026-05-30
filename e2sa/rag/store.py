"""LanceDB-backed literature vector store for the LitReviewAgent."""
from __future__ import annotations

from pathlib import Path

import lancedb
import pyarrow as pa

DEFAULT_LANCE_PATH = Path("data/lance")
EMBEDDING_DIM = 384  # sentence-transformers all-MiniLM-L6-v2 default


def papers_schema(embedding_dim: int = EMBEDDING_DIM) -> pa.Schema:
    """Build the papers table schema with a configurable embedding dimension.

    The embedding field is nullable so papers can be ingested before an
    embedder is wired up. When the LitSearchAgent runs without an embedder,
    it stores None in the embedding column; semantic search functions skip
    rows with null embeddings.
    """
    return pa.schema(
        [
            pa.field("chunk_id", pa.string()),
            pa.field("paper_id", pa.string()),
            pa.field("doi", pa.string()),
            pa.field("title", pa.string()),
            pa.field("authors", pa.list_(pa.string())),
            pa.field("year", pa.int32()),
            pa.field("venue", pa.string()),
            pa.field("region", pa.string()),
            pa.field("variables", pa.list_(pa.string())),
            pa.field("section", pa.string()),
            pa.field("text", pa.string()),
            pa.field("source_url", pa.string()),
            pa.field("citation_count", pa.int32()),
            pa.field("verified", pa.bool_()),
            pa.field("embedding", pa.list_(pa.float32(), list_size=embedding_dim), nullable=True),
            pa.field("ingested_at", pa.timestamp("us")),
        ]
    )


PAPER_SCHEMA = papers_schema()


def open_store(
    path: Path | str = DEFAULT_LANCE_PATH,
    embedding_dim: int = EMBEDDING_DIM,
) -> lancedb.DBConnection:
    """Open (or create) the LanceDB store and ensure the 'papers' table exists."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(str(p))
    if "papers" not in list_table_names(db):
        schema = papers_schema(embedding_dim)
        empty = pa.Table.from_pylist([], schema=schema)
        db.create_table("papers", data=empty)
    return db


def list_table_names(db: lancedb.DBConnection) -> list[str]:
    """Return table names as a plain list across LanceDB versions."""
    resp = db.list_tables()
    if hasattr(resp, "tables"):
        return list(resp.tables)
    return list(resp)
