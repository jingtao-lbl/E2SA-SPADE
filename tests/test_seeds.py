"""Tests for the seeds loader and integration with do_themed_review."""
from __future__ import annotations

from pathlib import Path

import pytest

from e2sa.agents.litreview import (
    FakeLLM,
    LitReviewAgent,
    Paper,
    SearchQuery,
    load_seeds,
)
from e2sa.agents.litreview.seeds import (
    _extract_from_bibtex,
    _extract_from_csv,
    _extract_from_freetext,
)

# --- Test fixtures ---


SAMPLE_MARKDOWN = """\
# SPADE Seed References

## Permafrost data sources

- Webb, H. et al. 2025. **A Comprehensive Database of Thawing Permafrost Locations Across Alaska**. Earth Syst. Sci. Data Discuss. doi:10.5194/essd-2025-557
- Olefeldt, D. et al. 2016. *Circumpolar distribution and carbon storage of thermokarst landscapes*. Nature Communications 7, 13043. https://doi.org/10.1038/ncomms13043

## Mapping methods

- Bartsch et al. 2021. **Top-of-permafrost ground ice indicated by remotely sensed late-season subsidence**. The Cryosphere 15, 2041. doi:10.5194/tc-15-2041-2021
- Ran et al. 2022. New high-resolution estimates of the permafrost thermal state. ESSD 14, 865. https://doi.org/10.5194/essd-14-865-2022

## Duplicates and noise

This line has 10.5194/tc-15-2041-2021 again (should dedup).
And a non-DOI mention of "permafrost".
"""


SAMPLE_CSV = """doi,title,year
10.5194/essd-2025-557,Webb 2025 thaw db,2025
10.1038/ncomms13043,Olefeldt thermokarst,2016
"""


SAMPLE_BIBTEX = """\
@article{webb2025,
  doi = {10.5194/essd-2025-557},
  title = {A Comprehensive Database of Thawing Permafrost Locations Across Alaska},
  year = {2025}
}

@article{bartsch2021,
  doi = {10.5194/tc-15-2041-2021},
  title = {Top-of-permafrost ground ice indicated by remotely sensed late-season subsidence},
  year = {2021}
}
"""


# --- DOI extraction ---


class TestExtractFromFreetext:
    def test_finds_dois_in_markdown(self, tmp_path: Path) -> None:
        f = tmp_path / "Reference.md"
        f.write_text(SAMPLE_MARKDOWN)
        dois, titles = _extract_from_freetext(f)
        assert "10.5194/essd-2025-557" in dois
        assert "10.1038/ncomms13043" in dois
        assert "10.5194/tc-15-2041-2021" in dois
        assert "10.5194/essd-14-865-2022" in dois

    def test_extracts_some_titles(self, tmp_path: Path) -> None:
        f = tmp_path / "Reference.md"
        f.write_text(SAMPLE_MARKDOWN)
        dois, titles = _extract_from_freetext(f)
        # Bold markdown should be picked up as a title
        assert any("Comprehensive Database" in t for t in titles)


class TestExtractFromCsv:
    def test_csv_dois_and_titles(self, tmp_path: Path) -> None:
        f = tmp_path / "seeds.csv"
        f.write_text(SAMPLE_CSV)
        dois, titles = _extract_from_csv(f)
        assert "10.5194/essd-2025-557" in dois
        assert "10.1038/ncomms13043" in dois
        assert "Webb 2025 thaw db" in titles


class TestExtractFromBibtex:
    def test_bibtex_dois_and_titles(self, tmp_path: Path) -> None:
        f = tmp_path / "seeds.bib"
        f.write_text(SAMPLE_BIBTEX)
        dois, titles = _extract_from_bibtex(f)
        assert "10.5194/essd-2025-557" in dois
        assert "10.5194/tc-15-2041-2021" in dois
        assert any("Comprehensive Database" in t for t in titles)


# --- load_seeds end to end ---


