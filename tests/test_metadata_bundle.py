"""Tests for the self-describing metadata bundle (docs/design/18).

write_metadata_bundle writes PROVENANCE.json + CITATION.cff + README.md into a
staged dataset folder, so it is never just a bare data file. Covers both the
single-file (local_path = the data file) and package (local_path = dir) shapes.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from e2sa.data.base import DatasetInfo, FetchResult
from e2sa.data.metadata_bundle import write_metadata_bundle


def _info() -> DatasetInfo:
    return DatasetInfo(
        dataset_id="calm_alt",
        name="CALM ALT (PANGAEA)",
        description="Active layer thickness, 263 time series.",
        variables=["active_layer_thickness"],
        spatial_coverage="Northern Hemisphere",
        temporal_coverage="1990-2024",
        format="TSV",
        url="https://doi.org/10.1594/PANGAEA.972777",
        license="CC-BY-4.0",
        citation="Streletskiy et al. (2025): GTN-P CALM ALT. PANGAEA, https://doi.org/10.1594/PANGAEA.972777",
        references=["Nelson et al. (2021), https://doi.org/10.1080/1088937X.2021.1988001"],
        keywords=["Active Layer Thickness", "CALM"],
    )


def _fr_single(folder: Path) -> FetchResult:
    folder.mkdir(parents=True, exist_ok=True)
    tsv = folder / "calm_alt.tsv"
    tsv.write_text("/* header */\ncol\n1\n")
    return FetchResult(
        dataset_id="calm_alt",
        local_path=tsv,  # single-file shape: the data file itself
        bytes_downloaded=tsv.stat().st_size,
        access_timestamp=datetime(2026, 6, 23, tzinfo=UTC),
        content_checksum="abc123def456",
        source_url="https://doi.org/10.1594/PANGAEA.972777",
    )


class TestWriteBundle:
    def test_writes_three_sidecars_into_the_folder(self, tmp_path: Path) -> None:
        folder = tmp_path / "pangaea" / "calm_alt"
        fr = _fr_single(folder)
        written = write_metadata_bundle(fr, "calm_alt", _info())
        names = {p.name for p in written}
        assert names == {"PROVENANCE.json", "CITATION.cff", "README.md"}
        for p in written:
            assert p.parent == folder and p.exists()

    def test_provenance_json_is_complete(self, tmp_path: Path) -> None:
        folder = tmp_path / "pangaea" / "calm_alt"
        fr = _fr_single(folder)
        write_metadata_bundle(fr, "calm_alt", _info())
        prov = json.loads((folder / "PROVENANCE.json").read_text())
        assert prov["data_center"] == "pangaea"
        assert prov["dataset_id"] == "calm_alt"
        assert prov["doi"] == "10.1594/PANGAEA.972777"
        assert "Streletskiy" in prov["citation"]
        assert prov["license"] == "CC-BY-4.0"
        assert prov["content_checksum_sha256"] == "abc123def456"
        assert prov["references"] and prov["variables"] == ["active_layer_thickness"]

    def test_citation_and_readme_carry_the_citation(self, tmp_path: Path) -> None:
        folder = tmp_path / "pangaea" / "calm_alt"
        fr = _fr_single(folder)
        write_metadata_bundle(fr, "calm_alt", _info())
        cff = (folder / "CITATION.cff").read_text()
        assert cff.startswith("cff-version: 1.2.0")
        assert "10.1594/PANGAEA.972777" in cff
        readme = (folder / "README.md").read_text()
        assert "## Citation" in readme and "Streletskiy" in readme
        assert "## References" in readme and "## Files" in readme

    def test_package_shape_writes_into_the_dir(self, tmp_path: Path) -> None:
        # local_path is a directory (BagIt/package); sidecars land in that dir.
        folder = tmp_path / "arctic_data_center" / "kanevskiy_2024_cryostratigraphy"
        (folder / "data").mkdir(parents=True)
        (folder / "bagit.txt").write_text("BagIt-Version: 0.97\n")
        fr = FetchResult(
            dataset_id="kanevskiy_2024_cryostratigraphy",
            local_path=folder,
            bytes_downloaded=10,
            access_timestamp=datetime(2026, 6, 23, tzinfo=UTC),
            content_checksum="deadbeef",
            source_url="https://doi.org/10.18739/A2H12V928",
            files=[folder / "bagit.txt"],
        )
        write_metadata_bundle(fr, "kanevskiy_2024_cryostratigraphy", None)
        assert (folder / "PROVENANCE.json").exists()
        prov = json.loads((folder / "PROVENANCE.json").read_text())
        assert prov["data_center"] == "arctic_data_center"
        assert prov["doi"] == "10.18739/A2H12V928"  # from source_url when no info


class TestNeverFabricatesCitation:
    """No-made-up-references rule: a missing citation must never be synthesized."""

    def _info_no_citation(self) -> DatasetInfo:
        return DatasetInfo(
            dataset_id="calm_alt",
            name="CALM ALT (PANGAEA)",
            description="Active layer thickness.",
            variables=["active_layer_thickness"],
            spatial_coverage="Northern Hemisphere",
            temporal_coverage="1990-2024",
            format="TSV",
            url="https://doi.org/10.1594/PANGAEA.972777",
            license="CC-BY-4.0",
            citation=None,  # adapter did not supply the real citation
        )

    def test_missing_citation_points_to_source_not_invented(self, tmp_path: Path) -> None:
        """When no citation is given, the CFF points to the source's official
        citation rather than fabricating "Title. URL"; README omits Citation."""
        folder = tmp_path / "pangaea" / "calm_alt"
        fr = _fr_single(folder)
        write_metadata_bundle(fr, "calm_alt", self._info_no_citation())

        cff = (folder / "CITATION.cff").read_text()
        assert "please cite:" not in cff  # nothing fabricated
        assert "official citation" in cff  # points to the authoritative source
        assert "CALM ALT (PANGAEA)." not in cff  # not the old "Title. URL" synthesis

        prov = json.loads((folder / "PROVENANCE.json").read_text())
        assert prov["citation"] is None  # stays null, not invented

        readme = (folder / "README.md").read_text()
        assert "## Citation" not in readme  # no Citation section without a real one
