"""`e2sa init <project> <run_id>` - scaffold a per-run subdirectory."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import click

from e2sa_cli.config import load_user

RUN_YAML_TEMPLATE = """\
# The single machine-read run artifact: manifest + intake (docs/design/19 §3.3).
# Read by the orchestrator (online) / interactive agent (offline) + `e2sa validate`.

# --- manifest (identity / status) ---
project: {project}
run_id: {run_id}
created: {created}
author:
  name: {author_name}
  email: {author_email}
status: scoped
e2sa_version: {e2sa_version}
schema_version: {schema_version}

# --- intake (the WHAT) ---
# `question` is required before this run executes. `sources` and `variables` are
# OPTIONAL: S0 intake derives variables from the question, S2 discover() derives
# sources, and both are written back here. An expert may pin them instead.
question: ""
sources: []
variables: []
# bbox: [west, south, east, north]        # optional
# time_range: ["YYYY-MM-DD", "YYYY-MM-DD"] # optional
"""

RESEARCH_PLAN_TEMPLATE = """\
# Research plan, {project} / {run_id}

**Status:** scoped, not yet executed.

## Question

<one or two sentences. Testable Earth system question this run answers.>

## Hypothesis

<the working hypothesis, with the expected sign and rough magnitude of the answer.>

## Data sources

| Source | Variables | Adapter | Notes |
|---|---|---|---|
| <e.g. CALM> | <ALT, soil T> | `e2sa/data/calm.py` | <coverage, time range> |

## Data preparation dependencies

Tasks under `projects/{project}/tasks/` that this run depends on. The agent files these via the `e2sa-file-task` skill when scaffolding a run that needs site data not already prepared. See `memory/knowledge/methods/20260521-when-to-file-a-data-prep-task.md` for the decision rule.

| Task | Work type | Status | MANIFEST |
|---|---|---|---|
| `<task_id>` | forcing / surface / observations / qc | requested / in_progress / done | `projects/{project}/tasks/<task_id>/MANIFEST.md` |

## Method

<short description of the analysis, modeling, evaluation choices.>

## Success criteria

<concrete, measurable. What the REPORT.md must contain for this run to count as answered.>

## Time and compute budget

<wall-clock and compute estimate. Helps the orchestrator pick fallbacks.>
"""

REPORT_TEMPLATE = """\
# Report, {project} / {run_id}

**Status:** empty, awaiting results. Populated by `e2sa-synthesize` or by hand after S9.

## Summary

<one paragraph.>

## Methods (executed)

<what was actually run, including deviations from RESEARCH_PLAN.md.>

## Results

<findings, with effect sizes and confidence intervals. Multiple-testing correction noted where relevant. Model predictions explicitly labeled as inference, not observation.>

## Limitations

<honest, scoped.>

## Reproduction

<command lines, environment notes.>
"""


@click.command()
@click.argument("project")
@click.argument("run_id")
@click.option(
    "--root",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path.cwd(),
    show_default=True,
    help="Repository root. Defaults to current working directory.",
)
@click.option(
    "--force",
    is_flag=True,
    help="Overwrite an existing run directory. Off by default to prevent accidents.",
)
def init(project: str, run_id: str, root: Path, force: bool) -> None:
    """Scaffold projects/<project>/runs/<run_id>/ with the canonical skeleton."""
    from e2sa_cli import __version__ as e2sa_version

    project_dir = root / "projects" / project
    if not project_dir.exists():
        click.echo(
            f"error: project directory does not exist: {project_dir}\n"
            f"       create it first (with its CLAUDE.md) before scaffolding a run.",
            err=True,
        )
        sys.exit(2)

    run_dir = project_dir / "runs" / run_id
    if run_dir.exists() and not force:
        click.echo(
            f"error: run directory already exists: {run_dir}\n"
            f"       pass --force to overwrite, or pick a different run_id.",
            err=True,
        )
        sys.exit(2)

    run_dir.mkdir(parents=True, exist_ok=True)
    for sub in ("notebooks", "data", "figures"):
        sub_path = run_dir / sub
        sub_path.mkdir(exist_ok=True)
        (sub_path / ".gitkeep").touch()

    user = load_user()
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    (run_dir / "run.yaml").write_text(
        RUN_YAML_TEMPLATE.format(
            project=project,
            run_id=run_id,
            created=created,
            author_name=user["name"],
            author_email=user["email"],
            e2sa_version=e2sa_version,
            schema_version="0.1.0",
        )
    )
    (run_dir / "RESEARCH_PLAN.md").write_text(
        RESEARCH_PLAN_TEMPLATE.format(project=project, run_id=run_id)
    )
    (run_dir / "REPORT.md").write_text(REPORT_TEMPLATE.format(project=project, run_id=run_id))

    click.echo(f"created: {run_dir}")
    click.echo("seeded:")
    for f in ("run.yaml", "RESEARCH_PLAN.md", "REPORT.md", "notebooks/", "data/", "figures/"):
        click.echo(f"  {f}")