class TestLoadSeeds:
    def test_load_markdown_no_enrichment(self, tmp_path: Path) -> None:
        f = tmp_path / "Reference.md"
        f.write_text(SAMPLE_MARKDOWN)
        seeds = load_seeds(f, enrich=False)
        # 4 unique DOIs (the duplicate was dedup'd)
        assert len(seeds) == 4
        for s in seeds:
            assert s.extra["is_seed"] is True
            assert s.source_backend == "seed"
            assert s.doi
            assert s.paper_id == s.doi

    def test_load_csv(self, tmp_path: Path) -> None:
        f = tmp_path / "seeds.csv"
        f.write_text(SAMPLE_CSV)
        seeds = load_seeds(f, enrich=False)
        assert len(seeds) == 2
        assert all(s.extra["is_seed"] for s in seeds)

    def test_load_bibtex(self, tmp_path: Path) -> None:
        f = tmp_path / "seeds.bib"
        f.write_text(SAMPLE_BIBTEX)
        seeds = load_seeds(f, enrich=False)
        assert len(seeds) == 2

    def test_dedup_within_file(self, tmp_path: Path) -> None:
        f = tmp_path / "Reference.md"
        f.write_text(
            "doi 10.1234/abc once\n"
            "doi 10.1234/abc twice\n"
            "doi 10.1234/abc thrice\n"
        )
        seeds = load_seeds(f, enrich=False)
        assert len(seeds) == 1

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_seeds(tmp_path / "nope.md")


# --- do_themed_review with seeds ---


class _FakeReviewSearchClient:
    def __init__(self, results: list[Paper] | None = None) -> None:
        self._results = results or [
            Paper(
                paper_id="10.9999/new1",
                doi="10.9999/new1",
                title="New paper from search",
                source_backend="fake",
            )
        ]

    def search_papers(self, query: SearchQuery):
        return list(self._results)


class TestDoThemedReviewWithSeeds:
    def test_seeds_are_ingested_first(self, tmp_path: Path) -> None:
        seeds = [
            Paper(
                paper_id="10.1234/seed1",
                doi="10.1234/seed1",
                title="Seed paper one",
                source_backend="seed",
                extra={"is_seed": True},
            )
        ]
        llm = FakeLLM(
            responses=[
                '["theme one"]',
                '[{"index":1,"relevance":"HIGH","reason":"good"}]',
            ]
        )
        agent = LitReviewAgent(
            store_path=tmp_path / "lance",
            search_client=_FakeReviewSearchClient(),
            verify_dois=False,
        )
        result = agent.do_themed_review(
            topic="t",
            llm=llm,
            seeds=seeds,
            per_theme_limit=1,
        )
        # 1 seed + 1 search hit = 2 ingested
        from e2sa.agents.litreview.ingest import existing_chunk_ids

        chunk_ids = existing_chunk_ids(agent.db)
        assert len(chunk_ids) == 2

    def test_search_results_dedup_against_seeds(self, tmp_path: Path) -> None:
        # Search returns the same DOI as the seed
        seeds = [
            Paper(
                paper_id="10.1234/dup",
                doi="10.1234/dup",
                title="Seed",
                source_backend="seed",
                extra={"is_seed": True},
            )
        ]
        same_doi_search = [
            Paper(
                paper_id="10.1234/dup",
                doi="10.1234/dup",
                title="Search result for the same paper",
                source_backend="fake",
            )
        ]
        llm = FakeLLM(responses=['["t1"]'])
        agent = LitReviewAgent(
            store_path=tmp_path / "lance",
            search_client=_FakeReviewSearchClient(results=same_doi_search),
            verify_dois=False,
        )
        result = agent.do_themed_review(
            topic="t",
            llm=llm,
            seeds=seeds,
            per_theme_limit=1,
            screen=False,
        )
        # The search result should have been dropped before screening
        # Only the seed remains
        assert result.total_returned == 0  # no new papers after seed dedup
        from e2sa.agents.litreview.ingest import existing_chunk_ids

        chunk_ids = existing_chunk_ids(agent.db)
        assert len(chunk_ids) == 1  # only the seed was ingested
