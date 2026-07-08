"""Concrete data-center connectors.

Importing this package registers every connector in `CONNECTOR_REGISTRY`
(via the `@register_connector` decorator on each class). `get_connector`
imports this package lazily so registration fires on first use.
"""
from __future__ import annotations

from e2sa.data.connectors import (
    arctic_data_center,  # noqa: F401
    earthdata,  # noqa: F401
    ess_dive,  # noqa: F401
    pangaea,  # noqa: F401
    pgc,  # noqa: F401
    zenodo,  # noqa: F401
)

__all__ = ["arctic_data_center", "earthdata", "ess_dive", "pangaea", "pgc", "zenodo"]
