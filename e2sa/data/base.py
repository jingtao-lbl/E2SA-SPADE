"""Abstract base class for all E2SA data source adapters.

Every data source (CALM, GTN-P, Alaska Thaw DB, ABoVE, etc.) implements
a concrete subclass of BaseAdapter. The interface has three methods:

    list_available  - discover what datasets/variables the source offers
    fetch           - download raw data (connector-backed: into
                      data/raw/<data_center>/<dataset_id>/)
    parse_to_schema - convert raw files into Observation records

Adapters are the extension point for adding new data sources. The rest
of the pipeline (harmonization, QC, catalog) depends only on this
interface, not on source-specific details.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

from e2sa.schema import Observation, Variable


@dataclass
class DatasetInfo:
    """Metadata about one available dataset within a source."""

    dataset_id: str
    name: str
    description: str
    #: The variables the SOURCE dataset CONTAINS (descriptive; written to the staged
    #: metadata bundle). This is NOT the emit-contract: what an adapter actually parses
    #: into Observations is its class-level `serves`, which is the only thing the
    #: capability index / matcher reads. The two can differ on purpose, e.g. a dataset
    #: that contains soil temperature + VWC + thaw depth but whose adapter serves only
    #: soil temperature today (the gap is the "extend this adapter" backlog signal).
    variables: list[str]
    spatial_coverage: str
    temporal_coverage: str
    format: str
    url: str | None = None
    license: str | None = None
    #: Full scholarly citation (the form the source requires). Feeds the staged
    #: PROVENANCE.json + CITATION.cff so each dataset folder is self-describing.
    citation: str | None = None
    #: Related works / references the source lists (DOIs or full citations).
    references: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class FetchResult:
    """Record of a completed download.

    For single-file fetches (CALM, GTN-P, Alaska Thaw, the original ABoVE
    pattern) `local_path` is the file itself and `files` is empty.
    For whole-package fetches (ESS-DIVE, BagIt packages) `local_path` is
    the package root directory and `files` lists every downloaded file
    relative to or under that root. The indexer (`index_package`) walks
    `files` when it is non-empty, otherwise it walks `local_path`.
    """

    dataset_id: str
    local_path: Path
    bytes_downloaded: int
    access_timestamp: datetime
    content_checksum: str
    source_url: str
    files: list[Path] = field(default_factory=list)


class BaseAdapter(ABC):
    """Abstract base for all data source adapters.

    Subclasses must set `source_id` and `adapter_version` as class
    attributes and implement the three abstract methods.
    """

    source_id: str
    adapter_version: str

    #: Coarse routing declaration: the Variables this adapter can emit. Read at
    #: import by the capability index in registry.py (Variable -> source_id) so a
    #: research question can find this source without instantiating the adapter or
    #: hitting an API. MUST be a subset of what parse_to_schema actually emits
    #: (enforced by tests). Empty default = not yet declared (invisible to
    #: discovery). See docs/design/14.
    serves: ClassVar[frozenset[Variable]] = frozenset()

    #: The data center this adapter's data comes from (the connector that owns
    #: auth + search + fetch). When set, the adapter's `fetch` delegates to that
    #: connector (Option C, docs/design/15-16). None = legacy self-contained
    #: adapter that does its own fetch. Additive: existing adapters keep working.
    data_center: ClassVar[str | None] = None

    def __init__(self, raw_dir: Path = Path("data/raw")) -> None:
        if self.data_center is not None:
            # Connector-backed (Option C): the connector owns the on-disk layout
            # (raw_dir/<data_center>/<dataset_id>/). Keep the top-level raw dir;
            # the per-source folder is neither used nor created here.
            self.raw_dir = raw_dir
        else:
            # Legacy/standalone adapter that fetches into raw_dir/<source_id>/.
            self.raw_dir = raw_dir / self.source_id
            self.raw_dir.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    def list_available(self) -> list[DatasetInfo]:
        """Return metadata for every dataset this source offers.

        This method should be cheap (hit a catalog endpoint or return
        a hardcoded list), not download full data files.
        """

    def fetch(self, dataset_id: str) -> FetchResult:
        """Download the dataset and return a FetchResult.

        Default (connector-backed, Option C): delegate to the adapter's
        `data_center` connector, which owns auth + download + idempotency and
        writes `raw_dir/<data_center>/<dataset_id>/`. A legacy/standalone adapter
        (no `data_center`) must override this with its own fetch.
        """
        if self.data_center is None:
            raise NotImplementedError(
                f"{type(self).__name__} sets no `data_center`; override fetch() "
                f"or set `data_center` to a registered connector."
            )
        # Lazy import: base.py must not import connector.py at module load
        # (connector.py imports base.py -> circular).
        from e2sa.data.connector import get_connector

        return get_connector(self.data_center, self.raw_dir).fetch(dataset_id)

    @abstractmethod
    def parse_to_schema(self, fetch_result: FetchResult) -> list[Observation]:
        """Parse a fetched raw file into a list of Observation records.

        Each Observation must have complete provenance. The adapter is
        responsible for unit conversion to SI, CRS normalization to
        WGS84, and populating qc_flags with any source-level quality
        indicators.
        """
