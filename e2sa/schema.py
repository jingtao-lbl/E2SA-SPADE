"""Unified observation schema (v0) for E2SA.

This is the canonical representation that all data adapters harmonize into.
Adapters receive heterogeneous source formats (CSV, NetCDF, GeoTIFF, tabular)
and emit Observation records with consistent units, CRS (WGS84), and
provenance metadata.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

SCHEMA_VERSION = "0.1.0"


class ObservationType(str, Enum):
    POINT = "point"
    PROFILE = "profile"
    GRID_CELL = "grid_cell"
    EVENT = "event"


class Variable(str, Enum):
    ACTIVE_LAYER_THICKNESS = "active_layer_thickness"
    SOIL_TEMPERATURE = "soil_temperature"
    GROUND_TEMPERATURE = "ground_temperature"
    VOLUMETRIC_ICE_CONTENT = "volumetric_ice_content"
    VOLUMETRIC_WATER_CONTENT = "volumetric_water_content"
    THAW_EVENT_LABEL = "thaw_event_label"
    LAND_SURFACE_TEMPERATURE = "land_surface_temperature"
    SURFACE_DEFORMATION = "surface_deformation"
    NDVI = "ndvi"
    ELEVATION = "elevation"
    SNOW_DEPTH = "snow_depth"
    PRECIPITATION = "precipitation"
    AIR_TEMPERATURE = "air_temperature"


class Provenance(BaseModel):
    source_id: str
    source_url: str | None = None
    access_timestamp: datetime
    content_checksum: str
    license: str | None = None
    adapter_version: str
    schema_version: str = Field(default=SCHEMA_VERSION)


class Observation(BaseModel):
    obs_id: str
    obs_type: ObservationType
    variable: Variable
    value: float
    unit: str

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    depth_m: float | None = Field(
        default=None, description="Positive downward, meters below surface"
    )

    time_start: datetime | None = None
    time_end: datetime | None = None

    qc_flags: list[str] = Field(default_factory=list)
    provenance: Provenance
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description="Source-specific fields that do not fit the unified schema",
    )
