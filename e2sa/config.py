"""Run configuration for an E2SA pipeline invocation, plus project-path resolution.

A `RunConfig` is the single machine-read run artifact, loaded from a run's `run.yaml`:
intake (the WHAT: question, sources, variables, bbox, time, model) plus the manifest
(identity + status + versions). These were two files (`configs/<run>.yaml` intake and
`runs/<run_id>/run.yaml` manifest); the config-trinity merge (docs/design/19 §3.3)
folds them into one `run.yaml`, so the top-level `configs/*.yaml` are now starter
templates a user copies. `sources` and `variables` are OPTIONAL: S0 intake derives
variables from the question and S2 `discover()` derives sources, writing them back.
`project` resolves the canonical on-disk layout via `project_paths`, so the data-assembly
agent and `acquire()` know where to place data without a hand-passed path. See
`docs/design/17`, `docs/design/19` §3.3/§3.6, and `projects/<project>/CLAUDE.md` §9-§10.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, field_validator

#: Root holding all projects (relative to the repo / cwd).
PROJECTS_ROOT = Path("projects")


@dataclass(frozen=True)
class ProjectPaths:
    """Canonical on-disk locations for one project (CLAUDE.md §9-§10)."""

    project: str
    root: Path  # projects/<project>
    data_dir: Path  # projects/<project>/data
    raw_dir: Path  # .../data/raw  (connector appends <data_center>/<dataset_id>/)
    interim_dir: Path  # .../data/interim
    processed_dir: Path  # .../data/processed
    catalog_path: Path  # .../data/catalog.duckdb


def project_paths(project: str, projects_root: Path | str = PROJECTS_ROOT) -> ProjectPaths:
    """Resolve a project name to its canonical data tree (no I/O, no mkdir)."""
    root = Path(projects_root) / project
    data = root / "data"
    return ProjectPaths(
        project=project,
        root=root,
        data_dir=data,
        raw_dir=data / "raw",
        interim_dir=data / "interim",
        processed_dir=data / "processed",
        catalog_path=data / "catalog.duckdb",
    )


class Author(BaseModel):
    """Run author, captured in run.yaml (seeded by `e2sa init`)."""

    name: str | None = None
    email: str | None = None


class RunConfig(BaseModel):
    """The single machine-read run artifact: intake + manifest (one `run.yaml`).

    Merged per docs/design/19 §3.3. `sources` and `variables` are OPTIONAL (derived
    by S0 intake / S2 discover() and written back). The manifest fields (run_id,
    created, author, status, versions) are seeded by `e2sa init`.
    """

    # --- manifest (identity / status; seeded by `e2sa init`) ---
    #: The project this run belongs to; resolves the on-disk data tree (doc 17).
    project: str | None = None
    run_id: str | None = None
    created: str | None = None
    author: Author | None = None
    status: str | None = None
    e2sa_version: str | None = None
    schema_version: str | None = None

    # --- intake (the WHAT) ---
    question: str | None = None
    #: Dataset slugs. Optional: S2 discover() derives them from `variables` if unset.
    sources: list[str] | None = None
    #: Variable enum members. Optional: S0 intake derives them from `question` if unset.
    variables: list[str] | None = None
    bbox: tuple[float, float, float, float] | None = None
    time_range: tuple[str, str] | None = None
    #: Optional explicit model override. Normally left unset: the modeling stage
    #: (S7 / ml_modeldev) chooses it, following the P3 baseline -> P4 generative
    #: roadmap. Not an intake decision; not a slug the user should need to know.
    model: str | None = None

    # --- legacy / overrides ---
    #: Superseded by `run_id`; kept so older configs still parse.
    name: str | None = None
    #: Optional explicit override; normally derived from `project` (see `paths`).
    output_dir: Path | None = None

    @field_validator("created", mode="before")
    @classmethod
    def _created_to_str(cls, v: object) -> object:
        # YAML auto-parses an ISO timestamp (e.g. 2026-06-23T20:16:59Z) into a
        # datetime; keep `created` a string so run.yaml round-trips cleanly.
        if isinstance(v, (datetime, date)):
            return v.isoformat()
        return v

    def paths(self) -> ProjectPaths | None:
        """The project's canonical paths, or None if this run names no project."""
        return project_paths(self.project) if self.project else None


def load_run_config(path: Path | str) -> RunConfig:
    """Load a RunConfig from a YAML file (a run's `run.yaml`, or a starter template)."""
    with open(path) as f:
        data = yaml.safe_load(f)
    return RunConfig(**data)


def load_run(run_dir: Path | str) -> RunConfig:
    """Load the merged `run.yaml` from a run directory (docs/design/19 §3.3)."""
    return load_run_config(Path(run_dir) / "run.yaml")
