"""Unit tests for LitReviewAgent. No live API calls."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from e2sa.agents.litreview import (
    CrossRefVerifier,
    LitReviewAgent,
    Paper,
    SearchQuery,
    SemanticScholarClient,
)
from e2sa.agents.litreview.ingest import (
    chunk_id_for,
    existing_chunk_ids,
    ingest_papers,
    papers_to_rows,
)
from e2sa.rag.store import open_store

FIXTURES = Path(__file__).parent / "fixtures"


class FakeSearchClient(SemanticScholarClient):
    """Test double that returns a canned Semantic Scholar response."""

    def __init__(self, fixture_path: Path) -> None:
        super().__init__()
        self.fixture_path = fixture_path

    def _fetch_json(self, url: str) -> dict[str, Any]:
        return json.loads(self.fixture_path.read_text())


class FakeVerifier(CrossRefVerifier):
    """Test double that returns a canned CrossRef response for one DOI."""

    def __init__(self, fixture_path: Path, target_doi: str) -> None:
        super().__init__(rate_limit_seconds=0)
        self.fixture_path = fixture_path
        self.target_doi = target_doi

    def verify(self, doi: str) -> dict[str, Any] | None:
        if doi != self.target_doi:
            return None
        payload = json.loads(self.fixture_path.read_text())
        return payload.get("message")


# --- Models ---


class TestPaperModel:
    def test_paper_minimum_fields(self) -> None:
        p = Paper(paper_id="x", title="t", source_backend="semantic_scholar")
        assert p.paper_id == "x"
        assert p.title == "t"
        assert p.verified is False
        assert p.authors == []

    def test_search_query_defaults(self) -> None:
        q = SearchQuery(query="permafrost")
        assert q.limit == 20
        assert q.year_min is None


# --- Search backend ---


class TestSemanticScholarClient:
    def test_parses_fixture_response(self) -> None:
        client = FakeSearchClient(FIXTURES / "semantic_scholar_response.json")
        papers = client.search_papers(SearchQuery(query="permafrost", limit=10))
        assert len(papers) == 3
        ran = papers[0]
        assert ran.doi == "10.5194/essd-14-865-2022"
        assert ran.year == 2022
        assert "Youhua Ran" in ran.authors
        assert ran.source_backend == "semantic_scholar"

    def test_paper_without_doi_uses_paper_id(self) -> None:
        client = FakeSearchClient(FIXTURES / "semantic_scholar_response.json")
        papers = client.search_papers(SearchQuery(query="anything"))
        no_doi = [p for p in papers if not p.doi]
        assert len(no_doi) == 1
        assert no_doi[0].paper_id == "ghi789"


# --- CrossRef verifier ---


class TestCrossRefVerifier:
    def test_enriches_matching_paper(self) -> None:
        verifier = FakeVerifier(
            FIXTURES / "crossref_response.json",
            target_doi="10.5194/essd-14-865-2022",
        )
        paper = Paper(
            paper_id="10.5194/essd-14-865-2022",
            doi="10.5194/essd-14-865-2022",
            title="",
            source_backend="semantic_scholar",
        )
        enriched = verifier.enrich_paper(paper)
        assert enriched.verified is True
        assert "Northern Hemisphere" in enriched.title
        assert enriched.year == 2022
        assert enriched.venue == "Earth System Science Data"

    def test_unverified_paper_unchanged(self) -> None:
        verifier = FakeVerifier(FIXTURES / "crossref_response.json", target_doi="other")
        paper = Paper(
            paper_id="some_id",
            doi="10.0000/notfound",
            title="Original Title",
            source_backend="semantic_scholar",
        )
        result = verifier.enrich_paper(paper)
        assert result.verified is False
        assert result.title == "Original Title"

    def test_paper_without_doi_unchanged(self) -> None:
        verifier = FakeVerifier(FIXTURES / "crossref_response.json", target_doi="any")
        paper = Paper(paper_id="x", title="t", source_backend="semantic_scholar")
        result = verifier.enrich_paper(paper)
        assert result.verified is False


# --- Ingestion ---


class TestIngestion:
    def test_chunk_id_stable(self) -> None:
        p = Paper(
            paper_id="10.1234/test",
            title="t",
            abstract="hello world",
            source_backend="semantic_scholar",
        )
        cid1 = chunk_id_for(p)
        cid2 = chunk_id_for(p)
        assert cid1 == cid2
        assert cid1.startswith("10.1234/test_abstract_")

    def test_papers_to_rows_handles_missing_fields(self) -> None:
        p = Paper(paper_id="x", title="t", source_backend="semantic_scholar")
        rows = papers_to_rows([p])
        assert len(rows) == 1
        row = rows[0]
        assert row["doi"] == ""
        assert row["year"] == 0
        assert row["embedding"] is None
        assert row["section"] == "abstract"

    def test_ingest_into_lance(self, tmp_path: Path) -> None:
        db = open_store(tmp_path / "lance")
        papers = [
            Paper(
                paper_id="10.1234/p1",
                doi="10.1234/p1",
                title="Paper One",
                authors=["A"],
                year=2024,
                abstract="abstract one",
                source_backend="semantic_scholar",
            ),
            Paper(
                paper_id="10.1234/p2",
                doi="10.1234/p2",
                title="Paper Two",
                authors=["B"],
                year=2023,
                abstract="abstract two",
                source_backend="semantic_scholar",
            ),
        ]
        ingested, dups = ingest_papers(db, papers)
        assert ingested == 2
        assert dups == 0

        # second ingest of same papers is a no-op
        ingested2, dups2 = ingest_papers(db, papers)
        assert ingested2 == 0
        assert dups2 == 2

    def test_existing_chunk_ids(self, tmp_path: Path) -> None:
        db = open_store(tmp_path / "lance")
        assert existing_chunk_ids(db) == set()
        ingest_papers(
            db,
            [
                Paper(
                    paper_id="10.1234/p3",
                    title="Paper Three",
                    abstract="abstract three",
                    source_backend="semantic_scholar",
                )
            ],
        )
        existing = existing_chunk_ids(db)
        assert len(existing) == 1


# --- Agent end-to-end ---


class TestLitReviewAgent:
    def test_search_only_returns_papers(self, tmp_path: Path) -> None:
        agent = LitReviewAgent(
            store_path=tmp_path / "lance",
            search_client=FakeSearchClient(FIXTURES / "semantic_scholar_response.json"),
            verify_dois=False,
        )
        papers = agent.search_only(SearchQuery(query="permafrost"))
        assert len(papers) == 3

    def test_search_and_ingest_no_verification(self, tmp_path: Path) -> None:
        agent = LitReviewAgent(
            store_path=tmp_path / "lance",
            search_client=FakeSearchClient(FIXTURES / "semantic_scholar_response.json"),
            verify_dois=False,
        )
        result = agent.search_and_ingest(SearchQuery(query="permafrost"))
        assert result.total_returned == 3
        assert result.ingested_count == 3
        assert result.duplicates_skipped == 0
        assert result.verification_attempted == 0
        assert result.verification_succeeded == 0

    def test_search_and_ingest_with_verification(self, tmp_path: Path) -> None:
        agent = LitReviewAgent(
            store_path=tmp_path / "lance",
            search_client=FakeSearchClient(FIXTURES / "semantic_scholar_response.json"),
            verifier=FakeVerifier(
                FIXTURES / "crossref_response.json",
                target_doi="10.5194/essd-14-865-2022",
            ),
            verify_dois=True,
        )
        result = agent.search_and_ingest(SearchQuery(query="permafrost"))
        assert result.total_returned == 3
        assert result.ingested_count == 3
        assert result.verification_attempted == 2
        assert result.verification_succeeded == 1
        verified_papers = [p for p in result.papers if p.verified]
        assert len(verified_papers) == 1
        assert verified_papers[0].doi == "10.5194/essd-14-865-2022"

    def test_dedup_on_repeat_run(self, tmp_path: Path) -> None:
        agent = LitReviewAgent(
            store_path=tmp_path / "lance",
            search_client=FakeSearchClient(FIXTURES / "semantic_scholar_response.json"),
            verify_dois=False,
        )
        first = agent.search_and_ingest(SearchQuery(query="permafrost"))
        second = agent.search_and_ingest(SearchQuery(query="permafrost"))
        assert first.ingested_count == 3
        assert second.ingested_count == 0
        assert second.duplicates_skipped == 3


# --- Themed search ---


class FakeThemeSearchClient:
    """Test double that returns different papers for different queries.

    Used to verify themed-mode dedup and per-theme counts.
    """

    def __init__(self) -> None:
        # Map query string -> list of fake papers (paper_ids)
        self._catalog = {
            "permafrost ground ice": [
                ("10.1234/p1", "Ground ice paper one"),
                ("10.1234/p2", "Ground ice paper two"),
            ],
            "thermokarst Alaska": [
                ("10.1234/p2", "Ground ice paper two"),  # overlaps with theme 1
                ("10.1234/p3", "Thermokarst paper three"),
            ],
            "InSAR permafrost": [
                ("10.1234/p4", "InSAR paper four"),
            ],
        }

    def search_papers(self, query: SearchQuery):
        from e2sa.agents.litreview.models import Paper

        records = self._catalog.get(query.query, [])
        return [
            Paper(
                paper_id=pid,
                doi=pid,
                title=title,
                source_backend="fake_themed",
            )
            for (pid, title) in records[: query.limit]
        ]


class TestThemedSearch:
    def test_themed_search_runs_per_theme(self, tmp_path: Path) -> None:
        agent = LitReviewAgent(
            store_path=tmp_path / "lance",
            search_client=FakeThemeSearchClient(),
            verify_dois=False,
        )
        result = agent.search_and_ingest(
            SearchQuery(
                themes=["permafrost ground ice", "thermokarst Alaska", "InSAR permafrost"],
                limit=10,
            )
        )
        # 4 unique papers across 3 themes (one duplicate)
        assert result.total_returned == 4
        assert result.ingested_count == 4

    def test_per_theme_counts(self, tmp_path: Path) -> None:
        agent = LitReviewAgent(
            store_path=tmp_path / "lance",
            search_client=FakeThemeSearchClient(),
            verify_dois=False,
        )
        result = agent.search_and_ingest(
            SearchQuery(
                themes=["permafrost ground ice", "thermokarst Alaska", "InSAR permafrost"],
                limit=10,
            )
        )
        # Theme 1 contributes 2 unique. Theme 2 had p2 overlap so only p3 is new.
        # Theme 3 contributes 1 new.
        assert result.per_theme_counts["permafrost ground ice"] == 2
        assert result.per_theme_counts["thermokarst Alaska"] == 1
        assert result.per_theme_counts["InSAR permafrost"] == 1

    def test_themed_search_propagates_per_theme_limit(self, tmp_path: Path) -> None:
        agent = LitReviewAgent(
            store_path=tmp_path / "lance",
            search_client=FakeThemeSearchClient(),
            verify_dois=False,
        )
        # limit=1 should give at most 1 paper per theme
        result = agent.search_and_ingest(
            SearchQuery(
                themes=["permafrost ground ice", "thermokarst Alaska"],
                limit=1,
            )
        )
        # Theme 1 contributes p1. Theme 2 contributes p2 (since limit=1, p2 from theme 2 not p3)
        # Total unique = 2
        assert result.total_returned <= 2

    def test_is_themed_property(self) -> None:
        assert SearchQuery(query="x").is_themed is False
        assert SearchQuery(themes=["a", "b"]).is_themed is True
        assert SearchQuery(query="x", themes=["a"]).is_themed is True

    def test_themed_search_empty_themes_falls_back_to_query(self, tmp_path: Path) -> None:
        agent = LitReviewAgent(
            store_path=tmp_path / "lance",
            search_client=FakeThemeSearchClient(),
            verify_dois=False,
        )
        result = agent.search_and_ingest(
            SearchQuery(query="permafrost ground ice", themes=[], limit=10)
        )
        # Falls back to single-query mode
        assert result.total_returned == 2
        assert result.per_theme_counts == {}
