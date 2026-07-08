# Data Source: NASA ABoVE via ORNL DAAC

**Date:** April 11, 2026
**Purpose:** Reference document for permafrost-related datasets from the Arctic-Boreal Vulnerability Experiment (ABoVE), accessed through the ORNL Distributed Active Archive Center (DAAC).

---

## 1. What It Is

**NASA ABoVE** (Arctic-Boreal Vulnerability Experiment) is a NASA Terrestrial Ecology Program field campaign that began in 2015 and runs for approximately 10 years. It links field-based, process-level studies with geospatial data products derived from airborne and satellite sensors, focused on understanding ecosystem vulnerability and resilience to environmental change in Arctic and boreal regions. The campaign has produced over 300 data products and 500+ publications.

**ORNL DAAC** (Oak Ridge National Laboratory Distributed Active Archive Center) is one of NASA's Earth Observing System Data and Information System (EOSDIS) data centers, specializing in terrestrial biogeochemistry, ecology, and environmental processes. It hosts over 1,954 datasets total. Three DAACs host ABoVE data: ORNL DAAC (biogeochemistry, ecology, soils), ASF DAAC (SAR), and NSIDC DAAC (cryosphere).


## 2. Key URLs

| Resource | URL |
|----------|-----|
| ABoVE project page | https://above.nasa.gov/ |
| ABoVE at Earthdata | https://www.earthdata.nasa.gov/data/projects/above |
| ORNL DAAC ABoVE collection | https://daac.ornl.gov/cgi-bin/dataset_lister.pl?p=34 |
| Earthdata Search (for filtered queries) | https://search.earthdata.nasa.gov/ |
| ABoVE Science Cloud | https://above.nasa.gov/ (via Products database link) |

---

## 3. Key Permafrost Datasets for Ground Ice and Thaw Mapping in Alaska

### A. Active Layer Thickness (ALT) -- Gridded Products

| Dataset | DOI / ID | Format | Resolution | Temporal | Notes |
|---------|----------|--------|------------|----------|-------|
| ALT from Remote Sensing Permafrost Model, Alaska | 10.3334/ORNLDAAC/1760 | NetCDF-4 | 1 km | 2001-2015 (annual) | Statewide Alaska, 35 MB, derived from MODIS LST + SMAP soil moisture. Single file. |
| Upscaled ALT in Northern Alaska | 10.3334/ORNLDAAC/2332 | Cloud-optimized GeoTIFF | 30 m | 2014, 2015, 2017 | ML-upscaled from P-band PolSAR. Northern half of Alaska. 3 files. |
| ALT from Airborne L- and P-band SAR (v3) | 10.3334/ORNLDAAC/2004 | NetCDF-4 | 30 m | 2017 | InSAR-derived seasonal subsidence and ALT along 28 flight lines. Includes uncertainty. |

### B. Active Layer Thickness -- In Situ and GPR

| Dataset | DOI / ID | Format | Temporal | Notes |
|---------|----------|--------|----------|-------|
| Soil Moisture and ALT in Alaska and NWT | 10.3334/ORNLDAAC/1903 | CSV | 2008-2020 | 352,719 observations (206k ALT measurements via probing and GPR). Multi-site compilation. |
| Active Layer Soil Characterization, N. Alaska | 10.3334/ORNLDAAC/1759 | CSV | 2018 | Lab-measured soil properties at permafrost sites. |
| Pre-ABoVE GPR Measurements of ALT, North Slope | 10.3334/ORNLDAAC/1265 | CSV | Historical | Ground-penetrating radar transects on Alaska North Slope. |
| Pre-ABoVE ALT and Soil Water Content, Barrow | 10.3334/ORNLDAAC/1355 | CSV | 2013 | 15 km of 500 MHz GPR + probing data at 4 sites. |

### C. InSAR-Derived Subsidence and Deformation

