"""Workflow spec: the per-project pipeline template the orchestrator executes.

A project ships one `workflow.yaml` (e.g. `projects/spade/workflow.yaml`) declaring
which subagents run, in what order (a DAG via `depends_on`), with which human
`checkpoint` and machine `validators` per stage. The generic orchestrator reads this
template plus a run's intake (`run.yaml`) and executes the stages in dependency order.

This is the "different projects, different subagents" mechanism (docs/design/19,
RESOLVED 2026-06-28: the template is declarative YAML, not Python): a project differs
by which stages its workflow selects, not by forking orchestrator code. The agent
library is `e2sa/agents/<name>/`; per-agent contracts are in `docs/design/11`.
"""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, field_validator, model_validator

#: Agents a stage may bind to (the `e2sa/agents/` library; docs/design/11 §3.2).
KNOWN_AGENTS = frozenset(
    {
        "litreview",
        "data_assembly",
        "ml_modeldev",
        "calibration",
        "validation",
        "model_evolve",
        "report",
    }
)


class Stage(BaseModel):
    """One stage of a project workflow: an agent bound into the DAG.

    `checkpoint` is the human gate ("off" = none; any other string names a
    checkpoint, e.g. "source_selection", "final_report"). `validators` are the
    machine gates run on this stage's output before a dependent stage consumes it
    (the named-validator taxonomy in docs/design/19 §3.5).
    """

    id: str
    agent: str
    stage_code: str | None = None  # which S0-S10 menu slot (traceability only)
    depends_on: list[str] = []
    checkpoint: str = "off"
    validators: list[str] = []

    @field_validator("agent")
    @classmethod
    def _known_agent(cls, v: str) -> str:
        if v not in KNOWN_AGENTS:
            raise ValueError(f"unknown agent {v!r}; expected one of {sorted(KNOWN_AGENTS)}")
        return v


class WorkflowDefaults(BaseModel):
    """Run-wide defaults a project workflow declares.

    `autonomy` "gated" pauses at each checkpoint; "auto" runs through (the doc-07
    toggle). `review` "always" means the independent ReviewAgent runs regardless of
    the human review gate (docs/design/07 §3.5).
    """

    autonomy: str = "gated"  # gated | auto
    review: str = "always"


class WorkflowSpec(BaseModel):
    """A project's pipeline template: the stages DAG plus defaults.

    Input contract: parsed from a project `workflow.yaml`. Validated on construction
    (unique stage ids, every `depends_on` resolves, no cycles). Side effects: none.
    """

    project: str
    description: str = ""
    stages: list[Stage]
    defaults: WorkflowDefaults = WorkflowDefaults()

    @model_validator(mode="after")
    def _validate_dag(self) -> "WorkflowSpec":
        ids = [s.id for s in self.stages]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate stage ids: {dupes}")
        idset = set(ids)
        for s in self.stages:
            for dep in s.depends_on:
                if dep not in idset:
                    raise ValueError(f"stage {s.id!r} depends_on unknown stage {dep!r}")
        self.topological_order()  # raises ValueError on a cycle
        return self

    def topological_order(self) -> list[str]:
        """Stage ids in a dependency-respecting order (deterministic).

        Raises ValueError if the graph has a cycle. Ready stages at each step are
        emitted in sorted order so the result is stable across runs.
        """
        remaining = {s.id: set(s.depends_on) for s in self.stages}
        resolved: set[str] = set()
        order: list[str] = []
        while remaining:
            ready = sorted(sid for sid, deps in remaining.items() if deps <= resolved)
            if not ready:
                raise ValueError(f"cycle or unresolved deps among stages: {sorted(remaining)}")
            for sid in ready:
                order.append(sid)
                resolved.add(sid)
                del remaining[sid]
        return order

    def stage(self, stage_id: str) -> Stage:
        """Return the Stage with this id, or raise KeyError."""
        for s in self.stages:
            if s.id == stage_id:
                return s
        raise KeyError(stage_id)


def load_workflow(path: Path | str) -> WorkflowSpec:
    """Load and validate a project workflow template from YAML.

    Input contract: a readable YAML file with `project` and `stages`. Output: a
    validated `WorkflowSpec`. Raises on malformed YAML or a failed validation.
    """
    with open(path) as f:
        data = yaml.safe_load(f)
    return WorkflowSpec(**data)
