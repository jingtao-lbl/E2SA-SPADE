"""Connector layer: one connector per data center (Option C, docs/design/15-16).

A *connector* owns access to a data center — authentication, search, and fetch.
A data center (Arctic Data Center, PANGAEA, NASA Earthdata, ESS-DIVE, Zenodo)
hosts many datasets, so the access logic lives once at the center level rather
than being re-implemented in every per-dataset adapter.

Relationship to adapters (`e2sa/data/base.py`):

    BaseConnector   (per data center)   auth + search + fetch
        ^
        | adapter.data_center names its connector; adapter.fetch delegates here
        |
    BaseAdapter     (per dataset)       parse_to_schema + serves + structure

The split is additive. An adapter that sets `data_center` delegates its `fetch`
to the named connector (so the package-fetch logic is written once); an adapter
that leaves `data_center` as None keeps doing its own fetch (legacy, untouched).

`search` lets a research question discover *new* datasets at a center given a
variable/bbox/time filter — something a per-dataset adapter cannot do. It may
ship as a documented stub per center initially; the known-DOI / on-disk fetch
path works without it.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

from e2sa.data.base import DatasetInfo, FetchResult


class BaseConnector(ABC):
    """Abstract base for one data center's access layer.

    Subclasses set `data_center` (the registry key) and implement `search`
    and `fetch`. `raw_root` is the top-level raw-data directory (the same
    `data/raw` the adapter is given); a connector fetches a dataset's package
    into `raw_root / <data_center> / <dataset_id>` (Option C raw layout,
    docs/design/15-16).
    """

    data_center: ClassVar[str]

    def __init__(self, raw_root: Path = Path("data/raw")) -> None:
        self.raw_root = Path(raw_root)

    @abstractmethod
    def search(
        self,
        *,
        variables: list[str] | None = None,
        bbox: tuple[float, float, float, float] | None = None,
        time_range: tuple[str, str] | None = None,
    ) -> list[DatasetInfo]:
        """Query the data center's API for datasets matching the filters.

        Returns candidate DatasetInfos. May be a documented stub initially
        (return an empty list); the known-DOI / on-disk fetch path does not
        depend on it.
        """

    @abstractmethod
    def fetch(self, dataset_id: str) -> FetchResult:
        """Download the dataset's package into `raw_root / dataset_id`.

        Must be idempotent (skip re-download when the package is already on
        disk and verifies) and record access_timestamp + content_checksum.
        """


CONNECTOR_REGISTRY: dict[str, type[BaseConnector]] = {}


def register_connector(cls: type[BaseConnector]) -> type[BaseConnector]:
    """Class decorator: register a connector under its `data_center` key."""
    key = cls.data_center
    if key in CONNECTOR_REGISTRY and CONNECTOR_REGISTRY[key] is not cls:
        raise ValueError(f"connector already registered for data center {key!r}")
    CONNECTOR_REGISTRY[key] = cls
    return cls


def get_connector(
    data_center: str, raw_root: Path = Path("data/raw")
) -> BaseConnector:
    """Instantiate the connector registered for `data_center`.

    Lazily imports `e2sa.data.connectors` so registration side effects fire
    without the registry module importing every connector at module load.
    """
    if data_center not in CONNECTOR_REGISTRY:
        import e2sa.data.connectors  # noqa: F401  (registration side effects)
    try:
        cls = CONNECTOR_REGISTRY[data_center]
    except KeyError as exc:
        known = ", ".join(sorted(CONNECTOR_REGISTRY)) or "(none)"
        raise KeyError(
            f"no connector registered for data center {data_center!r}. "
            f"Known: {known}"
        ) from exc
    return cls(raw_root=raw_root)
