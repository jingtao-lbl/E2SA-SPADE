"""Tests for the ESS-DIVE FLMD/dd-CSV path of e2sa.data.indexing.index_package.

Runs against a small fixture in tests/fixtures/indexer_ess_dive_pkg/. Also
includes an opt-in test against the real Barrow package on disk if present.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from e2sa.catalog import open_catalog, register_dataset
from e2sa.data.indexing import _map_variable, detect_standard, index_package
from e2sa.schema import Variable

FIXTURE_PKG = Path(__file__).parent / "fixtures" / "indexer_ess_dive_pkg"
REAL_BARROW = (
    Path(__file__).resolve().parents[1]
    / "projects" / "spade" / "data" / "raw" / "ngee_arctic" / "barrow_soil_2014"
)


def _seed(conn, dataset_id: str = "barrow_test") -> None:
    register_dataset(
        conn,
        dataset_id=dataset_id,
        source_id="ngee_arctic",
        name="NGEE-Arctic Barrow soil-T (fixture)",
        adapter_version="0.0.0",
        schema_version="0.1.0",
    )


def test_detect_standard_ess_dive(tmp_path: Path) -> None:
    assert detect_standard(FIXTURE_PKG) == "ess_dive_dd"


def test_index_package_enumerates_files(tmp_path: Path) -> None:
    conn = open_catalog(tmp_path / "cat.duckdb")
    _seed(conn)

    result = index_package(conn, "barrow_test", FIXTURE_PKG)
    assert result.standard == "ess_dive_dd"
    assert result.n_files == 3  # dd-CSV + data CSV + PDF user-file

    rows = conn.execute(
        "SELECT relative_path, role, format FROM package_files ORDER BY relative_path"
    ).fetchall()
    paths = {r[0]: (r[1], r[2]) for r in rows}
    assert paths["BEO_soil_temperature_30_min_dd.csv"] == ("dictionary", "csv")
    assert paths["BEO_soil_temperature_30_min_2012_2013.csv"] == ("data", "csv")
    assert paths["BEO_soil_properties_user_file.pdf"] == ("readme", "pdf")

    conn.close()


def test_index_package_records_checksums_and_bytes(tmp_path: Path) -> None:
    conn = open_catalog(tmp_path / "cat.duckdb")
    _seed(conn)
    index_package(conn, "barrow_test", FIXTURE_PKG)

    rows = conn.execute(
        "SELECT content_checksum, bytes FROM package_files"
    ).fetchall()
    assert all(len(r[0]) == 64 for r in rows)  # sha256 hex
    assert all(r[1] > 0 for r in rows)

    conn.close()


def test_dd_csv_variables_mapped_and_collapsed(tmp_path: Path) -> None:
    """Three soil_temperature_Ncm raw columns collapse to one SOIL_TEMPERATURE row."""
    conn = open_catalog(tmp_path / "cat.duckdb")
    _seed(conn)
    index_package(conn, "barrow_test", FIXTURE_PKG)

    rows = conn.execute(
        """
        SELECT variable, raw_name, unit, parseable, crs_tier
        FROM dataset_variables
        ORDER BY variable
        """
    ).fetchall()
    by_var = {r[0]: r for r in rows}

    assert "soil_temperature" in by_var
    var, raw_name, unit, parseable, crs_tier = by_var["soil_temperature"]
    assert "soil_temperature_5cm" in raw_name
    assert "soil_temperature_15cm" in raw_name
    assert "soil_temperature_25cm" in raw_name
    assert unit == "degC"
    assert parseable is True
    assert crs_tier == "pdf"

    assert by_var["volumetric_water_content"][1] == "volumetric_soil_moisture"
    assert by_var["volumetric_water_content"][2] == "m3 m-3"
    assert by_var["volumetric_water_content"][3] is True

    assert by_var["active_layer_thickness"][1] == "thaw_depth"
    assert by_var["active_layer_thickness"][3] is True

    assert by_var["plot_ID"][3] is False  # unmapped -> raw name, parseable=false

    conn.close()


def test_variables_linked_to_data_file_not_dd_csv(tmp_path: Path) -> None:
    """Variables should attribute to the prefix-matched data file, not the dd-CSV."""
    conn = open_catalog(tmp_path / "cat.duckdb")
    _seed(conn)
    index_package(conn, "barrow_test", FIXTURE_PKG)

    data_file_id = conn.execute(
        "SELECT file_id FROM package_files WHERE role = 'data'"
    ).fetchone()[0]

    soil_t_file_ids = conn.execute(
        "SELECT file_id FROM dataset_variables WHERE variable = 'soil_temperature'"
    ).fetchall()
    assert soil_t_file_ids == [(data_file_id,)]

    conn.close()


def test_index_package_idempotent(tmp_path: Path) -> None:
    conn = open_catalog(tmp_path / "cat.duckdb")
    _seed(conn)
    index_package(conn, "barrow_test", FIXTURE_PKG)
    index_package(conn, "barrow_test", FIXTURE_PKG)

    n_files = conn.execute("SELECT COUNT(*) FROM package_files").fetchone()[0]
    n_vars = conn.execute("SELECT COUNT(*) FROM dataset_variables").fetchone()[0]
    assert n_files == 3
    assert n_vars > 0

    conn.close()


def test_per_file_missing_sentinel_captured(tmp_path: Path) -> None:
    """The data CSV row should inherit the dd-CSV's declared sentinels (-9999, not_determined)."""
    conn = open_catalog(tmp_path / "cat.duckdb")
    _seed(conn)
    index_package(conn, "barrow_test", FIXTURE_PKG)

    sentinel = conn.execute(
        """
        SELECT missing_sentinel FROM package_files
        WHERE relative_path = 'BEO_soil_temperature_30_min_2012_2013.csv'
        """
    ).fetchone()[0]
    assert sentinel is not None
    assert "-9999" in sentinel
    assert "not_determined" in sentinel

    # The dd-CSV itself and the PDF have no sentinel attribution.
    other_sentinels = conn.execute(
        """
        SELECT missing_sentinel FROM package_files
        WHERE role IN ('dictionary', 'readme')
        """
    ).fetchall()
    assert all(r[0] is None for r in other_sentinels)

    conn.close()


