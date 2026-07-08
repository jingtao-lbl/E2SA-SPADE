"""Central registry of source_id -> adapter class, plus the capability index.

The orchestrator and CLI both use `get_adapter(source_id)` to look up the
right adapter without importing each one directly. Adding a new adapter
means: (1) implement it under `e2sa/data/adapters/<dataset_id>.py` (the file
name matches the §9 slug = source_id = dataset_id = the registry key below),
(2) add one line to ADAPTER_REGISTRY below, (3) declare its `serves` (Variables
it emits). A connector-backed adapter sets `data_center` and inherits the
default `fetch` (delegates to the connector); it implements only
`list_available` + `parse_to_schema`.

The capability index (`CAPABILITY_INDEX` + `sources_for_variables`) lets the
data-assembly agent route a research question to the sources that can serve its
variables, without instantiating adapters or hitting any API. It reads each
adapter's class-level `serves`. See docs/design/14.
"""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from e2sa.data.adapters.above_stdm import ABoVEAdapter
from e2sa.data.adapters.calm_alt import CALMAdapter
from e2sa.data.adapters.gtnp_magt import GTNPAdapter
from e2sa.data.adapters.kanevskiy_2024_cryostratigraphy import KanevskiyCryostratigraphyAdapter
from e2sa.data.adapters.sloan_2014_barrow_soil import Sloan2014BarrowSoilAdapter
from e2sa.data.adapters.tsp_north_america_ground_temperature import (
    TSPNorthAmericaGroundTemperatureAdapter,
)
from e2sa.data.adapters.webb_2026_alaska_thaw_db import AlaskaThawDBAdapter
from e2sa.data.base import BaseAdapter
from e2sa.schema import Variable

ADAPTER_REGISTRY: dict[str, type[BaseAdapter]] = {
    "calm_alt": CALMAdapter,
    "gtnp_magt": GTNPAdapter,
    "webb_2026_alaska_thaw_db": AlaskaThawDBAdapter,
    "above_stdm": ABoVEAdapter,
    "sloan_2014_barrow_soil": Sloan2014BarrowSoilAdapter,
    "kanevskiy_2024_cryostratigraphy": KanevskiyCryostratigraphyAdapter,
    "tsp_north_america_ground_temperature": TSPNorthAmericaGroundTemperatureAdapter,
}

# Variables that are the same physical quantity and should route together.
# GROUND_TEMPERATURE == SOIL_TEMPERATURE (PI ruling 2026-06-22): a query for
# either must find adapters serving the other. Adapters still declare in `serves`
# the exact member they emit (so the serves-subset-of-emitted guard holds); the
# equivalence lives here, in routing only.
VARIABLE_EQUIVALENCE: tuple[frozenset[Variable], ...] = (
    frozenset({Variable.SOIL_TEMPERATURE, Variable.GROUND_TEMPERATURE}),
)


def adapter_capabilities() -> dict[str, frozenset[Variable]]:
    """source_id -> the Variables its adapter declares it serves (`serves`)."""
    return {sid: cls.serves for sid, cls in ADAPTER_REGISTRY.items()}


def _build_capability_index() -> dict[Variable, list[str]]:
    """Variable -> sorted source_ids whose adapter declares it. Import-time, no I/O."""
    index: dict[Variable, set[str]] = {}
    for sid, cls in ADAPTER_REGISTRY.items():
        for var in cls.serves:
            index.setdefault(var, set()).add(sid)
    return {var: sorted(sids) for var, sids in index.items()}


#: Variable -> [source_id], built once at import from each adapter's `serves`.
CAPABILITY_INDEX: dict[Variable, list[str]] = _build_capability_index()


def _equivalence_class(var: Variable) -> frozenset[Variable]:
    """The set of Variables that route together with `var` (itself if no group)."""
    for group in VARIABLE_EQUIVALENCE:
        if var in group:
            return group
    return frozenset({var})


def sources_for_variables(
    variables: Iterable[Variable],
) -> dict[Variable, list[str]]:
    """For each requested Variable, the source_ids that can serve it.

    Expands each variable to its equivalence class (so SOIL_TEMPERATURE also
    matches GROUND_TEMPERATURE sources and vice versa), then unions the serving
    source_ids. A variable no registered adapter serves maps to `[]` (the signal
    for SourceDiscovery, docs/design/07 Phase F). Deterministic, no I/O.
    """
    result: dict[Variable, list[str]] = {}
    for var in variables:
        sids: set[str] = set()
        for member in _equivalence_class(var):
            sids.update(CAPABILITY_INDEX.get(member, ()))
        result[var] = sorted(sids)
    return result


def get_adapter(source_id: str, raw_dir: Path = Path("data/raw")) -> BaseAdapter:
    """Instantiate the adapter registered for source_id under raw_dir."""
    cls = ADAPTER_REGISTRY.get(source_id)
    if cls is None:
        raise KeyError(
            f"Unknown source_id: {source_id!r}. "
            f"Registered sources: {sorted(ADAPTER_REGISTRY)}"
        )
    return cls(raw_dir=raw_dir)
