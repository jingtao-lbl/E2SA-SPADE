"""Tests for the project workflow template (e2sa/workflow.py, docs/design/19).

Offline and deterministic. Exercises the SPADE workflow.yaml plus the DAG
validation rules (unknown agent, duplicate id, missing dep, cycle) and the
YAML-boolean `off` gotcha for `checkpoint`.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from e2sa.workflow import Stage, WorkflowSpec, load_workflow

SPADE_WORKFLOW = Path("projects/spade/workflow.yaml")


def _spec(stages, **kw):
    return WorkflowSpec(project="t", stages=[Stage(**s) for s in stages], **kw)


class TestSpadeWorkflow:
    def test_loads(self):
        wf = load_workflow(SPADE_WORKFLOW)
        assert wf.project == "spade"
        ids = [s.id for s in wf.stages]
        assert ids == ["litreview", "data_assembly", "ml_modeldev", "validation", "report"]

    def test_calibration_omitted(self):
        # The "different projects, different subagents" point: SPADE skips calibration.
        wf = load_workflow(SPADE_WORKFLOW)
        assert "calibration" not in {s.agent for s in wf.stages}

    def test_topological_order_respects_deps(self):
        wf = load_workflow(SPADE_WORKFLOW)
        order = wf.topological_order()
        # every dependency precedes the stage that needs it
        for s in wf.stages:
            for dep in s.depends_on:
                assert order.index(dep) < order.index(s.id)

    def test_checkpoint_off_is_a_string_not_bool(self):
        # YAML 1.1 parses bare `off` as boolean False; the template quotes it.
        wf = load_workflow(SPADE_WORKFLOW)
        litreview = wf.stage("litreview")
        assert litreview.checkpoint == "off"
        assert isinstance(litreview.checkpoint, str)

    def test_data_assembly_declares_data_validators(self):
        wf = load_workflow(SPADE_WORKFLOW)
        da = wf.stage("data_assembly")
        assert {"data_quality", "provenance_complete"} <= set(da.validators)


class TestDagValidation:
    def test_unknown_agent_rejected(self):
        with pytest.raises(ValueError, match="unknown agent"):
            _spec([{"id": "a", "agent": "not_an_agent"}])

    def test_duplicate_stage_ids_rejected(self):
        with pytest.raises(ValueError, match="duplicate stage ids"):
            _spec([{"id": "a", "agent": "litreview"}, {"id": "a", "agent": "report"}])

    def test_missing_dependency_rejected(self):
        with pytest.raises(ValueError, match="depends_on unknown stage"):
            _spec([{"id": "a", "agent": "litreview", "depends_on": ["ghost"]}])

    def test_cycle_rejected(self):
        with pytest.raises(ValueError, match="cycle"):
            _spec(
                [
                    {"id": "a", "agent": "litreview", "depends_on": ["b"]},
                    {"id": "b", "agent": "report", "depends_on": ["a"]},
                ]
            )

    def test_valid_linear_chain_orders(self):
        wf = _spec(
            [
                {"id": "a", "agent": "litreview"},
                {"id": "b", "agent": "data_assembly", "depends_on": ["a"]},
                {"id": "c", "agent": "report", "depends_on": ["b"]},
            ]
        )
        assert wf.topological_order() == ["a", "b", "c"]
