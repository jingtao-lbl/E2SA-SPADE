"""QC layer: data-quality + adapter-contract checks."""
from e2sa.qc.checks import (
    DEFAULT_RANGES,
    SUBSURFACE_VARIABLES,
    Finding,
    check_citation_not_synthesized,
    check_depth_for_subsurface,
    check_self_describing,
    check_serves_subset_emitted,
    check_value_ranges,
    summarize_distributions,
    validate_observations,
    validate_staged_folder,
)
from e2sa.qc.cross_source import check_cross_source_consistency

__all__ = [
    "DEFAULT_RANGES",
    "SUBSURFACE_VARIABLES",
    "Finding",
    "check_citation_not_synthesized",
    "check_cross_source_consistency",
    "check_depth_for_subsurface",
    "check_self_describing",
    "check_serves_subset_emitted",
    "check_value_ranges",
    "summarize_distributions",
    "validate_observations",
    "validate_staged_folder",
]
