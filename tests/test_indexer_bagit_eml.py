"""Tests for the DataONE BagIt + EML path of e2sa.data.indexing.index_package.

Runs against a small fixture in tests/fixtures/indexer_bagit_pkg/. Also
includes an opt-in test against the real Kanevskiy package on disk if present.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from e2sa.catalog import open_catalog, register_dataset
from e2sa.data.indexing import detect_standard, index_package

FIXTURE_PKG = Path(__file__).parent / "fixtures" / "indexer_bagit_pkg"
REAL_KANEVSKIY = (
    Path(__file__).resolve().parents[1]
    / "projects" / "spade" / "data" / "raw"
    / "arctic_data_center" / "kanevskiy_2024_cryostratigraphy"
)


def _seed(conn, dataset_id: str = "kanevskiy_test") -> None:
    register_dataset(
        conn,
        dataset_id=dataset_id,
        source_id="kanevskiy_2024_cryostratigraphy",
        name="Kanevskiy cryostratigraphy (fixture)",
        adapter_version="0.0.0",
        schema_version="0.1.0",
    )


def test_detect_standard_bagit() -> None:
    assert detect_standard(FIXTURE_PKG) == "dataone_bagit"


def test_index_package_enumerates_bagit_files(tmp_path: Path) -> None:
    conn = open_catalog(tmp_path / "cat.duckdb")
    _seed(conn)

    result = index_package(conn, "kanevskiy_test", FIXTURE_PKG)
    assert result.standard == "dataone_bagit"
    assert result.n_files == 5  # bagit.txt + manifest + 2 data csvs + EML

    rows = conn.execute(
        "SELECT relative_path, role, format FROM package_files ORDER BY relative_path"
    ).fetchall()
    paths = {r[0]: (r[1], r[2]) for r in rows}
    assert paths["bagit.txt"] == ("bagit", "text")
    assert paths["manifest-md5.txt"] == ("bagit", "text")
    assert paths["data/Sample_Site_July_2024.csv"] == ("data", "csv")
    assert paths["data/Other_Site_June_2024.csv"] == ("data", "csv")
    assert paths["metadata/science-metadata.xml"] == ("eml", "xml")

    conn.close()


def test_eml_attributes_mapped_to_enum(tmp_path: Path) -> None:
    """EIC, %  and VMC, % map to ice/water content; GMC and Notes stay raw."""
    conn = open_catalog(tmp_path / "cat.duckdb")
    _seed(conn)
    index_package(conn, "kanevskiy_test", FIXTURE_PKG)

    rows = conn.execute(
        """
        SELECT variable, raw_name, unit, parseable, crs_tier
        FROM dataset_variables
        ORDER BY variable
        """
    ).fetchall()
    by_var = {r[0]: r for r in rows}

    assert by_var["excess_ice_content"][1].startswith("EIC")
    assert by_var["excess_ice_content"][2] == "percent"
    assert by_var["excess_ice_content"][3] is True
    assert by_var["excess_ice_content"][4] == "assumed-wgs84"

    assert by_var["volumetric_water_content"][1].startswith("VMC")
    assert by_var["volumetric_water_content"][3] is True

    assert by_var["GMC, %"][3] is False  # unmapped
    assert by_var["Borehole"][3] is False  # unmapped
    assert by_var["Notes"][3] is False  # unmapped

    conn.close()


def test_eml_fuzzy_filename_match(tmp_path: Path) -> None:
    """EML 'Other-Site-June-2024.csv' (hyphens) matches disk
    'Other_Site_June_2024.csv' (underscores)."""
    conn = open_catalog(tmp_path / "cat.duckdb")
    _seed(conn)
    index_package(conn, "kanevskiy_test", FIXTURE_PKG)

    other_file_id = conn.execute(
        "SELECT file_id FROM package_files WHERE relative_path = 'data/Other_Site_June_2024.csv'"
    ).fetchone()[0]

    eic_for_other = conn.execute(
        """
        SELECT COUNT(*) FROM dataset_variables
        WHERE variable = 'excess_ice_content' AND file_id = ?
        """,
        [other_file_id],
    ).fetchone()[0]
    assert eic_for_other == 1

    conn.close()


def test_index_package_idempotent_bagit(tmp_path: Path) -> None:
    conn = open_catalog(tmp_path / "cat.duckdb")
    _seed(conn)
    index_package(conn, "kanevskiy_test", FIXTURE_PKG)
    index_package(conn, "kanevskiy_test", FIXTURE_PKG)

    n_files = conn.execute("SELECT COUNT(*) FROM package_files").fetchone()[0]
    n_vars = conn.execute("SELECT COUNT(*) FROM dataset_variables").fetchone()[0]
    assert n_files == 5
    assert n_vars > 0

    conn.close()


def test_bagit_md5_integrity_clean(tmp_path: Path) -> None:
    """Fixture manifest matches disk md5s, so md5_mismatches must be empty."""
    conn = open_catalog(tmp_path / "cat.duckdb")
    _seed(conn)
    result = index_package(conn, "kanevskiy_test", FIXTURE_PKG)
    assert result.md5_mismatches == []
    conn.close()


def test_bagit_md5_integrity_detects_tampered_manifest(tmp_path: Path) -> None:
    """Copy the fixture, swap in a manifest with a wrong md5, verify the indexer catches it."""
    import shutil

    pkg = tmp_path / "pkg"
    shutil.copytree(FIXTURE_PKG, pkg)
    (pkg / "manifest-md5.txt").write_text(
        "deadbeef00000000000000000000beef data/Sample_Site_July_2024.csv\n",
        encoding="utf-8",
    )

    conn = open_catalog(tmp_path / "cat.duckdb")
    _seed(conn)
    result = index_package(conn, "kanevskiy_test", pkg)

    assert result.md5_mismatches == ["data/Sample_Site_July_2024.csv"]
    conn.close()


@pytest.mark.skipif(
    not REAL_KANEVSKIY.is_dir(),
    reason="Real Kanevskiy package not on disk (gitignored); skip live test.",
)
def test_real_kanevskiy_md5_integrity_clean(tmp_path: Path) -> None:
    """The real Kanevskiy download should have no md5 mismatches against its manifest."""
    conn = open_catalog(tmp_path / "cat.duckdb")
    register_dataset(
        conn,
        dataset_id="kanevskiy_2024_cryostratigraphy",
        source_id="kanevskiy_2024_cryostratigraphy",
        adapter_version="0.0.0",
        schema_version="0.1.0",
    )
    result = index_package(conn, "kanevskiy_2024_cryostratigraphy", REAL_KANEVSKIY)
    assert result.md5_mismatches == [], (
        f"md5 mismatches in real Kanevskiy download: {result.md5_mismatches}"
    )
    conn.close()


@pytest.mark.skipif(
    not REAL_KANEVSKIY.is_dir(),
    reason="Real Kanevskiy package not on disk (gitignored); skip live test.",
)
def test_index_package_against_real_kanevskiy(tmp_path: Path) -> None:
    """Opt-in: runs against the actual Kanevskiy download if present."""
    conn = open_catalog(tmp_path / "cat.duckdb")
    register_dataset(
        conn,
        dataset_id="kanevskiy_2024_cryostratigraphy",
        source_id="kanevskiy_2024_cryostratigraphy",
        name="Kanevskiy 2024 (real download)",
        adapter_version="0.0.0",
        schema_version="0.1.0",
    )
    result = index_package(conn, "kanevskiy_2024_cryostratigraphy", REAL_KANEVSKIY)

    assert result.standard == "dataone_bagit"
    assert result.n_files >= 40  # 22 CSV + 22 PDF + BagIt files + EML/sysmeta

    eic_hits = conn.execute(
        "SELECT COUNT(*) FROM dataset_variables WHERE variable = 'excess_ice_content'"
    ).fetchone()[0]
    assert eic_hits >= 10  # 22 dataTables, most carry EIC, %

    conn.close()
