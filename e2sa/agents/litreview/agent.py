"""LitReviewAgent: orchestrates search, verification, and ingestion."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import lancedb

from e2sa.rag.store import open_store

from .ingest import ingest_papers
from .models import Paper, SearchQuery, SearchResult
from .search import SemanticScholarClient
from .verify import CrossRefVerifier


@runtime_checkable
class SearchBackend(Protocol):
    """Common interface implemented by all search backends."""

    def search_papers(self, query: SearchQuery) -> list[Paper]: ...


def default_search_backend() -> SearchBackend:
    """Build the preferred search backend.

    Returns a direct Semantic Scholar client by default. Semantic Scholar
    already aggregates papers across arXiv, PubMed, bioRxiv, medRxiv, and
    other sources (200M+ papers total) and provides proper relevance
    ranking, which makes it the best general-purpose search backend.

    The PaperSearchMCPBackend is also available as an explicit choice
    when you need direct per-platform calls (for example, to grab the
    most recent arXiv preprints or to use platform-specific filters that
    Semantic Scholar does not expose). It's also the path we will use
    in Phase 5c for full-text PDF acquisition via paper-search-mcp's
    download_*_paper and read_*_paper functions, which is its primary
    strength.
    """
    return SemanticScholarClient()


def _backend_name(backend: SearchBackend) -> str:
    """Best-effort string identifier for the backend in SearchResult."""
    cls_name = type(backend).__name__
    if cls_name == "PaperSearchMCPBackend":
        platforms = getattr(backend, "available_platforms", [])
        return f"paper_search_mcp:{','.join(platforms)}"
    if cls_name == "SemanticScholarClient":
        return "semantic_scholar"
    return cls_name.lower()


class LitReviewAgent:
    """Orchestrates literature search, DOI verification, and ingestion.

    Default search backend is a direct Semantic Scholar HTTP client
    (good relevance ranking, broad coverage including arXiv, PubMed,
    bioRxiv, medRxiv as part of the same 200M-paper graph).

    An alternative PaperSearchMCPBackend wraps openags/paper-search-mcp
    (https://github.com/openags/paper-search-mcp) for direct per-platform
    calls. Use it when you need platform-specific behavior. paper-search-mcp
    will also be used in Phase 5c for full-text PDF acquisition, which is
    its primary strength.

    DOI verification uses CrossRef (free, no auth). Embedding generation
    is opt-in and not enabled in the default constructor.
    """

    def __init__(
        self,
        store_path: Path | str | None = None,
        search_client: Any = None,
        verifier: CrossRefVerifier | None = None,
        verify_dois: bool = True,
        db: lancedb.DBConnection | None = None,
    ) -> None:
        self.search_client: SearchBackend = search_client or default_search_backend()
        self.verifier = verifier or CrossRefVerifier()
        self.verify_dois = verify_dois
        if db is not None:
            self.db = db
        else:
            self.db = open_store(store_path) if store_path else open_store()

    def search_and_ingest(self, query: SearchQuery) -> SearchResult:
        """Search the backend, optionally verify DOIs, ingest, and return a summary.

        Dispatches to themed-mode or single-query-mode based on whether
        SearchQuery.themes is set.
        """
        timestamp = datetime.now(tz=timezone.utc)

        if query.is_themed:
            papers, per_theme_counts = self._search_themed(query)
        else:
            papers = self.search_client.search_papers(query)
            per_theme_counts = {}

        total_returned = len(papers)

        verification_attempted = 0
        verification_succeeded = 0
        if self.verify_dois:
            enriched: list[Paper] = []
            for paper in papers:
                if paper.doi:
                    verification_attempted += 1
                    enriched_paper = self.verifier.enrich_paper(paper)
                    if enriched_paper.verified:
                        verification_succeeded += 1
                    enriched.append(enriched_paper)
                else:
                    enriched.append(paper)
            papers = enriched

        ingested_count, duplicates_skipped = ingest_papers(self.db, papers)

        return SearchResult(
            query=query,
            backend=_backend_name(self.search_client),
            timestamp=timestamp,
            total_returned=total_returned,
            papers=papers,
            ingested_count=ingested_count,
            duplicates_skipped=duplicates_skipped,
            verification_attempted=verification_attempted,
            verification_succeeded=verification_succeeded,
            per_theme_counts=per_theme_counts,
        )

    def _search_themed(
        self, query: SearchQuery
    ) -> tuple[list[Paper], dict[str, int]]:
        """Run one search per theme, dedupe by paper_id, return merged papers and per-theme counts.

        `query.limit` is interpreted as max results per theme.
        Per-theme counts reflect unique papers contributed by each theme
        (i.e., a paper that came back from theme A and theme B counts only
        for theme A, the first one to surface it).
        """
        seen: set[str] = set()
        merged: list[Paper] = []
        per_theme: dict[str, int] = {}

        for theme in query.themes:
            sub_query = query.model_copy(
                update={"query": theme, "themes": []}
            )
            try:
                results = self.search_client.search_papers(sub_query)
            except Exception:  # noqa: BLE001
                per_theme[theme] = 0
                continue

            unique_count = 0
            for paper in results:
                if paper.paper_id in seen:
                    continue
                seen.add(paper.paper_id)
                merged.append(paper)
                unique_count += 1
            per_theme[theme] = unique_count

        return merged, per_theme

    def search_only(self, query: SearchQuery) -> list[Paper]:
        """Run a search without ingestion or verification. Useful for previewing."""
        if query.is_themed:
            papers, _ = self._search_themed(query)
            return papers
        return self.search_client.search_papers(query)

    def do_triage_only(
        self,
        topic: str,
        context: str = "",
        llm: Any = None,
        seeds: list[Paper] | None = None,
        drop_irrelevant: bool = True,
    ) -> SearchResult:
        """Triage papers already in the LanceDB store; no new search.

        Use this after ingesting a curated corpus (e.g., via ingest-wos
        on a Web of Science export). The agent reads every paper in the
        store that is not already labeled with a relevance rating, runs
        LLM screening with optional seed anchoring, and updates the
        relevance labels in place by re-ingesting the enriched records.

        Seeds, if provided, are still ingested first (they may or may
        not overlap with the existing store) and used as positive
        examples for screening.
        """
        from .screen import screen_papers

        if llm is None:
            from .llm import AnthropicLLM

            llm = AnthropicLLM()

        if seeds:
            ingest_papers(self.db, seeds)

        # Read all papers from the store
        table = self.db.open_table("papers")
        if table.count_rows() == 0:
            return SearchResult(
                query=SearchQuery(query=topic),
                backend="triage_only",
                timestamp=datetime.now(tz=timezone.utc),
                total_returned=0,
                papers=[],
            )

        arrow = table.to_arrow().to_pylist()
        # Convert rows back to Paper records for screening. Skip seeds
        # since they're already trusted (but we may re-screen them for consistency).
        candidates: list[Paper] = []
        seed_dois = {s.doi for s in (seeds or []) if s.doi}
        for row in arrow:
            if row.get("chunk_id", "").startswith("seed") and row.get("doi") in seed_dois:
                continue
            extra = {}
            if row.get("verified") is not None:
                extra["verified_flag"] = row["verified"]
            candidates.append(
                Paper(
                    paper_id=row.get("paper_id") or row.get("chunk_id", "unknown"),
                    doi=row.get("doi") or None,
                    title=row.get("title") or "(no title)",
                    authors=row.get("authors") or [],
                    year=row.get("year") if row.get("year") else None,
                    venue=row.get("venue") or None,
                    abstract=row.get("text") or None,
                    source_url=row.get("source_url") or None,
                    citation_count=row.get("citation_count") or None,
                    source_backend=(
                        "wos"
                        if row.get("chunk_id", "").startswith("wos")
                        else "store"
                    ),
                    verified=bool(row.get("verified")),
                    extra=extra,
                )
            )

        if not candidates:
            return SearchResult(
                query=SearchQuery(query=topic),
                backend="triage_only",
                timestamp=datetime.now(tz=timezone.utc),
                total_returned=0,
                papers=[],
            )

        screened = screen_papers(
            papers=candidates,
            topic=topic,
            context=context,
            llm=llm,
            drop_irrelevant=drop_irrelevant,
            seeds=seeds,
        )

        return SearchResult(
            query=SearchQuery(query=topic),
            backend="triage_only",
            timestamp=datetime.now(tz=timezone.utc),
            total_returned=len(screened),
            papers=screened,
        )

    def do_themed_review(
        self,
        topic: str,
        context: str = "",
        llm: Any = None,
        seeds: list[Paper] | None = None,
        per_theme_limit: int = 5,
        max_themes: int = 12,
        screen: bool = True,
        drop_irrelevant: bool = True,
    ) -> SearchResult:
        """Run the full LLM-orchestrated review pipeline.

        Stages:
            1. Decompose `topic` (with optional `context`) into focused themes via LLM
            2. Run themed search across the configured backend
            3. (Optional) Screen results for relevance via LLM
            4. Verify DOIs (if verify_dois=True on the agent)
            5. Ingest into the LanceDB store with dedup

        Mirrors stages 3 to 4 of Jing's manual phosphorus literature review
        workflow. Stages 5 to 8 (acquire PDFs, extract findings, draft
        synthesis) belong to Phase 5c.

        Args:
            topic: One-sentence research question or topic.
            context: Optional longer project description.
            llm: An LLM implementation. If None, constructs an AnthropicLLM.
            per_theme_limit: Max search results per theme.
            max_themes: Soft cap on themes the LLM is asked to produce.
            screen: If True, run LLM relevance screening after search.
            drop_irrelevant: If True (and screen=True), drop IRRELEVANT papers.

        Returns:
            A SearchResult with all the standard fields plus per_theme_counts.
            Each ingested paper has `extra["relevance"]` and
            `extra["relevance_reason"]` populated when screening was used.
        """
        from .decompose import decompose_topic
        from .screen import screen_papers

        if llm is None:
            from .llm import AnthropicLLM

            llm = AnthropicLLM()

        # Stage 0: ingest seeds into the store first so they exist as ground truth.
        # Seeds also dedup against future search results via paper_id matching.
        seed_doi_set: set[str] = set()
        if seeds:
            ingest_papers(self.db, seeds)
            seed_doi_set = {s.doi for s in seeds if s.doi}

        themes = decompose_topic(
            topic=topic,
            context=context,
            llm=llm,
            max_themes=max_themes,
        )
        if not themes:
            raise RuntimeError(
                "Theme decomposition returned no themes. Check the topic and context."
            )

        query = SearchQuery(themes=themes, limit=per_theme_limit)
        timestamp = datetime.now(tz=timezone.utc)
        papers, per_theme_counts = self._search_themed(query)

        # Drop search results that already exist as seeds (they're already ingested)
        if seed_doi_set:
            papers = [p for p in papers if p.doi not in seed_doi_set]

        if screen and papers:
            papers = screen_papers(
                papers=papers,
                topic=topic,
                context=context,
                llm=llm,
                drop_irrelevant=drop_irrelevant,
                seeds=seeds,
            )

        verification_attempted = 0
        verification_succeeded = 0
        if self.verify_dois:
            enriched: list[Paper] = []
            for paper in papers:
                if paper.doi:
                    verification_attempted += 1
                    enriched_paper = self.verifier.enrich_paper(paper)
                    if enriched_paper.verified:
                        verification_succeeded += 1
                    enriched.append(enriched_paper)
                else:
                    enriched.append(paper)
            papers = enriched

        ingested_count, duplicates_skipped = ingest_papers(self.db, papers)

        return SearchResult(
            query=query,
            backend=_backend_name(self.search_client),
            timestamp=timestamp,
            total_returned=len(papers),
            papers=papers,
            ingested_count=ingested_count,
            duplicates_skipped=duplicates_skipped,
            verification_attempted=verification_attempted,
            verification_succeeded=verification_succeeded,
            per_theme_counts=per_theme_counts,
        )
