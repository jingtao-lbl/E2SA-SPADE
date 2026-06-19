"""`e2sa validate <run_id>` - deterministic structural checks on a run.

No LLM call. Rule-based. Fast (seconds). Backs the `e2sa-validate` skill and
the `e2sa-workflow-guard` pre-commit / pre-push hook.

P0 check set (will expand at P2+ when adapters and schemas land):

1. Skeleton complete (run.yaml, RESEARCH_PLAN.md, REPORT.md, notebooks/, data/, figures/)
2. run.yaml parseable, has required fields (project, run_id, created, status)
3. Notebooks have saved outputs (no empty `outputs` arrays)
4. No hardcoded secrets in any file under the run dir
5. No derived-notebook helpers (warn if create_notebooks.py / *_to_notebook.py / nbgen*.py exist)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import click
import yaml

REQUIRED_TOPLEVEL = ("run.yaml", "RESEARCH_PLAN.md", "REPORT.md")
REQUIRED_DIRS = ("notebooks", "data", "figures")
REQUIRED_YAML_FIELDS = ("project", "run_id", "created", "status")

SECRET_PATTERNS = [
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"), "Anthropic API key"),
    (re.compile(r"sk-proj-[A-Za-z0-9_\-]{20,}"), "OpenAI project API key"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key id"),
    (re.compile(r"AWS_SECRET_ACCESS_KEY\s*=\s*['\"][A-Za-z0-9/+=]{40}['\"]"), "AWS secret access key"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"), "JWT"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), "GitHub fine-grained PAT"),
    (re.compile(r"\bghp_[A-Za-z0-9]{36}\b"), "GitHub classic PAT"),
]

DERIVED_NOTEBOOK_HELPER_PATTERNS = [
    re.compile(r"create_notebooks?\.py$"),
    re.compile(r".*_to_notebook\.py$"),
    re.compile(r"nbgen.*\.py$"),
]


def _find_run_dir(run_id: str, root: Path) -> Path | None:
    matches = list(root.glob(f"projects/*/runs/{run_id}"))
    if len(matches) == 0:
        return None
    if len(matches) > 1:
        click.echo(
            f"error: run_id '{run_id}' is ambiguous, matches {len(matches)} paths:",
            err=True,
        )
        for m in matches:
            click.echo(f"  {m}", err=True)
        click.echo("       pass --path to disambiguate.", err=True)
        sys.exit(2)
    return matches[0]


def _check_skeleton(run_dir: Path) -> list[str]:
    issues: list[str] = []
    for f in REQUIRED_TOPLEVEL:
        if not (run_dir / f).exists():
            issues.append(f"S1: missing required file: {f}")
    for d in REQUIRED_DIRS:
        if not (run_dir / d).is_dir():
            issues.append(f"S1: missing required dir: {d}/")
    return issues


def _check_run_yaml(run_dir: Path) -> list[str]:
    yaml_path = run_dir / "run.yaml"
    if not yaml_path.exists():
        return []
    try:
        data = yaml.safe_load(yaml_path.read_text())
    except yaml.YAMLError as e:
        return [f"S2: run.yaml is not parseable: {e}"]
    if not isinstance(data, dict):
        return ["S2: run.yaml root is not a mapping"]
    issues = []
    for field in REQUIRED_YAML_FIELDS:
        if field not in data or data[field] in ("", None):
            issues.append(f"S2: run.yaml missing required field: {field}")
    return issues


def _check_notebook_outputs(run_dir: Path) -> list[str]:
    issues: list[str] = []
    nb_dir = run_dir / "notebooks"
    if not nb_dir.is_dir():
        return []
    for nb_path in sorted(nb_dir.rglob("*.ipynb")):
        if ".ipynb_checkpoints" in nb_path.parts:
            continue
        try:
            nb = json.loads(nb_path.read_text())
        except json.JSONDecodeError as e:
            issues.append(f"S3: notebook not parseable: {nb_path.relative_to(run_dir)}: {e}")
            continue
        cells = nb.get("cells", [])
        code_cells = [c for c in cells if c.get("cell_type") == "code"]
        if not code_cells:
            continue
        if not any(c.get("outputs") for c in code_cells):
            issues.append(
                f"S3: notebook has no saved outputs: {nb_path.relative_to(run_dir)}"
            )
    return issues


def _check_secrets(run_dir: Path) -> list[str]:
    issues: list[str] = []
    for path in sorted(run_dir.rglob("*")):
        if not path.is_file():
            continue
        if any(p == ".ipynb_checkpoints" for p in path.parts):
            continue
        if path.suffix in (".png", ".jpg", ".jpeg", ".pdf", ".nc", ".tif", ".tiff", ".parquet", ".h5", ".hdf5", ".gz", ".zip"):
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        for pat, name in SECRET_PATTERNS:
            if pat.search(text):
                issues.append(
                    f"S4: possible {name} in {path.relative_to(run_dir)}"
                )
    return issues


def _check_no_derived_helpers(run_dir: Path) -> list[str]:
    issues: list[str] = []
    for path in sorted(run_dir.rglob("*.py")):
        name = path.name
        if any(pat.match(name) for pat in DERIVED_NOTEBOOK_HELPER_PATTERNS):
            issues.append(
                f"S5: derived-notebook helper present: {path.relative_to(run_dir)}; "
                f"notebook-first execution is the policy"
            )
    return issues


@click.command()
@click.argument("run_id", required=False)
@click.option(
    "--path",
    "explicit_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Explicit path to the run directory, bypasses search by run_id.",
)
@click.option(
    "--root",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path.cwd(),
    show_default=True,
    help="Repository root for search.",
)
def validate(run_id: str | None, explicit_path: Path | None, root: Path) -> None:
    """Run deterministic structural checks against a run. Exit 0 on pass."""
    if explicit_path is not None:
        run_dir = explicit_path
    elif run_id is not None:
        found = _find_run_dir(run_id, root)
        if found is None:
            click.echo(
                f"error: no run found with id '{run_id}' under {root}/projects/*/runs/",
                err=True,
            )
            sys.exit(2)
        run_dir = found
    else:
        click.echo("error: either RUN_ID or --path is required.", err=True)
        sys.exit(2)

    issues: list[str] = []
    issues.extend(_check_skeleton(run_dir))
    issues.extend(_check_run_yaml(run_dir))
    issues.extend(_check_notebook_outputs(run_dir))
    issues.extend(_check_secrets(run_dir))
    issues.extend(_check_no_derived_helpers(run_dir))

    checks_run = 5
    if issues:
        click.echo(f"FAIL ({len(issues)} issues, {checks_run} checks): {run_dir}")
        for issue in issues:
            click.echo(f"  {issue}")
        sys.exit(1)
    click.echo(f"PASS ({checks_run} checks): {run_dir}")
