"""DataAssemblyAgent: assemble analysis-ready data for a research question.

E2SA pipeline stage S2-S6 (discover -> retrieve -> organize -> harmonize -> QC
-> post-process -> write). Orchestrates the existing data modules (`e2sa.data`,
`e2sa.orchestrator.acquire`, `e2sa.harmonize`, `e2sa.qc`); SPADE supplies the
domain source cards + adapters. Design: `docs/design/11_agent_pipeline.md`.

STUB: interface defined; methods not yet implemented.
"""
from __future__ import annotations

from .agent import DataAssemblyAgent
from .models import (
    AssemblyRequest,
    AssemblyResult,
    DatasetCandidate,
    ScreeningDecision,
    TargetFormat,
)

__all__ = [
    "DataAssemblyAgent",
    "AssemblyRequest",
    "AssemblyResult",
    "DatasetCandidate",
    "ScreeningDecision",
    "TargetFormat",
]
