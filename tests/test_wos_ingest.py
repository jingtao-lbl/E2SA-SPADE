"""Unit tests for WoS field-tagged plain text parser and ingestion."""
from __future__ import annotations

from pathlib import Path

import pytest

from e2sa.agents.litreview.wos_ingest import (
    ingest_wos_export,
    parse_wos_file,
)
from e2sa.rag.store import open_store

FIXTURES = Path(__file__).parent / "fixtures"
REAL_SPADE_EXPORT = (
    Path(__file__).parent.parent / "projects" / "spade" / "references" / "savedrecs.txt"
)


# --- Fixture parsing ---


class TestParseWosFile:
    def test_parses_three_records_from_fixture(self) -> None:
        papers = parse_wos_file(FIXTURES / "wos_sample.txt")
        assert len(papers) == 3

    def test_first_record_fields(self) -> None:
        papers = parse_wos_file(FIXTURES / "wos_sample.txt")
        webb = papers[0]
        assert webb.doi == "10.5194/essd-2025-557"
        assert webb.paper_id == "10.5194/essd-2025-557"
        assert "Comprehensive Database" in webb.title
        assert webb.year == 2025
        assert webb.citation_count == 5
        assert webb.venue == "Earth System Science Data Discussions"
        assert webb.source_backend == "wos"
        assert webb.verified is True
        assert "Hailey Webb" in webb.authors or "Webb, Hailey" in webb.authors

    def test_multiline_title_joined(self) -> None:
        papers = parse_wos_file(FIXTURES / "wos_sample.txt")
        assert "Across Alaska" in papers[0].title
        assert papers[0].title.count("\n") == 0

    def test_multiline_abstract_joined(self) -> None:
        papers = parse_wos_file(FIXTURES / "wos_sample.txt")
        abstract = papers[0].abstract or ""
        assert "19,540 labeled locations" in abstract
        assert "hazard." in abstract
        # No unescaped newlines remain in the joined abstract
        assert abstract.count("\n") == 0

    def test_book_chapter_no_doi_uses_wos_uid(self) -> None:
        papers = parse_wos_file(FIXTURES / "wos_sample.txt")
        smith = papers[1]
        assert smith.doi is None
        assert smith.paper_id.startswith("wos:")
        assert "WOS:000999999999001" in smith.paper_id
        assert smith.extra["document_type"] == "Book Chapter"

    def test_missing_abstract_is_none(self) -> None:
        papers = parse_wos_file(FIXTURES / "wos_sample.txt")
        anon = papers[2]
        assert anon.abstract is None

    def test_wos_specific_fields_in_extra(self) -> None:
        papers = parse_wos_file(FIXTURES / "wos_sample.txt")
        webb = papers[0]
        assert webb.extra.get("is_wos") is True
        assert "permafrost" in webb.extra.get("keywords_author", "").lower()
        assert "Geosciences" in webb.extra.get("wos_categories", "")
        assert webb.extra.get("publication_type") == "J"

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            parse_wos_file(tmp_path / "nope.txt")


# --- Real SPADE export ---


class TestParseRealSpadeExport:
    def test_parses_all_37_records(self) -> None:
        if not REAL_SPADE_EXPORT.exists():
            pytest.skip("Real SPADE savedrecs.txt not present")
        papers = parse_wos_file(REAL_SPADE_EXPORT)
        assert len(papers) == 37

    def test_all_records_have_titles(self) -> None:
        if not REAL_SPADE_EXPORT.exists():
            pytest.skip("Real SPADE savedrecs.txt not present")
        papers = parse_wos_file(REAL_SPADE_EXPORT)
        for p in papers:
            assert p.title
            assert p.title != "(no title)"

    def test_most_records_have_dois(self) -> None:
        if not REAL_SPADE_EXPORT.exists():
            pytest.skip("Real SPADE savedrecs.txt not present")
        papers = parse_wos_file(REAL_SPADE_EXPORT)
        with_doi = [p for p in papers if p.doi]
        # At least 30 of 37 should have DOIs (book chapters may not)
        assert len(with_doi) >= 30

    def test_all_records_have_abstract_or_year(self) -> None:
        if not REAL_SPADE_EXPORT.exists():
            pytest.skip("Real SPADE savedrecs.txt not present")
        papers = parse_wos_file(REAL_SPADE_EXPORT)
        for p in papers:
            assert p.year is not None, f"Missing year: {p.title}"

    def test_all_wos_uid_present(self) -> None:
        if not REAL_SPADE_EXPORT.exists():
            pytest.skip("Real SPADE savedrecs.txt not present")
        papers = parse_wos_file(REAL_SPADE_EXPORT)
        for p in papers:
            assert p.extra.get("wos_uid", "").startswith("WOS:")


# --- Ingestion ---


class TestIngestWosExport:
    def test_ingests_to_lance_store(self, tmp_path: Path) -> None:
        db = open_store(tmp_path / "lance")
        result = ingest_wos_export(db, FIXTURES / "wos_sample.txt")
        assert result.records_parsed == 3
        assert result.ingested == 3
        assert result.duplicates_skipped == 0

    def test_reports_doi_vs_uid_split(self, tmp_path: Path) -> None:
        db = open_store(tmp_path / "lance")
        result = ingest_wos_export(db, FIXTURES / "wos_sample.txt")
        assert result.records_with_doi == 1  # only Webb has DOI in fixture
        assert result.records_with_wos_uid == 2  # Smith and Anonymous

    def test_reports_abstract_counts(self, tmp_path: Path) -> None:
        db = open_store(tmp_path / "lance")
        result = ingest_wos_export(db, FIXTURES / "wos_sample.txt")
        assert result.records_with_abstract == 2  # Webb and Smith
        assert result.records_with_year == 3

    def test_dry_run_does_not_write(self, tmp_path: Path) -> None:
        db = open_store(tmp_path / "lance")
        result = ingest_wos_export(
            db, FIXTURES / "wos_sample.txt", dry_run=True
        )
        assert result.records_parsed == 3
        assert result.ingested == 0

        from e2sa.agents.litreview.ingest import existing_chunk_ids

        assert existing_chunk_ids(db) == set()

    def test_dedup_on_reingest(self, tmp_path: Path) -> None:
        db = open_store(tmp_path / "lance")
        first = ingest_wos_export(db, FIXTURES / "wos_sample.txt")
        second = ingest_wos_export(db, FIXTURES / "wos_sample.txt")
        assert first.ingested == 3
        assert second.ingested == 0
        assert second.duplicates_skipped == 3

    def test_missing_file_in_result(self, tmp_path: Path) -> None:
        db = open_store(tmp_path / "lance")
        result = ingest_wos_export(db, tmp_path / "nope.txt")
        assert result.records_parsed == 0
        assert result.ingested == 0
        assert len(result.errors) == 1
