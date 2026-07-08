"""Tests for project-aware data placement (docs/design/17).

Covers the ProjectPaths resolver, RunConfig.project resolution, and the
DataAssemblyAgent deriving its raw_dir + catalog from config.project. The
acquire()/CLI threading is covered in test_minimal_driver.py.
"""
from __future__ import annotations

from pathlib import Path

from e2sa.agents.data_assembly.agent import DataAssemblyAgent
from e2sa.config import RunConfig, load_run_config, project_paths


class TestProjectPaths:
    def test_resolves_canonical_tree(self) -> None:
        pp = project_paths("spade")
        assert pp.root == Path("projects/spade")
        assert pp.raw_dir == Path("projects/spade/data/raw")
        assert pp.interim_dir == Path("projects/spade/data/interim")
        assert pp.processed_dir == Path("projects/spade/data/processed")
        assert pp.catalog_path == Path("projects/spade/data/catalog.duckdb")

    def test_projects_root_override(self, tmp_path: Path) -> None:
        pp = project_paths("spade", projects_root=tmp_path)
        assert pp.raw_dir == tmp_path / "spade" / "data" / "raw"

    def test_no_io_performed(self, tmp_path: Path) -> None:
        # Pure resolution: must not create anything on disk.
        project_paths("ghost", projects_root=tmp_path)
        assert not (tmp_path / "ghost").exists()


class TestRunConfigProject:
    def test_paths_from_project(self) -> None:
        cfg = RunConfig(name="r", question="q", sources=[], variables=[], project="spade")
        pp = cfg.paths()
        assert pp is not None
        assert pp.raw_dir == Path("projects/spade/data/raw")

    def test_paths_none_without_project(self) -> None:
        cfg = RunConfig(name="r", question="q", sources=[], variables=[])
        assert cfg.paths() is None

    def test_loads_the_spade_template(self) -> None:
        cfg = load_run_config("configs/spade_alaska_ice_content.yaml")
        assert cfg.project == "spade"
        assert cfg.paths().catalog_path == Path("projects/spade/data/catalog.duckdb")
        # Template uses current registered slugs + served variables.
        assert "kanevskiy_2024_cryostratigraphy" in cfg.sources
        assert "alaska_thaw_db_2025" not in cfg.sources
        assert "excess_ice_content" in cfg.variables


class TestAgentResolvesProject:
    def test_agent_derives_raw_and_catalog_from_project(self) -> None:
        cfg = RunConfig(name="r", question="q", sources=[], variables=[], project="spade")
        agent = DataAssemblyAgent(cfg)
        assert agent.raw_dir == Path("projects/spade/data/raw")
        assert agent.catalog_path == Path("projects/spade/data/catalog.duckdb")

    def test_explicit_catalog_overrides_project(self, tmp_path: Path) -> None:
        cfg = RunConfig(name="r", question="q", sources=[], variables=[], project="spade")
        agent = DataAssemblyAgent(cfg, catalog_path=tmp_path / "c.duckdb")
        assert agent.catalog_path == tmp_path / "c.duckdb"
        assert agent.raw_dir == Path("projects/spade/data/raw")  # still from project

    def test_projectless_config_uses_framework_default(self) -> None:
        cfg = RunConfig(name="r", question="q", sources=[], variables=[])
        agent = DataAssemblyAgent(cfg)
        assert agent.raw_dir == Path("data/raw")
