"""Tests for Phase 5b LLM-orchestrated review pipeline.

Uses FakeLLM with canned JSON responses so all tests are offline and
deterministic. Live behavior is exercised separately via the CLI in
the dev log.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from e2sa.agents.litreview import (
    FakeLLM,
    LitReviewAgent,
    Paper,
    SearchQuery,
    decompose_topic,
    screen_papers,
)

# --- decompose_topic ---


class TestDecomposeTopic:
    def test_parses_clean_json_array(self) -> None:
        llm = FakeLLM(
            responses=[
                '["permafrost ground ice", "thermokarst Alaska", "InSAR subsidence"]'
            ]
        )
        themes = decompose_topic("test topic", llm=llm)
        assert themes == ["permafrost ground ice", "thermokarst Alaska", "InSAR subsidence"]

    def test_parses_json_with_code_fence(self) -> None:
        llm = FakeLLM(
            responses=[
                '```json\n["theme A", "theme B"]\n```'
            ]
        )
        themes = decompose_topic("test", llm=llm)
        assert themes == ["theme A", "theme B"]

    def test_parses_json_with_trailing_text(self) -> None:
        llm = FakeLLM(
            responses=[
                '["one", "two"]\n\nThese cover the main areas.'
            ]
        )
        themes = decompose_topic("test", llm=llm)
        assert themes == ["one", "two"]

    def test_strips_empty_strings(self) -> None:
        llm = FakeLLM(responses=['["good theme", "", "  ", "another good"]'])
        themes = decompose_topic("test", llm=llm)
        assert themes == ["good theme", "another good"]

    def test_passes_context_to_prompt(self) -> None:
        llm = FakeLLM(responses=['["a", "b"]'])
        decompose_topic(
            "test topic",
            context="Project context goes here.",
            llm=llm,
        )
        last_user = llm.call_log[-1][1]
        assert "Project context goes here." in last_user
        assert "test topic" in last_user

    def test_truncates_long_context(self) -> None:
        llm = FakeLLM(responses=['["x"]'])
        long_context = "A" * 20_000
        decompose_topic("topic", context=long_context, llm=llm)
        last_user = llm.call_log[-1][1]
        assert "[truncated]" in last_user
        assert len(last_user) < 15_000

    def test_invalid_json_raises(self) -> None:
        llm = FakeLLM(responses=["not json at all"])
        with pytest.raises(ValueError):
            decompose_topic("test", llm=llm)


# --- screen_papers ---


def _paper(idx: int, title: str, abstract: str = "") -> Paper:
    return Paper(
        paper_id=f"10.1234/p{idx}",
        doi=f"10.1234/p{idx}",
        title=title,
        abstract=abstract,
        source_backend="fake",
    )


class TestScreenPapers:
    def test_drops_irrelevant_by_default(self) -> None:
        papers = [
            _paper(1, "Paper A", "Permafrost ice content study"),
            _paper(2, "Paper B", "Brucellosis in cattle"),
            _paper(3, "Paper C", "InSAR ground deformation"),
        ]
        rating_response = """[
            {"index": 1, "relevance": "HIGH", "reason": "directly on topic"},
            {"index": 2, "relevance": "IRRELEVANT", "reason": "off topic"},
            {"index": 3, "relevance": "MEDIUM", "reason": "methodology"}
        ]"""
        llm = FakeLLM(responses=[rating_response])
        result = screen_papers(papers, topic="permafrost ice", llm=llm)
        assert len(result) == 2
        relevances = {p.extra["relevance"] for p in result}
        assert relevances == {"HIGH", "MEDIUM"}

    def test_keeps_irrelevant_when_flag_off(self) -> None:
        papers = [_paper(1, "X"), _paper(2, "Y")]
        rating_response = """[
            {"index": 1, "relevance": "HIGH", "reason": "yes"},
            {"index": 2, "relevance": "IRRELEVANT", "reason": "no"}
        ]"""
        llm = FakeLLM(responses=[rating_response])
        result = screen_papers(
            papers, topic="t", llm=llm, drop_irrelevant=False
        )
        assert len(result) == 2

    def test_attaches_relevance_to_extra(self) -> None:
        papers = [_paper(1, "X")]
        llm = FakeLLM(responses=['[{"index": 1, "relevance": "HIGH", "reason": "great"}]'])
        result = screen_papers(papers, topic="t", llm=llm)
        assert result[0].extra["relevance"] == "HIGH"
        assert result[0].extra["relevance_reason"] == "great"

    def test_batches_papers(self) -> None:
        papers = [_paper(i, f"P{i}") for i in range(25)]
        # 25 papers / batch_size 10 = 3 batches
        responses = []
        for batch_size in [10, 10, 5]:
            ratings = [
                {"index": i + 1, "relevance": "MEDIUM", "reason": "ok"}
                for i in range(batch_size)
            ]
            import json

            responses.append(json.dumps(ratings))
        llm = FakeLLM(responses=responses)
        result = screen_papers(papers, topic="t", llm=llm, batch_size=10)
        assert len(result) == 25
        assert len(llm.call_log) == 3

    def test_handles_malformed_response(self) -> None:
        papers = [_paper(1, "X"), _paper(2, "Y")]
        llm = FakeLLM(responses=["not a json array"])
        result = screen_papers(
            papers, topic="t", llm=llm, drop_irrelevant=False
        )
        # Falls back to LOW for all, none dropped (none rated IRRELEVANT)
        assert len(result) == 2
        assert all(p.extra["relevance"] == "LOW" for p in result)


# --- do_themed_review end-to-end with FakeLLM and FakeSearchClient ---


class FakeReviewSearchClient:
    """Fake search client with one paper per query."""

    def search_papers(self, query: SearchQuery):
        # Return one paper named after the query
        return [
            Paper(
                paper_id=f"10.1234/{query.query.replace(' ', '_')}",
                doi=f"10.1234/{query.query.replace(' ', '_')}",
                title=f"Paper for {query.query}",
                abstract=f"Abstract about {query.query}",
                source_backend="fake_review",
            )
        ]


class TestDoThemedReview:
    def test_full_pipeline_with_fakes(self, tmp_path: Path) -> None:
        # FakeLLM needs:
        # 1. One response for decomposition (3 themes)
        # 2. One response for screening (3 papers in one batch)
        decompose_response = '["theme one", "theme two", "theme three"]'
        screen_response = """[
            {"index": 1, "relevance": "HIGH", "reason": "good"},
            {"index": 2, "relevance": "MEDIUM", "reason": "ok"},
            {"index": 3, "relevance": "IRRELEVANT", "reason": "no"}
        ]"""
        llm = FakeLLM(responses=[decompose_response, screen_response])

        agent = LitReviewAgent(
            store_path=tmp_path / "lance",
            search_client=FakeReviewSearchClient(),
            verify_dois=False,
        )

        result = agent.do_themed_review(
            topic="test topic",
            context="some context",
            llm=llm,
            per_theme_limit=1,
        )

        # 3 themes -> 3 papers, screening drops 1, leaving 2
        assert len(result.query.themes) == 3
        assert result.total_returned == 2
        assert result.ingested_count == 2
        assert all(p.extra.get("relevance") in {"HIGH", "MEDIUM"} for p in result.papers)

    def test_skips_screening_when_flag_off(self, tmp_path: Path) -> None:
        llm = FakeLLM(responses=['["a", "b"]'])  # only decompose
        agent = LitReviewAgent(
            store_path=tmp_path / "lance",
            search_client=FakeReviewSearchClient(),
            verify_dois=False,
        )
        result = agent.do_themed_review(
            topic="t",
            llm=llm,
            per_theme_limit=1,
            screen=False,
        )
        # 2 themes -> 2 papers, no screening
        assert result.total_returned == 2
        assert all("relevance" not in p.extra for p in result.papers)

    def test_per_theme_counts_in_result(self, tmp_path: Path) -> None:
        llm = FakeLLM(
            responses=[
                '["alpha", "beta"]',
                """[
                    {"index": 1, "relevance": "HIGH", "reason": "x"},
                    {"index": 2, "relevance": "HIGH", "reason": "y"}
                ]""",
            ]
        )
        agent = LitReviewAgent(
            store_path=tmp_path / "lance",
            search_client=FakeReviewSearchClient(),
            verify_dois=False,
        )
        result = agent.do_themed_review(
            topic="t",
            llm=llm,
            per_theme_limit=1,
        )
        assert "alpha" in result.per_theme_counts
        assert "beta" in result.per_theme_counts