class TestVariableMappingExtensions:
    """Sloan-specific column names that the indexer must catch (per-plot + 30-min files)."""

    def test_bare_temperature_maps_to_soil_temperature(self) -> None:
        """30-min dd-CSV column 'temperature' (not 'soil_temperature')."""
        assert _map_variable("temperature") == Variable.SOIL_TEMPERATURE

    def test_temp_with_unit_suffix_maps_to_soil_temperature(self) -> None:
        """36 per-plot dd-CSV column 'Temp, deg C' should map after suffix strip."""
        assert _map_variable("Temp, deg C") == Variable.SOIL_TEMPERATURE

    def test_temp_alone_maps_to_soil_temperature(self) -> None:
        """Disambiguation note: in this permafrost-data domain, bare 'temp' = soil T."""
        assert _map_variable("temp") == Variable.SOIL_TEMPERATURE
        assert _map_variable("TEMP") == Variable.SOIL_TEMPERATURE

    def test_site_metadata_stays_unmapped(self) -> None:
        """plot_ID, polygon_ID, region, etc. are identifiers, not measurements."""
        for raw in ["plot_ID", "polygon_ID", "region", "locale", "site"]:
            assert _map_variable(raw) is None, f"{raw!r} should not be mapped"


@pytest.mark.skipif(
    not REAL_BARROW.is_dir(),
    reason="Real Barrow package not on disk (gitignored); skip live test.",
)
def test_index_package_against_real_barrow(tmp_path: Path) -> None:
    """Opt-in: runs against the actual NGEE-Arctic Barrow download if present."""
    conn = open_catalog(tmp_path / "cat.duckdb")
    register_dataset(
        conn,
        dataset_id="ngee_barrow_soil_2014",
        source_id="ngee_arctic",
        name="NGEE-Arctic Barrow soil-T 2012-2013 (real download)",
        adapter_version="0.0.0",
        schema_version="0.1.0",
    )
    result = index_package(conn, "ngee_barrow_soil_2014", REAL_BARROW)

    assert result.standard == "ess_dive_dd"
    assert result.n_files >= 5  # 4 CSVs + 1 PDF in the real package

    soil_t = conn.execute(
        "SELECT COUNT(*) FROM dataset_variables WHERE variable = 'soil_temperature'"
    ).fetchone()[0]
    assert soil_t >= 1

    conn.close()
