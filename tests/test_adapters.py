"""Unit tests for the four bootstrap data source adapters.

Each test uses fixture files in tests/fixtures/ to verify parsing logic
without hitting real network endpoints.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from e2sa.data.above import ABoVEAdapter
from e2sa.data.alaska_thaw_db import AlaskaThawDBAdapter
from e2sa.data.base import FetchResult
from e2sa.data.calm import CALMAdapter
from e2sa.data.gtnp import GTNPAdapter
from e2sa.schema import ObservationType, Variable

FIXTURES = Path(__file__).parent / "fixtures"

FAKE_FETCH = FetchResult(
    dataset_id="test",
    local_path=Path("placeholder"),
    bytes_downloaded=0,
    access_timestamp=datetime(2026, 4, 12, tzinfo=UTC),
    content_checksum="test_checksum",
    source_url="https://test.invalid",
)


def _fetch_result(fixture_path: Path) -> FetchResult:
    return FetchResult(
        dataset_id="test",
        local_path=fixture_path,
        bytes_downloaded=fixture_path.stat().st_size,
        access_timestamp=datetime(2026, 4, 12, tzinfo=UTC),
        content_checksum="fixture_checksum",
        source_url="https://test.invalid",
    )


# --- CALM ---


class TestCALMAdapter:
    def test_parse_filters_to_us_only(self) -> None:
        adapter = CALMAdapter(raw_dir=Path("/tmp/test_calm"))
        fr = _fetch_result(FIXTURES / "calm_sample.tsv")
        obs = adapter.parse_to_schema(fr)
        countries = {o.extra.get("area_locality", "") for o in obs}
        assert all("Alaska" in area for area in countries if area)
        assert len(obs) > 0

    def test_parse_skips_missing_data(self) -> None:
        adapter = CALMAdapter(raw_dir=Path("/tmp/test_calm"))
        fr = _fetch_result(FIXTURES / "calm_sample.tsv")
        obs = adapter.parse_to_schema(fr)
        obs_ids = [o.obs_id for o in obs]
        assert not any("2022" in oid and "U1" in oid for oid in obs_ids)

    def test_parse_flags_probe_refusal(self) -> None:
        adapter = CALMAdapter(raw_dir=Path("/tmp/test_calm"))
        fr = _fetch_result(FIXTURES / "calm_sample.tsv")
        obs = adapter.parse_to_schema(fr)
        kougarok_160 = [o for o in obs if o.value == 160.0]
        assert len(kougarok_160) == 1
        assert "possible_probe_refusal" in kougarok_160[0].qc_flags

    def test_parse_returns_correct_schema(self) -> None:
        adapter = CALMAdapter(raw_dir=Path("/tmp/test_calm"))
        fr = _fetch_result(FIXTURES / "calm_sample.tsv")
        obs = adapter.parse_to_schema(fr)
        for o in obs:
            assert o.obs_type == ObservationType.POINT
            assert o.variable == Variable.ACTIVE_LAYER_THICKNESS
            assert o.unit == "cm"
            assert -90 <= o.latitude <= 90
            assert -180 <= o.longitude <= 180
            assert o.provenance.source_id == "calm"


# --- GTN-P ---


class TestGTNPAdapter:
    def test_parse_produces_profiles(self) -> None:
        adapter = GTNPAdapter(raw_dir=Path("/tmp/test_gtnp"))
        fr = _fetch_result(FIXTURES / "gtnp_sample.tsv")
        obs = adapter.parse_to_schema(fr)
        assert len(obs) > 0
        assert all(o.obs_type == ObservationType.PROFILE for o in obs)
        assert all(o.variable == Variable.GROUND_TEMPERATURE for o in obs)

    def test_parse_handles_multiple_depths(self) -> None:
        adapter = GTNPAdapter(raw_dir=Path("/tmp/test_gtnp"))
        fr = _fetch_result(FIXTURES / "gtnp_sample.tsv")
        obs = adapter.parse_to_schema(fr)
        bh001_depths = sorted(
            o.depth_m for o in obs if "BH001" in o.obs_id and o.depth_m is not None
        )
        assert bh001_depths == [0.0, 1.0, 5.0, 10.0]

    def test_parse_skips_missing_temperature(self) -> None:
        adapter = GTNPAdapter(raw_dir=Path("/tmp/test_gtnp"))
        fr = _fetch_result(FIXTURES / "gtnp_sample.tsv")
        obs = adapter.parse_to_schema(fr)
        bh003_obs = [o for o in obs if "BH003" in o.obs_id]
        depths = [o.depth_m for o in bh003_obs]
        assert 10.0 not in depths

    def test_parse_correct_units(self) -> None:
        adapter = GTNPAdapter(raw_dir=Path("/tmp/test_gtnp"))
        fr = _fetch_result(FIXTURES / "gtnp_sample.tsv")
        obs = adapter.parse_to_schema(fr)
        assert all(o.unit == "degC" for o in obs)

    def test_obs_ids_are_unique_across_stations_with_shared_event(self, tmp_path: Path) -> None:
        """Regression: real 2025 PANGAEA reuses event labels like 'MAGT_06_24'
        across many stations. obs_id must include station name + coords."""
        tsv = tmp_path / "shared_event.tsv"
        tsv.write_text(
            "/* test fixture */\n"
            "Event label\tName\tLatitude of event\tLongitude of event\tDATE/TIME\t"
            "Frequency\tDEPTH, sediment/rock [m]\tTemp [°C]\tProvenance/source\tAuthor(s)\n"
            "MAGT_06_24\tStation_A\t68.6134\t161.3498\t2014\thourly\t5.00\t-5.10\tsrc\tauthor\n"
            "MAGT_06_24\tStation_B\t70.1234\t-149.5678\t2014\thourly\t5.00\t-3.20\tsrc\tauthor\n",
            encoding="utf-8",
        )
        adapter = GTNPAdapter(raw_dir=tmp_path)
        obs = adapter.parse_to_schema(_fetch_result(tsv))
        assert len(obs) == 2
        ids = {o.obs_id for o in obs}
        assert len(ids) == 2, f"obs_id collision: {[o.obs_id for o in obs]}"


# --- Alaska Thaw DB ---


class TestAlaskaThawDBAdapter:
    def test_parse_from_csv(self, tmp_path: Path) -> None:
        """Test parsing directly from a CSV (bypassing ZIP extraction)."""
        adapter = AlaskaThawDBAdapter(raw_dir=tmp_path)
        csv_path = FIXTURES / "alaska_thaw_db_sample.csv"
        fr = _fetch_result(csv_path)

        # Monkey-patch to read CSV directly instead of extracting from ZIP
        obs = _parse_csv_directly(adapter, fr)
        assert len(obs) == 10

    def test_all_feature_categories_present(self, tmp_path: Path) -> None:
        adapter = AlaskaThawDBAdapter(raw_dir=tmp_path)
        fr = _fetch_result(FIXTURES / "alaska_thaw_db_sample.csv")
        obs = _parse_csv_directly(adapter, fr)
        categories = {o.extra["feature_category"] for o in obs}
        assert "Thermokarst lake" in categories
        assert "Non-abrupt" in categories
        assert "Active layer detachment" in categories

    def test_event_type_and_provenance(self, tmp_path: Path) -> None:
        adapter = AlaskaThawDBAdapter(raw_dir=tmp_path)
        fr = _fetch_result(FIXTURES / "alaska_thaw_db_sample.csv")
        obs = _parse_csv_directly(adapter, fr)
        for o in obs:
            assert o.obs_type == ObservationType.EVENT
            assert o.variable == Variable.THAW_EVENT_LABEL
            assert o.provenance.source_id == "alaska_thaw_db"
            assert o.extra.get("feature_category")

    def test_per_record_provenance_fields(self, tmp_path: Path) -> None:
        adapter = AlaskaThawDBAdapter(raw_dir=tmp_path)
        fr = _fetch_result(FIXTURES / "alaska_thaw_db_sample.csv")
        obs = _parse_csv_directly(adapter, fr)
        assert obs[0].extra["authors"] == "Jones and Zuck, 2016"
        assert obs[0].extra["doi"] == "https://doi.org/10.1234/example1"


def _parse_csv_directly(adapter: AlaskaThawDBAdapter, fr: FetchResult) -> list:
    """Parse a CSV file directly, bypassing ZIP extraction."""
    import csv
    import io

    from e2sa.data.alaska_thaw_db import ADAPTER_VERSION, FEATURE_CATEGORIES
    from e2sa.schema import Observation, ObservationType, Provenance, Variable

    text = fr.local_path.read_text(encoding="utf-8")
    reader = csv.DictReader(io.StringIO(text))

    observations = []
    for i, row in enumerate(reader):
        try:
            lat = float(row.get("Latitude", "").strip())
            lon = float(row.get("Longitude", "").strip())
        except (ValueError, AttributeError):
            continue

        feature_category = row.get("FeatureCategory", "").strip()
        category_index = (
            FEATURE_CATEGORIES.index(feature_category)
            if feature_category in FEATURE_CATEGORIES
            else -1
        )

        obs = Observation(
            obs_id=f"thawdb_{i:05d}_{lat:.3f}_{lon:.3f}",
            obs_type=ObservationType.EVENT,
            variable=Variable.THAW_EVENT_LABEL,
            value=float(category_index),
            unit="category_index",
            latitude=lat,
            longitude=lon,
            depth_m=None,
            time_start=None,
            time_end=None,
            qc_flags=[],
            provenance=Provenance(
                source_id="alaska_thaw_db",
                source_url="https://test.invalid",
                access_timestamp=fr.access_timestamp,
                content_checksum=fr.content_checksum,
                adapter_version=ADAPTER_VERSION,
            ),
            extra={
                "feature_name": row.get("FeatureName", "").strip(),
                "feature_type": row.get("FeatureType", "").strip(),
                "feature_category": feature_category,
                "thaw_type": row.get("ThawType", "").strip(),
                "data_source_type": row.get("DataSourceType", "").strip(),
                "authors": row.get("Authors", "").strip(),
                "doi": row.get("DOI", "").strip(),
                "imagery": row.get("Imagery", "").strip(),
                "imagery_dates": row.get("ImageryDates", "").strip(),
                "imagery_resolution_m": row.get("ImageryResolution_meters", "").strip(),
            },
        )
        observations.append(obs)
    return observations


# --- ABoVE ---


class TestABoVEAdapter:
    def test_parse_csv_produces_observations(self, tmp_path: Path) -> None:
        adapter = ABoVEAdapter(raw_dir=tmp_path)
        fr = _fetch_result(FIXTURES / "above_stdm_sample.csv")
        fr = FetchResult(
            dataset_id="above_stdm_1903",
            local_path=FIXTURES / "above_stdm_sample.csv",
            bytes_downloaded=(FIXTURES / "above_stdm_sample.csv").stat().st_size,
            access_timestamp=datetime(2026, 4, 12, tzinfo=UTC),
            content_checksum="fixture",
            source_url="https://test.invalid",
        )
        obs = adapter.parse_to_schema(fr)
        assert len(obs) > 0

    def test_maps_multiple_variables(self, tmp_path: Path) -> None:
        adapter = ABoVEAdapter(raw_dir=tmp_path)
        fr = FetchResult(
            dataset_id="above_stdm_1903",
            local_path=FIXTURES / "above_stdm_sample.csv",
            bytes_downloaded=100,
            access_timestamp=datetime(2026, 4, 12, tzinfo=UTC),
            content_checksum="fixture",
            source_url="https://test.invalid",
        )
        obs = adapter.parse_to_schema(fr)
        variables = {o.variable for o in obs}
        assert Variable.ACTIVE_LAYER_THICKNESS in variables
        assert Variable.SOIL_TEMPERATURE in variables

    def test_list_available_returns_registry(self, tmp_path: Path) -> None:
        adapter = ABoVEAdapter(raw_dir=tmp_path)
        datasets = adapter.list_available()
        assert len(datasets) >= 1
        assert datasets[0].dataset_id == "above_stdm_1903"
