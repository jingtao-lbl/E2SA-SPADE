#!/usr/bin/env python3
"""SPADE runner for the card <-> adapter citation consistency validator.

Holds the SPADE-specific mapping from each registered adapter's source_id to the
source card (`projects/spade/data/sources/<card>.md`) that documents it, then runs
the generic engine in `e2sa.data.card_consistency`. When a new adapter is added to
the registry, add its card here (or the validator fails, by design).

Run it:

    python projects/spade/tools/check_card_consistency.py

Exit code is 0 when every adapter's citation is consistent with its card, 1 otherwise.
The test `tests/test_card_consistency.py` imports `run()` so CI enforces the same check.
"""
from __future__ import annotations

import sys
from pathlib import Path

from e2sa.data.card_consistency import Finding, check_card_citation_consistency, format_report

#: source_id (ADAPTER_REGISTRY key) -> source-card basename under SOURCES_DIR.
#: Cards are project-named, not data-center-named, so the mapping is explicit.
CARD_BY_SOURCE_ID: dict[str, str] = {
    "calm_alt": "calm.md",
    "gtnp_magt": "gtnp.md",
    "webb_2026_alaska_thaw_db": "alaska_thaw_db.md",
    "above_stdm": "above.md",
    "sloan_2014_barrow_soil": "ngee_arctic.md",
    "kanevskiy_2024_cryostratigraphy": "kanevskiy_cryostratigraphy.md",
    "tsp_north_america_ground_temperature": "tsp_north_america.md",
}

SOURCES_DIR: Path = Path(__file__).resolve().parents[1] / "data" / "sources"


def run() -> list[Finding]:
    """Run the consistency check against the SPADE source cards."""
    return check_card_citation_consistency(SOURCES_DIR, CARD_BY_SOURCE_ID)


def main() -> int:
    findings = run()
    print(format_report(findings))
    return 1 if any(f.is_error for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
