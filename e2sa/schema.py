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
    EXCESS_ICE_CONTENT = "excess_ice_content"
    VOLUMETRIC_WATER_CONTENT = "volumetric_water_content"
    THAW_EVENT_LABEL = "thaw_event_label"
    LAND_SURFACE_TEMPERATURE = "land_surface_temperature"
    SURFACE_DEFORMATION = "surface_deformation"
    NDVI = "ndvi"
    ELEVATION = "elevation"
    SNOW_DEPTH = "snow_depth"
    PRECIPITATION = "precipitation"
    AIR_TEMPERATURE = "air_temperature"


#: Canonical unit per measured Variable (UDUNITS / CF-style strings; "1" = a
#: dimensionless fraction). After harmonization, an Observation.unit MUST equal
#: CANONICAL_UNITS[variable]; e2sa.harmonize.units enforces and converts to it.
#: Categorical variables (THAW_EVENT_LABEL) carry no canonical unit and are absent
#: here on purpose -- callers treat "not in CANONICAL_UNITS" as "no conversion".
#: The last four are Tier-3 remote-sensing/forcing variables that no current adapter
#: emits yet; their canonical units were ratified by Jing 2026-06-29 (degC for both
#: temperatures to match ground/soil; mm/day rate for precipitation; mm cumulative
#: displacement for surface deformation). See memory/dev_logs/20260629d.
CANONICAL_UNITS: dict[Variable, str] = {
    Variable.ACTIVE_LAYER_THICKNESS: "m",
    Variable.SOIL_TEMPERATURE: "degC",
    Variable.GROUND_TEMPERATURE: "degC",
    Variable.VOLUMETRIC_ICE_CONTENT: "1",
    Variable.EXCESS_ICE_CONTENT: "1",
    Variable.VOLUMETRIC_WATER_CONTENT: "1",
    Variable.NDVI: "1",
    Variable.ELEVATION: "m",
    Variable.SNOW_DEPTH: "m",
    Variable.LAND_SURFACE_TEMPERATURE: "degC",
    Variable.SURFACE_DEFORMATION: "mm",  # cumulative vertical displacement (Jing 2026-06-29)
    Variable.PRECIPITATION: "mm/day",  # rate (Jing 2026-06-29)
    Variable.AIR_TEMPERATURE: "degC",
}

#: Inclusive physical bounds per measured Variable, expressed in CANONICAL_UNITS.
#: Single source of truth for the QC value-range check (e2sa.qc reads this), so units
#: and QC thresholds never drift. A value outside the range is reported by QC, never
#: silently dropped. The last four match their ratified CANONICAL_UNITS (Jing 2026-06-29).
VALID_RANGE: dict[Variable, tuple[float, float]] = {
    Variable.ACTIVE_LAYER_THICKNESS: (0.0, 10.0),       # m
    Variable.SOIL_TEMPERATURE: (-60.0, 40.0),           # degC
    Variable.GROUND_TEMPERATURE: (-60.0, 40.0),         # degC
    Variable.VOLUMETRIC_ICE_CONTENT: (0.0, 1.0),        # fraction
    Variable.EXCESS_ICE_CONTENT: (0.0, 1.0),            # fraction
    Variable.VOLUMETRIC_WATER_CONTENT: (0.0, 1.0),      # fraction
    Variable.NDVI: (-1.0, 1.0),                         # dimensionless
    Variable.ELEVATION: (-500.0, 9000.0),               # m
    Variable.SNOW_DEPTH: (0.0, 30.0),                   # m
    Variable.LAND_SURFACE_TEMPERATURE: (-60.0, 50.0),   # degC
    Variable.SURFACE_DEFORMATION: (-1000.0, 1000.0),    # mm (cumulative, +/-1 m)
    Variable.PRECIPITATION: (0.0, 2000.0),              # mm/day
    Variable.AIR_TEMPERATURE: (-70.0, 50.0),            # degC
}


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
