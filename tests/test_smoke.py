"""Phase 0 smoke test. Confirms the core modules import and initialize."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from e2sa import __version__
from e2sa.catalog import open_catalog
from e2sa.rag import list_table_names, open_store
from e2sa.schema import (
    SCHEMA_VERSION,
    Observation,
    ObservationType,
    Provenance,
    Variable,
)


def test_version_exposed() -> None:
    assert __version__
    assert SCHEMA_VERSION


def test_observation_roundtrip() -> None:
    prov = Provenance(
        source_id="calm",
        source_url="https://example.invalid/calm",
        access_timestamp=datetime(2026, 4, 11, tzinfo=UTC),
        content_checksum="deadbeef",
        license="CC-BY-4.0",
        adapter_version="0.0.1",
    )
    obs = Observation(
        obs_id="calm_site001_2024",
        obs_type=ObservationType.POINT,
        variable=Variable.ACTIVE_LAYER_THICKNESS,
        value=0.65,
        unit="m",
        latitude=68.6,
        longitude=-149.6,
        depth_m=None,
        provenance=prov,
    )
    assert obs.variable == Variable.ACTIVE_LAYER_THICKNESS
    assert obs.latitude == 68.6
    assert obs.provenance.schema_version == SCHEMA_VERSION


def test_catalog_opens(tmp_path: Path) -> None:
    conn = open_catalog(tmp_path / "catalog.duckdb")
    tables = {row[0] for row in conn.execute("SHOW TABLES").fetchall()}
    assert {"datasets", "downloads", "observations"} <= tables
    conn.close()


def test_lance_store_opens(tmp_path: Path) -> None:
    db = open_store(tmp_path / "lance")
    assert "papers" in list_table_names(db)