| Dataset | DOI / ID | Format | Resolution | Temporal | Notes |
|---------|----------|--------|------------|----------|-------|
| Pre-ABoVE ReSALT InSAR, Barrow | 10.3334/ORNLDAAC/1266 | GeoTIFF | 30 m | 2006-2011 | Seasonal surface subsidence from InSAR, gridded ALT maps. |
| Pre-ABoVE ReSALT InSAR, Prudhoe Bay | 10.3334/ORNLDAAC/1267 | GeoTIFF | 30 m | 1992-2000 | Mean ReSALT over Prudhoe Bay area. |

### D. Soil Temperature Profiles

| Dataset | DOI / ID | Format | Temporal | Notes |
|---------|----------|--------|----------|-------|
| Soil Temperature Profiles, USArray Stations | 10.3334/ORNLDAAC/1680 | CSV | 2016-2021 | 63 monitoring sites across interior Alaska. Surface to 1.5 m depth. |

### E. Permafrost Distribution and Properties

| Dataset | DOI / ID | Format | Temporal | Notes |
|---------|----------|--------|----------|-------|
| Permafrost Measurements, Y-K Delta | 10.3334/ORNLDAAC/1598 | GeoTIFF + CSV + Shapefile | 2009-2016 | Thaw depth, vegetation types, LiDAR elevation, permafrost probability maps. 7 files, 773 MB. |
| Soil Properties (dielectric, moisture, conductivity) | ORNL DAAC ABoVE collection | CSV | Various | Lab-measured soil physical properties for permafrost sites. |

### F. Integrated / ML-Derived Products

| Dataset | DOI / ID | Format | Resolution | Temporal | Notes |
|---------|----------|--------|------------|----------|-------|
| GeoCryoAI Permafrost, Thaw Depth, C Flux | 10.3334/ORNLDAAC/2371 | TAR (compressed archive) | 1 km | 1960-2022 | **650 GB**. Integrates CALM, GTNP, ITEX, SMALT, STDM, ReSALT, AmeriFlux, NEON, UAVSAR, AVIRIS-NG. Includes thaw depth, ALT, thaw subsidence, CO2/CH4 flux. Published April 2025. |
| AirMOSS P-band SAR Soil Properties | 10.3334/ORNLDAAC/1657 | NetCDF-4 | 30 m | 2014-2017 | ALT, dielectric constant, soil moisture profile, surface roughness. 29 files across 12 sites. |

### G. Thermokarst and Lake Change

| Dataset | DOI / ID | Format | Temporal | Notes |
|---------|----------|--------|----------|-------|
| Thermokarst Lake Photos, Fairbanks | ORNL DAAC ABoVE collection | JPEG/orthophoto | 2014 | High-res orthophotos of 21 thermokarst lakes, 214 km2 area. |
| Historical Lake Shorelines, Fairbanks | 10.3334/ORNLDAAC/1859 | Shapefile | 1949-2009 | 130-275 thermokarst lakes/ponds tracked per year. |

### H. Ecosystem CO2/CH4 Flux Compilations (auxiliary)

Not a core ground-ice dataset, but bundles soil/air/water temperature, soil moisture, and site-level permafrost indicators that can serve as auxiliary covariates or sanity-check anchors for SPADE harmonization.

| Dataset | DOI / ID | Format | Temporal | Notes |
|---------|----------|--------|----------|-------|
| ABCFlux v2: Arctic-Boreal CO2 and CH4 In-situ Flux and Environmental Data | 10.3334/ORNLDAAC/2448 | CSV (2 files, ~32 MB) | 1984-05-01 to 2024-12-31 | Virkkala et al. 2025 compilation of 1,024 Arctic-Boreal flux sites across 11 countries (incl. Alaska). Variables: NEE, GPP, Reco, CH4 (diffusive/ebullitive), soil/air/water T, soil moisture, permafrost indicators. Short name `Arctic_Boreal_CO2_Flux_V2_2448`. Earthdata catalog: https://www.earthdata.nasa.gov/data/catalog/ornl-cloud-arctic-boreal-co2-flux-v2-2448-1. Companion paper: Virkkala et al. 2025 (see §10). |

