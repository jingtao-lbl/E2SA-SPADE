"""Test catalog integration: adapter -> parse -> ingest into DuckDB."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from e2sa.catalog import ingest_observations, open_catalog, register_dataset, register_download
from e2sa.data.adapters.calm_alt import CALMAdapter
from e2sa.data.base import FetchResult
from e2sa.schema import Observation, ObservationType, Provenance, Variable

FIXTURES = Path(__file__).parent / "fixtures"


def _obs(obs_id: str, value: float = 1.0) -> Observation:
    """Minimal valid Observation with a controllable obs_id + value."""
    return Observation(
        obs_id=obs_id,
        obs_type=ObservationType.POINT,
        variable=Variable.SOIL_TEMPERATURE,
        value=value,
        unit="degC",
        latitude=70.0,
        longitude=-150.0,
        provenance=Provenance(
            source_id="test",
            access_timestamp=datetime(2026, 6, 23, tzinfo=UTC),
            content_checksum="x",
            adapter_version="0.1.0",
        ),
    )


def test_calm_end_to_end_into_catalog(tmp_path: Path) -> None:
    """Parse CALM fixture, ingest into catalog, query back."""
    conn = open_catalog(tmp_path / "test_catalog.duckdb")

    register_dataset(
        conn,
        dataset_id="calm_test",
        source_id="calm",
        name="CALM test fixture",
        adapter_version="0.1.0",
        schema_version="0.1.0",
    )

    fr = FetchResult(
        dataset_id="calm_test",
        local_path=FIXTURES / "calm_sample.tsv",
        bytes_downloaded=1000,
        access_timestamp=datetime(2026, 4, 12, tzinfo=UTC),
        content_checksum="fixture_checksum",
        source_url="https://test.invalid",
    )
    register_download(conn, fr)

    adapter = CALMAdapter(raw_dir=tmp_path)
    observations = adapter.parse_to_schema(fr)
    count = ingest_observations(conn, observations, dataset_id="calm_test")

    assert count == len(observations)
    assert count > 0

    result = conn.execute("SELECT COUNT(*) FROM observations").fetchone()
    assert result[0] == count

    result = conn.execute(
        "SELECT COUNT(*) FROM observations WHERE variable = 'active_layer_thickness'"
    ).fetchone()
    assert result[0] == count

    result = conn.execute("SELECT COUNT(*) FROM datasets").fetchone()
    assert result[0] == 1

    result = conn.execute("SELECT COUNT(*) FROM downloads").fetchone()
    assert result[0] == 1

    conn.close()


def test_ingest_dedupes_duplicate_obs_id(tmp_path: Path) -> None:
    """Records sharing an obs_id collapse to one row (last wins), no PK conflict.

    Encodes why dedupe matters: the plain-INSERT append path would raise on a
    duplicate obs_id; silently swallowing duplicates is also how the GTN-P
    obs_id-collision bug hid, so the drop is real and last-wins is deterministic.
    """
    conn = open_catalog(tmp_path / "c.duckdb")
    obs = [_obs("dup", value=1.0), _obs("dup", value=2.0), _obs("other", value=3.0)]

    count = ingest_observations(conn, obs, dataset_id="d1")

    assert count == 2  # "dup" collapsed to one
    dup = conn.execute("SELECT value FROM observations WHERE obs_id = 'dup'").fetchall()
    assert dup == [(2.0,)]  # last wins
    assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 2
    conn.close()


def test_ingest_replace_is_idempotent_no_stale_rows(tmp_path: Path) -> None:
    """Re-ingesting a dataset replaces its rows wholesale, leaving no stale rows.

    Encodes the dataset-grain idempotency contract: re-acquiring a dataset must
    reflect exactly the new parse (delete-then-append), not accumulate or strand
    rows that the old INSERT OR REPLACE would have left behind.
    """
    conn = open_catalog(tmp_path / "c.duckdb")
    ingest_observations(conn, [_obs("a"), _obs("b"), _obs("c")], dataset_id="d1")

    count = ingest_observations(conn, [_obs("a", value=9.0), _obs("b")], dataset_id="d1")

    assert count == 2
    ids = {r[0] for r in conn.execute(
        "SELECT obs_id FROM observations WHERE dataset_id = 'd1'"
    ).fetchall()}
    assert ids == {"a", "b"}  # "c" removed, no stale row
    assert conn.execute("SELECT value FROM observations WHERE obs_id = 'a'").fetchone()[0] == 9.0
    conn.close()


def test_ingest_isolates_datasets(tmp_path: Path) -> None:
    """Re-ingesting one dataset must not touch another dataset's rows.

    Encodes that the DELETE is dataset-scoped, not a global wipe.
    """
    conn = open_catalog(tmp_path / "c.duckdb")
    ingest_observations(conn, [_obs("a1"), _obs("a2")], dataset_id="dA")
    ingest_observations(conn, [_obs("b1")], dataset_id="dB")

    ingest_observations(conn, [_obs("a1")], dataset_id="dA")  # re-ingest dA only

    n_a = conn.execute("SELECT COUNT(*) FROM observations WHERE dataset_id = 'dA'").fetchone()
    n_b = conn.execute("SELECT COUNT(*) FROM observations WHERE dataset_id = 'dB'").fetchone()
    assert n_a[0] == 1
    assert n_b[0] == 1  # untouched by the dA re-ingest
    conn.close()


def test_ingest_empty_is_noop(tmp_path: Path) -> None:
    """An empty observation list returns 0 and leaves existing rows untouched."""
    conn = open_catalog(tmp_path / "c.duckdb")
    ingest_observations(conn, [_obs("a")], dataset_id="d1")

    count = ingest_observations(conn, [], dataset_id="d1")

    assert count == 0
    assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1  # not wiped
    conn.close()
