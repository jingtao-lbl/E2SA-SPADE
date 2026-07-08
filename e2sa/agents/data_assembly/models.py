"""Pydantic domain models for the data-assembly agent.

Configuration and result records. The heavy lifting (fetch, index, harmonize,
QC) is done by existing modules the agent calls; these records describe the
request and report what was assembled.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from e2sa.schema import Variable


class TargetFormat(str, Enum):
    """Analysis-ready output format the assembled data is written to."""

    CSV = "csv"
    PARQUET = "parquet"
    NETCDF = "netcdf"
    GEOTIFF = "geotiff"
    NONE = "none"  # leave it in the catalog only


class AssemblyRequest(BaseModel):
    """What to assemble, derived from a research question."""

    question: str
    variables: list[Variable] = Field(default_factory=list)
    bbox: tuple[float, float, float, float] | None = None
    time_range: tuple[str, str] | None = None
    target_format: TargetFormat = TargetFormat.NONE
    notes: str = ""


class DatasetCandidate(BaseModel):
    """A dataset that might satisfy (part of) the request, surfaced by discovery."""

    source_id: str
    """Adapter / source-card id (e.g. 'ngee_arctic', 'kanevskiy_2024_cryostratigraphy')."""
    dataset_id: str | None = None
    doi: str | None = None
    variables: list[Variable] = Field(default_factory=list)
    coverage: str = ""
    license: str | None = None
    landing_page: str | None = None
    relevance: float | None = None
    """Optional relevance score (e.g. from the litreview/RAG layer)."""
    already_on_disk: bool = False


class ScreeningDecision(BaseModel):
    """Accept/reject decision for one candidate (human checkpoint (a) in CLAUDE.md Section 5)."""

    candidate: DatasetCandidate
    accepted: bool
    reason: str = ""


class AssemblyResult(BaseModel):
    """Summary of one assembly run."""

    request: AssemblyRequest
    datasets_assembled: list[str] = Field(default_factory=list)
    catalog_path: str | None = None
    n_observations: int = 0
    output_paths: list[str] = Field(default_factory=list)
    qc_flags: dict[str, int] = Field(default_factory=dict)
    notes: str = ""
