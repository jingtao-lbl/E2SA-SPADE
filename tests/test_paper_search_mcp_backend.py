"""Unit tests for PaperSearchMCPBackend.

Uses fake searcher classes (no live network) to verify the conversion
from paper_search_mcp.paper.Paper to e2sa.litreview Paper, the
multi-platform fan-out, the per-platform error tolerance, and the
year filtering.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from e2sa.agents.litreview import SearchQuery
from e2sa.agents.litreview.paper_search_mcp_backend import PaperSearchMCPBackend

# --- Fake paper-search-mcp Paper objects ---


@dataclass
class FakeRawPaper:
    paper_id: str
    title: str
    authors: Any
    abstract: str = ""
    doi: str = ""
    published_date: Any = None
    pdf_url: str = ""
    url: str = ""
    source: str = "fake"
    citations: int = 0
    categories: Any = ""
    keywords: Any = ""


# --- Fake searcher classes ---


class FakeArxivSearcher:
    def search(self, query: str, max_results: int = 10) -> list[FakeRawPaper]:
        return [
            FakeRawPaper(
                paper_id="2604.08544v1",
                title="Permafrost ground ice mapping with InSAR",
                authors="Alice Smith; Bob Jones",
                abstract="We present a method...",
                doi="10.1234/arxiv.test1",
                published_date=datetime(2024, 6, 15),
                pdf_url="https://arxiv.org/pdf/2604.08544v1",
                url="http://arxiv.org/abs/2604.08544v1",
                citations=12,
                categories="physics.geo-ph",
            ),
            FakeRawPaper(
                paper_id="2103.99999",
                title="Old paper from 2021",
                authors="Carol Brown",
                published_date=datetime(2021, 3, 1),
                doi="10.1234/arxiv.old",
            ),
        ][:max_results]


class FakePubMedSearcher:
    def search(self, query: str, max_results: int = 10) -> list[FakeRawPaper]:
        return [
            FakeRawPaper(
                paper_id="PMC123456",
                title="A pubmed paper",
                authors=["David Author", "Eve Coauthor"],
                doi="10.1234/pubmed.test",
                published_date=datetime(2023, 1, 1),
            )
        ][:max_results]


class BrokenSearcher:
    def search(self, query: str, max_results: int = 10):
        raise RuntimeError("simulated platform failure")


# --- Tests ---


class TestPaperSearchMCPBackend:
    def _backend_with_fakes(self, **searchers) -> PaperSearchMCPBackend:
        return PaperSearchMCPBackend(
            platforms=list(searchers.keys()),
            searcher_factory=searchers,
        )

    def test_single_platform_search(self) -> None:
        backend = self._backend_with_fakes(arxiv=FakeArxivSearcher())
        papers = backend.search_papers(SearchQuery(query="permafrost", limit=10))
        assert len(papers) == 2
        assert papers[0].title == "Permafrost ground ice mapping with InSAR"
        assert papers[0].source_backend == "paper_search_mcp:arxiv"
        assert papers[0].doi == "10.1234/arxiv.test1"
        assert papers[0].year == 2024
        assert "Alice Smith" in papers[0].authors
        assert "Bob Jones" in papers[0].authors
        assert papers[0].citation_count == 12

    def test_authors_split_from_string(self) -> None:
        backend = self._backend_with_fakes(arxiv=FakeArxivSearcher())
        papers = backend.search_papers(SearchQuery(query="x", limit=5))
        assert papers[0].authors == ["Alice Smith", "Bob Jones"]

    def test_authors_already_list(self) -> None:
        backend = self._backend_with_fakes(pubmed=FakePubMedSearcher())
        papers = backend.search_papers(SearchQuery(query="x", limit=5))
        assert papers[0].authors == ["David Author", "Eve Coauthor"]

    def test_multi_platform_fanout(self) -> None:
        backend = self._backend_with_fakes(
            arxiv=FakeArxivSearcher(),
            pubmed=FakePubMedSearcher(),
        )
        papers = backend.search_papers(SearchQuery(query="x", limit=10))
        sources = {p.source_backend for p in papers}
        assert "paper_search_mcp:arxiv" in sources
        assert "paper_search_mcp:pubmed" in sources

    def test_per_platform_failure_does_not_break_others(self) -> None:
        backend = self._backend_with_fakes(
            arxiv=FakeArxivSearcher(),
            broken=BrokenSearcher(),
        )
        papers = backend.search_papers(SearchQuery(query="x", limit=10))
        assert len(papers) > 0
        sources = {p.source_backend for p in papers}
        assert "paper_search_mcp:arxiv" in sources

    def test_year_min_filter(self) -> None:
        backend = self._backend_with_fakes(arxiv=FakeArxivSearcher())
        papers = backend.search_papers(
            SearchQuery(query="x", limit=10, year_min=2023)
        )
        years = {p.year for p in papers}
        assert all(y >= 2023 for y in years)
        assert 2024 in years
        assert 2021 not in years

    def test_year_max_filter(self) -> None:
        backend = self._backend_with_fakes(arxiv=FakeArxivSearcher())
        papers = backend.search_papers(
            SearchQuery(query="x", limit=10, year_max=2022)
        )
        years = {p.year for p in papers}
        assert 2021 in years
        assert 2024 not in years

    def test_overall_limit_respected(self) -> None:
        backend = self._backend_with_fakes(
            arxiv=FakeArxivSearcher(),
            pubmed=FakePubMedSearcher(),
        )
        papers = backend.search_papers(SearchQuery(query="x", limit=2))
        assert len(papers) <= 2

    def test_no_searchers_returns_empty(self) -> None:
        backend = PaperSearchMCPBackend(platforms=[], searcher_factory={})
        papers = backend.search_papers(SearchQuery(query="x", limit=10))
        assert papers == []

    def test_extra_fields_preserved(self) -> None:
        backend = self._backend_with_fakes(arxiv=FakeArxivSearcher())
        papers = backend.search_papers(SearchQuery(query="x", limit=5))
        extra = papers[0].extra
        assert extra["platform"] == "arxiv"
        assert extra["paper_id_native"] == "2604.08544v1"
        assert extra["pdf_url"].endswith(".pdf/2604.08544v1") or "arxiv.org" in extra["pdf_url"]