---

## 4. Data Formats

Formats vary significantly across datasets.

| Format | Typical Use | Datasets |
|--------|-------------|----------|
| **NetCDF-4** (.nc, .nc4) | Gridded spatial products (ALT maps, SAR-derived fields, soil properties) | ALT Remote Sensing Model, AirMOSS, ReSALT v3 |
| **GeoTIFF** (.tif) | Raster maps (permafrost probability, subsidence, upscaled ALT) | Y-K Delta, Pre-ABoVE InSAR, Upscaled ALT (cloud-optimized) |
| **CSV** (.csv) | In situ point measurements (soil temp, thaw depth, soil properties) | STDM, USArray, GPR transects, soil characterization |
| **Shapefile** (.shp/.zip) | Vector features (lake shorelines, site boundaries) | Y-K Delta, Historical Lakes |
| **TAR** (.tar) | Large compressed archives with mixed contents | GeoCryoAI (650 GB) |
| **JPEG** | Field photos and orthophotos | Thermokarst lake imagery |

**Key point for adapter design.** There is no single standard format. An adapter must handle at least NetCDF-4, GeoTIFF, and CSV.

---

## 5. Spatial Coverage

- **Domain.** Alaska and western Canada (Yukon, Northwest Territories). Some datasets cover only northern Alaska (North Slope); others span the full state.
- **Bounding box (typical full domain).** ~54-72 N, ~170-132 W.
- **Resolutions vary widely.**
  - 30 m (SAR-derived, upscaled ALT)
  - 1 km (remote sensing model ALT, GeoCryoAI)
  - Point measurements (in situ CSV datasets)
  - Flight-line swaths (airborne SAR)

---

## 6. Temporal Coverage

| Phase | Years | Notes |
|-------|-------|-------|
| Pre-ABoVE | 1992-2014 | Legacy datasets (Barrow, Prudhoe Bay InSAR; GPR) folded into the ABoVE archive |
| ABoVE Campaign | 2015-2025 | Core field campaign. Major airborne campaigns in 2017 and 2019. |
| Derived products | Vary | Some extend back to 1960 (GeoCryoAI) or 2001 (ALT model). Depend on input data availability. |

---

## 7. Access Method

