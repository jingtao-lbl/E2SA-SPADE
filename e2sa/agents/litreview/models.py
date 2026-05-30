"""Pydantic models for LitReviewAgent."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class Paper(BaseModel):
    """A normalized scientific paper record from any search backend."""

    paper_id: str
    """Stable identifier (DOI preferred, fallback to source-specific ID)."""

    doi: str | None = None
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    abstract: str | None = None
    source_url: str | None = None
    citation_count: int | None = None

    source_backend: str
    """Which backend produced this record (semantic_scholar, crossref, etc.)."""

    verified: bool = False
    """True if the DOI was verified against CrossRef."""

    extra: dict[str, Any] = Field(default_factory=dict)
    """Backend-specific fields not in the unified schema."""


class SearchQuery(BaseModel):
    """Parameters for a literature search.

    Two modes:

    1. Single-query mode: set `query` to a free-text string. The agent
       runs one search per backend with that query. Best for backends
       that handle multi-word queries with proper relevance ranking
       (Semantic Scholar).

    2. Themed mode: set `themes` to a list of focused single-concept
       queries. The agent runs one search per theme and merges results.
       Best for backends that prefer single-concept queries
       (paper-search-mcp's per-platform searchers). Mirrors the manual
       phosphorus literature review workflow where Claude broke a topic
       into 12 themes and searched each separately.

    If both `query` and `themes` are provided, themed mode is used and
    `query` is ignored. If neither is provided, the result is empty.
    """

    query: str = ""
    themes: list[str] = Field(default_factory=list)
    limit: int = 20
    """In single-query mode, the total max results.
    In themed mode, the max results per theme.
    """
    year_min: int | None = None
    year_max: int | None = None
    fields_of_study: list[str] = Field(default_factory=list)

    @property
    def is_themed(self) -> bool:
        return bool(self.themes)


class SearchResult(BaseModel):
    """Outcome of a search and ingest run."""

    query: SearchQuery
    backend: str
    timestamp: datetime
    total_returned: int
    papers: list[Paper]
    ingested_count: int = 0
    duplicates_skipped: int = 0
    verification_attempted: int = 0
    verification_succeeded: int = 0
    per_theme_counts: dict[str, int] = Field(default_factory=dict)
    """Themed mode only: how many unique papers each theme contributed."""
