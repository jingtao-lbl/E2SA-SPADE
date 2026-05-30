# GTN-P (Global Terrestrial Network for Permafrost)

## Role in SPADE

Bootstrap source 2. Borehole ground temperature profiles providing subsurface thermal state data. Complements CALM's active layer thickness with depth-resolved temperature.

## Access

| Method | URL | Format | Priority |
|---|---|---|---|
| PANGAEA 2025 MAGT product (recommended) | https://doi.pangaea.de/10.1594/PANGAEA.972992 | Tab-delimited text, CC-BY 4.0 | 1st |
| NSIDC G10015 (Alaska deep boreholes) | https://nsidc.org/data/g10015/versions/1 | ASCII text | 2nd |
| GTN-P data platform (new Jan 2026) | https://data.gtn-p.org/ | CSV, NetCDF | 3rd |
| Legacy database | https://gtnpdatabase.org/boreholes | Excel downloads | 4th |

No authentication required for any of these.

## Summary

GTN-P is the international monitoring network for the Permafrost Essential Climate Variable under GCOS. It aggregates two programs: TSP (Thermal State of Permafrost, borehole temperatures) and CALM (active layer thickness, covered separately). Database contains 1,389 boreholes globally, 311 stations in the 2025 PANGAEA MAGT product (1980-2021). Alaska has 24 USGS deep boreholes plus many UAF-maintained sites.

## Variables

**Borehole temperature (TSP)**
- Ground temperature profiles at multiple depths (degrees C)
- Mean Annual Ground Temperature (MAGT) at depth of Zero Annual Amplitude
- Some sites include air temperature and snow thickness

**Derived metadata at borehole sites**
- Permafrost zone (continuous, discontinuous, sporadic, isolated)
- Vegetation type, elevation, geomorphology, lithology

## Data format (PANGAEA 2025, recommended)

13 fields per record: Event label, Name, Latitude, Longitude, DATE/TIME (ISO 8601), Frequency, Depth (m below surface, positive downward), Temperature (degrees C, annual mean), Provenance, Author(s), GTN-P ID, Reference (original), Reference (secondary).

23 standardized depth levels: 0, 0.1, 0.2, 0.25, 0.4, 0.5, 0.6, 0.75, 0.8, 1.0, 1.2, 1.5, 1.6, 2.0, 2.4, 2.5, 3.0, 3.2, 4.0, 5.0, 10.0, 15.0, 20.0 m.

## Spatial coverage

- 1,389 boreholes globally. 311 in PANGAEA 2025 MAGT product.
- Alaska: 24 USGS deep boreholes on Arctic Slope (68.5-71.2N, 148.3-161.1W), plus 200+ UAF boreholes (depths 1-380 m).
- 73% of all GTN-P boreholes are shallower than 25 m. Deep profile data is sparse.

## Temporal coverage

- PANGAEA 2025 MAGT: 1980-2021 (41 years)
- NSIDC Alaska deep boreholes: 1973-2014
- Measurement frequencies vary: hourly (continuous loggers), seasonal (manual), or annual means only

## Known gotchas

1. **Low metadata completeness.** Only 50% of boreholes and 63% of active layer sites have complete metadata (elevation, vegetation, drilling date).
2. **Heterogeneous measurement frequencies.** Some boreholes have hourly logger data, others have a few manual readings per year. PANGAEA annual MAGT products exclude years with >20% missing values.
3. **Pre-1984 vs post-1984 methods.** Pre-1984 Alaska data used fixed-depth discrete readings (every 1.5 or 3.0 m). Post-1984 used continuous logging during probe descent. Different data density and noise.
4. **Water intrusion artifacts.** Sudden warming/cooling spikes from water entering borehole or cable. Hard to flag automatically.
5. **Thermistor drift.** Moisture exposure can introduce spurious trends indistinguishable from real warming.
6. **Slope orientation bias.** Boreholes have preferential slope orientations, creating systematic temperature bias.
7. **Excel download quirks (legacy database).** Date formatting, decimal separators vary by locale. Not always ISO 8601.
8. **Deduplication needed.** Same borehole may appear in PANGAEA, gtnpdatabase, and NSIDC. Use GTN-P ID as canonical key.
9. **Wide format in older PANGAEA products.** The 2021 MAGT product uses one column per year (1978-2016). Requires wide-to-long pivot.

## Adapter design notes

**Schema mapping.** One row per (borehole, depth, time) measurement.
- obs_type: `ObservationType.PROFILE`
- variable: `Variable.GROUND_TEMPERATURE`
- value: temperature in degrees C
- unit: "degC"
- latitude/longitude: decimal degrees, WGS84
- depth_m: meters below surface (positive downward)
- time_start/time_end: ISO 8601 date (annual for MAGT, time_end = time_start)
- provenance.source_id: "gtnp"
- extra: borehole_id, site_name, gtnp_id, permafrost_zone, measurement_frequency, elevation_m

**Recommended ingestion order.**
1. PANGAEA 2025 MAGT product (broadest coverage, clean TSV, standardized depths)
2. NSIDC G10015 (24 Alaska deep boreholes, 1973-2014, ASCII) for deep Alaska profiles
3. gtnpdatabase.org individual downloads for specific sites not covered above

**Fetch strategy.** PANGAEA: single download, small file. NSIDC: per-borehole ASCII files via HTTPS. Compute sha256 for each.

**Deduplication.** Use GTN-P borehole ID as the canonical key across sources. If the same (borehole_id, depth, date) appears from multiple sources, prefer PANGAEA (standardized quality) over legacy database (raw).

**Unit test fixture.** A 20-row TSV with 3 boreholes at different depths, including one Alaska borehole and one with missing temperature values.
