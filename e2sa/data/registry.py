"""Central registry of source_id -> adapter class.

The orchestrator and CLI both use `get_adapter(source_id)` to look up the
right adapter without importing each one directly. Adding a new adapter
means: (1) implement it under `e2sa/data/<source>.py`, (2) add one line
to ADAPTER_REGISTRY below.
"""
from __future__ import annotations

from pathlib import Path

from e2sa.data.above import ABoVEAdapter
from e2sa.data.alaska_thaw_db import AlaskaThawDBAdapter
from e2sa.data.base import BaseAdapter
from e2sa.data.calm import CALMAdapter
from e2sa.data.ess_dive import ESSDIVEAdapter
from e2sa.data.gtnp import GTNPAdapter

ADAPTER_REGISTRY: dict[str, type[BaseAdapter]] = {
    "calm": CALMAdapter,
    "gtnp": GTNPAdapter,
    "alaska_thaw_db": AlaskaThawDBAdapter,
    "above": ABoVEAdapter,
    "ess_dive": ESSDIVEAdapter,
}


def get_adapter(source_id: str, raw_dir: Path = Path("data/raw")) -> BaseAdapter:
    """Instantiate the adapter registered for source_id under raw_dir."""
    cls = ADAPTER_REGISTRY.get(source_id)
    if cls is None:
        raise KeyError(
            f"Unknown source_id: {source_id!r}. "
            f"Registered sources: {sorted(ADAPTER_REGISTRY)}"
        )
    return cls(raw_dir=raw_dir)
