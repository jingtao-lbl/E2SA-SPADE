"""Abstract base class for all E2SA data source adapters.

Every data source (CALM, GTN-P, Alaska Thaw DB, ABoVE, etc.) implements
a concrete subclass of BaseAdapter. The interface has three methods:

    list_available  - discover what datasets/variables the source offers
    fetch           - download raw data to data/raw/<source>/
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
from typing import Any

from e2sa.schema import Observation


@dataclass
class DatasetInfo:
    """Metadata about one available dataset within a source."""

    dataset_id: str
    name: str
    description: str
    variables: list[str]
    spatial_coverage: str
    temporal_coverage: str
    format: str
    url: str | None = None
    license: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class FetchResult:
    """Record of a completed download."""

    dataset_id: str
    local_path: Path
    bytes_downloaded: int
    access_timestamp: datetime
    content_checksum: str
    source_url: str


class BaseAdapter(ABC):
    """Abstract base for all data source adapters.

    Subclasses must set `source_id` and `adapter_version` as class
    attributes and implement the three abstract methods.
    """

    source_id: str
    adapter_version: str

    def __init__(self, raw_dir: Path = Path("data/raw")) -> None:
        self.raw_dir = raw_dir / self.source_id
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    def list_available(self) -> list[DatasetInfo]:
        """Return metadata for every dataset this source offers.

        This method should be cheap (hit a catalog endpoint or return
        a hardcoded list), not download full data files.
        """

    @abstractmethod
    def fetch(self, dataset_id: str) -> FetchResult:
        """Download the specified dataset to self.raw_dir.

        Must be idempotent: if the file already exists on disk with a
        matching checksum, skip the download and return the existing
        FetchResult. Must record access_timestamp and content_checksum.
        """

    @abstractmethod
    def parse_to_schema(self, fetch_result: FetchResult) -> list[Observation]:
        """Parse a fetched raw file into a list of Observation records.

        Each Observation must have complete provenance. The adapter is
        responsible for unit conversion to SI, CRS normalization to
        WGS84, and populating qc_flags with any source-level quality
        indicators.
        """
