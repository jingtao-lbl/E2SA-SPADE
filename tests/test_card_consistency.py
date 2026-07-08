"""Enforce that every built adapter's citation is consistent with its source card.

Intent: the human-facing source card and the machine-facing adapter citation are
two copies of the same attribution, and SPADE ships adapters (not data), so this
attribution is what travels with each source. If they drift (a card missing the
adapter's DOI or first author, or a new adapter with no card), assembled data is
under-attributed. This test fails loud on that drift, and on any registered adapter
that has no card mapping in the SPADE runner.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from e2sa.data.card_consistency import extract_dois, first_author_surname

_TOOL = Path(__file__).resolve().parents[1] / "projects/spade/tools/check_card_consistency.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("spade_card_check", _TOOL)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_every_adapter_citation_matches_its_card():
    findings = _load_runner().run()
    errors = [str(f) for f in findings if f.is_error]
    assert not errors, "card <-> adapter citation drift:\n" + "\n".join(errors)


def test_every_registered_adapter_has_a_card_mapping():
    from e2sa.data.registry import ADAPTER_REGISTRY

    mapping = _load_runner().CARD_BY_SOURCE_ID
    unmapped = sorted(set(ADAPTER_REGISTRY) - set(mapping))
    assert not unmapped, f"adapters with no source card mapped: {unmapped}"


def test_doi_extraction_strips_prefixes_and_trailing_punctuation():
    assert extract_dois("see https://doi.org/10.1594/PANGAEA.972777.") == ["10.1594/PANGAEA.972777"]
    assert extract_dois("doi:10.5194/essd-18-3147-2026 (2026)") == ["10.5194/essd-18-3147-2026"]


def test_first_author_surname():
    assert first_author_surname("Streletskiy, Dmitry A; CALM") == "Streletskiy"
    assert first_author_surname("Sloan V; Liebig J") == "Sloan"
