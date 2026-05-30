"""Paper Search MCP backend for LitReviewAgent.

Wraps the openags/paper-search-mcp library
(https://github.com/openags/paper-search-mcp, MIT license, author: openags)
as a unified search backend that fans out a query across multiple academic
platforms (arXiv, PubMed, bioRxiv, medRxiv, Google Scholar) and returns
normalized Paper records.

paper-search-mcp is also available as an MCP server. This module imports
its underlying searcher classes directly so we can call them from Python
without spawning an MCP subprocess. Both the MCP server and this direct
import path are valid ways to use the same library.

Note on the arXiv adapter: paper-search-mcp's ArxivSearcher sorts by
submittedDate which returns the most recent papers regardless of query
relevance. We override that one platform with a relevance-ranked variant
(_RelevanceArxivSearcher) while still using paper-search-mcp for the other
platforms unchanged.
"""
from __future__ import annotations

import importlib
from datetime import datetime
from typing import Any

from .models import Paper, SearchQuery

class _RelevanceArxivSearcher:
    """arXiv searcher with relevance ranking (overrides paper-search-mcp default).

    Compatible with the paper-search-mcp ArxivSearcher interface so the rest
    of the backend treats it identically. The only difference is the API
    parameters: we use sortBy=relevance with the all: field prefix so
    multi-word queries return what users expect.
    """

    BASE_URL = "http://export.arxiv.org/api/query"

    def search(self, query: str, max_results: int = 10) -> list:
        import feedparser  # noqa: PLC0415
        import requests  # noqa: PLC0415

        from paper_search_mcp.paper import Paper as RawPaper  # noqa: PLC0415

        params = {
            "search_query": f"all:{query}",
            "max_results": max_results,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
        response = requests.get(self.BASE_URL, params=params, timeout=30)
        feed = feedparser.parse(response.content)
        papers = []
        for entry in feed.entries:
            try:
                authors = [a.name for a in entry.authors]
                published = datetime.strptime(entry.published, "%Y-%m-%dT%H:%M:%SZ")
                updated = datetime.strptime(entry.updated, "%Y-%m-%dT%H:%M:%SZ")
                pdf_url = next(
                    (link.href for link in entry.links if link.type == "application/pdf"),
                    "",
                )
                papers.append(
                    RawPaper(
                        paper_id=entry.id.split("/")[-1],
                        title=entry.title,
                        authors=authors,
                        abstract=entry.summary,
                        url=entry.id,
                        pdf_url=pdf_url,
                        published_date=published,
                        updated_date=updated,
                        source="arxiv",
                        categories=[t.term for t in entry.tags],
                        keywords=[],
                        doi=entry.get("doi", ""),
                    )
                )
            except Exception:  # noqa: BLE001
                continue
        return papers


# Mapping from short platform name to (module path, class name OR callable factory)
PLATFORM_REGISTRY: dict[str, tuple[str, str] | tuple[None, Any]] = {
    "arxiv": (None, _RelevanceArxivSearcher),  # local override for relevance
    "pubmed": ("paper_search_mcp.academic_platforms.pubmed", "PubMedSearcher"),
    "biorxiv": ("paper_search_mcp.academic_platforms.biorxiv", "BioRxivSearcher"),
    "medrxiv": ("paper_search_mcp.academic_platforms.medrxiv", "MedRxivSearcher"),
    "google_scholar": (
        "paper_search_mcp.academic_platforms.google_scholar",
        "GoogleScholarSearcher",
    ),
}

DEFAULT_PLATFORMS = ["arxiv", "pubmed", "biorxiv", "medrxiv"]


class PaperSearchMCPBackend:
    """Unified search backend over openags/paper-search-mcp searchers.

    Default platforms: arXiv, PubMed, bioRxiv, medRxiv. Google Scholar is
    available but disabled by default because it is more likely to break
    or be rate-limited.

    Each platform searcher is constructed lazily on first use. If a platform
    is not installed or fails to import, the backend skips it and continues.
    Per-query, if one platform fails the others still return results.
    """

    def __init__(
        self,
        platforms: list[str] | None = None,
        searcher_factory: dict[str, Any] | None = None,
    ) -> None:
        """Construct the backend.

        Args:
            platforms: list of platform names from PLATFORM_REGISTRY. If None,
                uses DEFAULT_PLATFORMS.
            searcher_factory: optional pre-built mapping {platform_name: searcher}
                for tests or for injecting custom searchers.
        """
        self.platforms = platforms or list(DEFAULT_PLATFORMS)
        if searcher_factory is not None:
            self._searchers = dict(searcher_factory)
        else:
            self._searchers = self._build_searchers(self.platforms)

    @staticmethod
    def _build_searchers(platforms: list[str]) -> dict[str, Any]:
        searchers: dict[str, Any] = {}
        for name in platforms:
            if name not in PLATFORM_REGISTRY:
                continue
            module_path, class_or_factory = PLATFORM_REGISTRY[name]
            try:
                if module_path is None:
                    # Local override (e.g., relevance-ranked arxiv)
                    searchers[name] = class_or_factory()
                else:
                    module = importlib.import_module(module_path)
                    cls = getattr(module, class_or_factory)
                    searchers[name] = cls()
            except (ImportError, AttributeError):
                continue
        return searchers

    @property
    def available_platforms(self) -> list[str]:
        return list(self._searchers.keys())

    def search_papers(self, query: SearchQuery) -> list[Paper]:
        """Run the query across all configured platforms and return normalized Papers."""
        if not self._searchers:
            return []

        per_platform_limit = max(1, query.limit // len(self._searchers))
        all_papers: list[Paper] = []

        for platform_name, searcher in self._searchers.items():
            try:
                raw_results = searcher.search(query.query, max_results=per_platform_limit)
            except Exception:  # noqa: BLE001
                # One platform failure should not kill the whole search
                continue
            for raw in raw_results or []:
                try:
                    all_papers.append(_to_paper(raw, platform_name))
                except Exception:  # noqa: BLE001
                    continue

        all_papers = _filter_by_year(all_papers, query.year_min, query.year_max)
        return all_papers[: query.limit]


def _to_paper(raw: Any, platform_name: str) -> Paper:
    """Convert a paper_search_mcp Paper into an e2sa.litreview Paper."""
    raw_authors = getattr(raw, "authors", None)
    if isinstance(raw_authors, str):
        authors = [a.strip() for a in raw_authors.split(";") if a.strip()]
    elif isinstance(raw_authors, list):
        authors = [str(a).strip() for a in raw_authors if str(a).strip()]
    else:
        authors = []

    year: int | None = None
    published_date = getattr(raw, "published_date", None)
    if isinstance(published_date, datetime):
        year = published_date.year
    elif isinstance(published_date, str) and len(published_date) >= 4:
        try:
            year = int(published_date[:4])
        except ValueError:
            year = None

    doi = getattr(raw, "doi", "") or None
    raw_paper_id = getattr(raw, "paper_id", "") or ""
    paper_id = doi or f"{platform_name}:{raw_paper_id}" if raw_paper_id else doi or "unknown"

    return Paper(
        paper_id=paper_id,
        doi=doi,
        title=getattr(raw, "title", "") or "",
        authors=authors,
        year=year,
        venue=None,
        abstract=getattr(raw, "abstract", "") or None,
        source_url=getattr(raw, "url", "") or None,
        citation_count=getattr(raw, "citations", 0) or None,
        source_backend=f"paper_search_mcp:{platform_name}",
        verified=False,
        extra={
            "platform": platform_name,
            "paper_id_native": raw_paper_id,
            "pdf_url": getattr(raw, "pdf_url", "") or "",
            "categories": getattr(raw, "categories", "") or "",
            "keywords": getattr(raw, "keywords", "") or "",
            "published_date": (
                published_date.isoformat()
                if isinstance(published_date, datetime)
                else (published_date or "")
            ),
        },
    )


def _filter_by_year(
    papers: list[Paper], year_min: int | None, year_max: int | None
) -> list[Paper]:
    if year_min is None and year_max is None:
        return papers
    filtered = []
    for p in papers:
        if p.year is None:
            continue
        if year_min is not None and p.year < year_min:
            continue
        if year_max is not None and p.year > year_max:
            continue
        filtered.append(p)
    return filtered