### License and data use
NASA EOSDIS data, including ABoVE products distributed through ORNL DAAC, are **free and open** and are **public domain as U.S. Government works**, with no period of exclusive access (NASA Earth Science Data and Information Policy, https://www.earthdata.nasa.gov/engage/open-data-services-software-policies/data-information-policy). There is no special data-use agreement for ABoVE. Cite each dataset by its DOI. Public-domain status permits redistribution, but SPADE does not redistribute the data: adapters fetch each granule via `earthaccess` into the gitignored local `projects/spade/data/raw/` tree, and downstream users retrieve it the same way under NASA's open-data terms.

### Authentication
All ORNL DAAC datasets require a free **NASA Earthdata Login** account (https://urs.earthdata.nasa.gov/). No special data use agreements for ABoVE.

### Programmatic Access (Recommended)

**`earthaccess` Python library** (maintained by NSIDC, works across all DAACs).

```python
import earthaccess

# Login (reads ~/.netrc or prompts)
earthaccess.login()

# Search by DOI
results = earthaccess.search_data(
    doi="10.3334/ORNLDAAC/1760",
    temporal=("2001-01-01", "2015-12-31"),
    bounding_box=(-179.18, 55.57, -132.58, 70.21)
)

# Download locally
earthaccess.download(results, local_path="./data/")

# Or stream directly (cloud-hosted datasets, best from us-west-2)
files = earthaccess.open(results)
```

Install: `pip install earthaccess`

### Alternative Access Methods

| Method | Notes |
|--------|-------|
| **CMR API** | REST API at https://cmr.earthdata.nasa.gov/search/. Query by collection concept_id, temporal, spatial. Returns granule URLs. |
| **CMR STAC API** | STAC-compliant endpoint for cloud-native workflows. |
| **Direct HTTPS** | Download from `https://data.ornldaac.earthdata.nasa.gov/` with Earthdata Login cookie/token. |
| **S3 (in-cloud)** | Cloud-hosted datasets accessible via `s3://` from AWS us-west-2. Requires temporary S3 credentials from earthaccess. |
| **Earthdata Search GUI** | Browser-based discovery and download at https://search.earthdata.nasa.gov/. |

### Identifying Datasets

Each dataset has a unique **short_name** and **concept_id** (e.g., `C1297751981-ORNL_DAAC`). Use either `doi`, `short_name`, or `concept_id` in earthaccess/CMR queries.

---

## 8. Known Gotchas

1. **Massive file sizes.** GeoCryoAI is 650 GB. Plan storage and download bandwidth accordingly. Consider subsetting before full download.

2. **Mixed formats within the ABoVE collection.** No single format standard. The same variable (ALT) can appear as NetCDF, GeoTIFF, or CSV depending on the dataset. Adapters must detect format per-file.

3. **Multiple projections.** SAR-derived products often use UTM zones. Remote sensing model products use geographic (lat/lon). GeoTIFF products may use Alaska Albers. Reprojection is required for cross-dataset analysis.

4. **Varying spatial resolutions.** 30 m to 1 km to point-scale. Regridding needed for multi-dataset fusion.

5. **Dataset versioning.** Some datasets have multiple versions (e.g., ReSALT InSAR has v1, v2, v3). Always check for the latest version. Version is part of the CMR query.

6. **Sparse temporal overlap.** Different datasets cover different years. The STDM compilation (2008-2020) is broad but patchy. ALT model covers 2001-2015 only. Airborne campaigns cluster around 2017.

7. **Cloud-hosted vs. on-premises.** Not all ORNL DAAC datasets are cloud-enabled yet. Check `cloud_hosted=True` in earthaccess queries. Cloud-optimized GeoTIFFs (COGs) support range requests; plain GeoTIFFs do not.

8. **ORNL DAAC URL redirects.** The legacy `daac.ornl.gov` URLs now redirect to `earthdata.nasa.gov` and `data.ornldaac.earthdata.nasa.gov`. Programmatic scrapers using old URLs will break.

9. **TAR archives.** GeoCryoAI ships as TAR files, not individual granules. Must download the full archive before extracting individual variables.

10. **Quality flags and uncertainty.** Not all datasets include uncertainty estimates. SAR-derived ALT products generally include uncertainty; in situ compilations have variable QC across contributing networks.

---

## 9. Adapter Design Notes

### Strategy: One Adapter, Multiple Dataset Handlers

A single `ABoVEAdapter` class should handle the heterogeneity through a registry of dataset-specific handlers.

```
ABoVEAdapter
  |-- authenticate(earthdata_login)
  |-- search(doi_or_shortname, bbox, temporal)
  |-- download(granules, local_path)
  |-- load(dataset_key) --> dispatches to format handler
       |-- _load_netcdf(path)    --> xarray.Dataset
       |-- _load_geotiff(path)   --> xarray.DataArray (via rioxarray)
       |-- _load_csv(path)       --> pandas.DataFrame / geopandas.GeoDataFrame
       |-- _load_tar(path)       --> extract, then recurse
  |-- harmonize(datasets) --> common grid, CRS, time axis
```

### Key Design Decisions

1. **Use `earthaccess` as the unified access layer.** It handles authentication, CMR search, and download/streaming for all DAACs. Avoids writing custom HTTP/S3 logic.

2. **Dataset registry (config-driven).** Store metadata per dataset (DOI, short_name, format, CRS, resolution, variables of interest) in a YAML/JSON config. Adding a new ABoVE dataset means adding a config entry, not new code.

3. **Format detection.** Dispatch based on file extension (.nc/.nc4 to xarray, .tif to rioxarray, .csv to pandas). Fall back to config hint if extension is ambiguous.

4. **Lazy loading.** For large datasets (GeoCryoAI at 650 GB), support bounding-box and temporal subsetting before loading into memory. Use `xarray.open_dataset(chunks=...)` for dask-backed lazy reads.

5. **CRS normalization.** Reproject everything to a common CRS (EPSG:3338 Alaska Albers or EPSG:4326 geographic) on load. Store original CRS in metadata.

6. **Resolution harmonization.** Do not resample automatically. Provide a `regrid(target_resolution)` method. Let the caller decide the target grid.

7. **Point-to-grid bridging.** For CSV point data (STDM, soil temp), provide a `to_geodataframe()` method with coordinate columns mapped. Gridding (kriging, nearest-neighbor) is a separate step.

8. **Version pinning.** Config should specify dataset version. Default to latest but allow override.

### Priority Datasets for ARES

For ground ice content mapping and thaw prediction, prioritize in this order:

1. **STDM compilation** (DOI 1903) -- largest in situ ALT + soil moisture dataset, multi-decade
2. **ALT Remote Sensing Model** (DOI 1760) -- statewide 1 km annual ALT, 2001-2015
3. **Upscaled ALT** (DOI 2332) -- 30 m resolution, northern Alaska
4. **ReSALT InSAR v3** (DOI 2004) -- subsidence + ALT from SAR, 30 m
5. **USArray Soil Temperature** (DOI 1680) -- depth profiles at 63 sites
6. **GeoCryoAI** (DOI 2371) -- integrated ML product, but 650 GB and requires careful handling
7. **Y-K Delta Permafrost** (DOI 1598) -- permafrost probability maps (regional)

---

## 10. References

### Key papers

- **Schaefer, K., Clayton, L. K., Battaglia, M. J., Bourgeau-Chavez, L. L., Chen, R. H., Chen, A. C., Chen, J., Bakian-Dogaheh, K., Douglas, T. A., Grelick, S. E., Iwahana, G., Jafarov, E., Liu, L., Ludwig, S., Michaelides, R. J., Moghaddam, M., Natali, S., Panda, S. K., Parsekian, A. D., … Zhao, Y.** (2021). ABoVE: Soil Moisture and Active Layer Thickness in Alaska and NWT, Canada, 2008-2020 (Version 1). ORNL Distributed Active Archive Center. https://doi.org/10.3334/ORNLDAAC/1903. Dataset citation for the built `above_stdm` adapter (STDM compilation, DOI 1903), verbatim from the adapter.
- **Miller, C. E., Griffith, P. C., Goetz, S. J., Hoy, E. E., Pinto, N., McCubbin, I. B., Thorpe, A. K., et al.** (2019). An overview of ABoVE airborne campaign data acquisitions and science opportunities. *Environmental Research Letters* 14(8):080201. doi:10.1088/1748-9326/ab0d44. Project-level overview of ABoVE airborne campaign data; cite for general ABoVE framing.
- **Virkkala, A.-M., et al.** (2025). ABCFlux v2: Arctic-boreal CO2 and CH4 monthly flux observations and ancillary information across terrestrial and freshwater ecosystems. *Earth System Science Data* preprint essd-2025-585. doi:10.5194/essd-2025-585. Companion paper for the ABCFlux v2 dataset (ORNLDAAC/2448, §3.H above). 1,024 unique sites, 1984-2024, 23,656 flux site-months across terrestrial and freshwater Arctic-boreal ecosystems.

### Web resources

- ABoVE Project: https://above.nasa.gov/
- ABoVE at Earthdata: https://www.earthdata.nasa.gov/data/projects/above
- ORNL DAAC: https://daac.ornl.gov/
- earthaccess library: https://github.com/nsidc/earthaccess
- earthaccess docs: https://earthaccess.readthedocs.io/
- CMR API: https://cmr.earthdata.nasa.gov/search/
- Earthdata Login: https://urs.earthdata.nasa.gov/
