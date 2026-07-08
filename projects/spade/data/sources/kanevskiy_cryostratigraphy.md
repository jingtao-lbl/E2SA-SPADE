# Data Source: Kanevskiy 2024 Cryostratigraphy

**Date:** June 17, 2026
**Purpose:** Standalone-dataset card for Kanevskiy, Shur, Jones, and Jorgenson (2024), *Cryostratigraphy and ground-ice content of the upper permafrost in Alaska and Northern Canada, 2018-2023*, hosted on the NSF Arctic Data Center. Per the source-card convention (`README.md`), standalone datasets with their own DOI get their own card; this dataset is not part of a tracked program (NGEE-Arctic, ABoVE, CALM, GTN-P), so it gets one here.

---

## Citation (required)

Kanevskiy, M., Y. Shur, B. Jones, and M. T. Jorgenson. 2024. *Cryostratigraphy and ground-ice content of the upper permafrost in Alaska and Northern Canada, 2018-2023*. NSF Arctic Data Center. https://doi.org/10.18739/A2H12V928

When this dataset is used in an analysis, the citation above is the **current-version** form. The local copy on disk is the predecessor version (see "Versioning" below); cite the current DOI regardless.

---

## Role in SPADE

**Direct field-measurement labels for excess-ice content (EIC), the primary anchor variable of the ice-content product** (per `projects/spade/design/01_ice_content_mapping.md`). Sparse but high-quality: 22 sampling campaigns 2018-2023 at 8 Alaska sites (plus 2 Canadian sites that must be filtered out for Alaska-only training). Each campaign carries per-borehole EIC, GMC, VMC, and cryostratigraphic-unit assignments tied to a depth range; several files also carry electrical conductivity. Field methods (SIPRE corer, frozen-then-oven-dried weights per Shur et al. 2021 Methods S1) make these direct measurements rather than inferences from a proxy.

This dataset is one of the **few primary EIC sources** SPADE has located. ESS-DIVE search returned no comparable primary holdings; NSIDC offers cartographic interpretations (Ferrians 1965) and active-layer products, not ice-content cores. Discovery was paper-first (Google Scholar → publication → ADC landing).

---

## Access

| Resource | URL |
|---|---|
| Landing page | https://arcticdata.io/catalog/view/doi:10.18739/A2H12V928 |
| DOI | https://doi.org/10.18739/A2H12V928 |
| DataONE EML object (machine-readable) | https://arcticdata.io/metacat/d1/mn/v2/object/doi:10.18739/A2H12V928 |
| DataONE sysmeta (version chain) | https://arcticdata.io/metacat/d1/mn/v2/meta/doi:10.18739/A2H12V928 |
| Download | "Download All" button on the landing page → single BagIt zip (~59 MB) |

**Data center:** NSF Arctic Data Center (a DataONE member node, operated by NCEAS and UCSB). Open download, no auth required. The DataONE REST API at `arcticdata.io/metacat/d1/mn/v2/` is open for both `object` (the EML XML) and `meta` (the system metadata describing version relationships).

---

## Versioning (latest-version rule)

The latest-version rule in the sources README is non-negotiable for ADC because ADC mints a new DOI per dataset revision. Always download and cite the **current** DOI.

| Field | Value |
|---|---|
| **Current DOI** | `10.18739/A2H12V928` |
| **Current upload date** | 2025-08-08 |
| **Predecessor DOI** | `10.18739/A2QR4NS3D` (uploaded 2024-02-23, obsoleted 2025-08-08) |
| **ORCID rights-holder** | http://orcid.org/0000-0003-0565-0187 |
| **Method to verify** | `GET https://arcticdata.io/metacat/d1/mn/v2/meta/doi:<DOI>` and check whether `<obsoletedBy>` is present. Absence = latest version. |

**Differences between the predecessor and current versions** (from comparing EML + sysmeta): same title, same authors, same publisher, same license, same temporal coverage (2018-2023), same geographic bounding box, same methods references (Shur et al. 2021 Methods S1; French and Shur 2010). The current revision was published ~18 months after the predecessor, almost certainly a corrections/metadata pass (likely fixed the three EML-vs-disk filename mismatches noted in the "Gotchas" section below) and possibly an additional data table. **Structural inspection findings from the predecessor (`memory/dev_logs_intern/20260615a_*`, `memory/knowledge/findings/20260616-archive-metadata-variability.md`) carry forward.**

---

## Summary

The dataset documents cryostratigraphy and ground-ice content of the upper permafrost (typically 0-3 m, occasionally to 5.2 m) at intensively-instrumented sites across northern Alaska and the Canadian Arctic. Each campaign drilled multiple boreholes (typically 4-50, with a transect design) using a SIPRE corer; cores were described, photographed, and sampled in the field, with samples returned to UAF for laboratory determination of gravimetric and volumetric moisture content and excess-ice content. Cryostructure descriptions follow French and Shur (2010) and Kanevskiy et al. (2013) classifications adapted from Russian and North American literature. Ice-content quantification follows Shur et al. (2021), Supporting Information Methods S1.

The dataset is **paired with field photographs and study-area narratives in per-CSV PDF files** — one PDF per CSV. The PDFs contain context the CSV does not: site description, transect history, sampling-design summary, per-unit aggregated EIC results, figure references, and DOIs of related datasets at the same site (e.g. the 2009 Jago River study at `10.18739/A28K8J`). Treat the PDFs as part of the data product, not as optional documentation.

---

## Variables

**Primary (SPADE anchor):** EIC = excess-ice content, % vol.

**Other ground-ice content variables:** GMC (gravimetric moisture content, % wt); VMC (volumetric moisture content, % vol).

**Cryostratigraphic-unit codes** (verbatim from the EML methodStep and from every CSV's 15-line footer; the unit-code-to-description mapping must come from the footer or the EML, not be assumed):

| Code | Meaning |
|---|---|
| ALU | Unfrozen active layer |
| ALF | Frozen active layer, ice-poor |
| TL | Transient layer |
| ALF-TL | Undifferentiated frozen AL / transient layer |
| IL-PD | Intermediate layer, poorly developed |
| IL-WD | Intermediate layer, well developed (EIC > 30-40%) |
| TL-IL | Undifferentiated transient / intermediate |
| SP | Syngenetic permafrost |
| QSP | Quasi-syngenetic permafrost |
| PSP | Para-syngenetic permafrost (thawed and refrozen talik) |

**Massive ice and soil-composition codes:** IW (ice wedge), TCI (thermokarst-cave ice), PFTD (post-fire thaw depth, max), P (peat), M (mineral soil).

**Per-file additions:** four CSVs carry an `EC` column (electrical conductivity); four carry `Elevation` (variably named); one CSV uses a completely different schema reporting layer thicknesses instead of per-sample ice content. See "Gotchas" for the full schema-variation map.

---

## Format

| Aspect | Detail |
|---|---|
| Package format | BagIt 1.0 (single zip; payload at `data/`, metadata at `metadata/`, plus `bagit.txt`, `bag-info.txt`, `manifest-md5.txt`, `tagmanifest-md5.txt`) |
| Metadata standard | EML 2.2.0 single XML at `metadata/science-metadata.xml` (~268 KiB, ~5,500 lines in the predecessor; structure unchanged) |
| File count | 22 CSVs + 22 PDFs (one PDF per CSV, same basename) plus the metadata XML |
| CSV header | 4 header rows: dataset title row, blank row, two-row column header (multi-row spans, e.g. "Coordinates" spans Lat/Lon and "Sample depth" wraps "cm" to the next row). EML's `<physical><numHeaderLines>` declares this. |
| CSV footer | 15-line embedded footer (the abbreviation legend as comma-padded rows). EML's `<physical><numFooterLines>` declares this. **The footer is part of the file but is not data; silent parsing failure if missed.** |
| Per-row depth representation | String ranges (`0-27`, `27-39`, `48-58`) for both `Unit Depth` and `Sample depth`. Stored as text/ordinal in EML. Parser needs range-splitting. |
| Combined-concept column | `Cryostratigraphic units / soils` combines unit code and soil composition with `/` (e.g. `ALU/M+P silt`, `IL-PD/M+P silt`). Parser needs field-splitting. |
| Missing-value sentinel | **Empty cell (blank).** `0` is meaningful (e.g. EIC=0 = no excess ice) and distinct from blank. **No `-9999`.** |
| Character encoding | Latin-1 mojibake observed on en-dashes in legend rows (renders as `�` in UTF-8 terminals). Verify per-file with `file --mime-encoding` or read with `encoding='latin-1'`. |
| CRS | **Not specified in EML.** Lat/lon in degrees only. **Assume WGS84 with a low-confidence flag** (Tier 3 of the indexer's CRS-fallback ladder). |
| Time | Date column only; no time of day; no time-zone indication. |

---

## Coverage

| Aspect | Value |
|---|---|
| **Geographic bounding box** | West -169°, East -70°, North 74°, South 60° (Alaska + Canadian Arctic union) |
| **Temporal** | 2018-2023 (per-campaign destructive sampling) |
| **Vertical** | Surface to ~3 m typical; up to 5.2 m at Jago River |

**Alaska sites (20 of 22 files; the SPADE-relevant subset):**

| Site | Visits | Years |
|---|---|---|
| Utqiagvik (Barrow) | 4 | 2019, 2021, 2022, 2023 |
| Teshekpuk Lake | 4 | 2019, 2021, 2022, 2023 |
| Prudhoe Bay | 4 | 2019, 2020, 2021, 2022 |
| Anaktuvuk River (post-fire) | 2 | 2021, 2022 |
| Point Lay | 2 | 2022, 2023 |
| Toolik | 2 | 2019, 2023 |
| Itkillik | 1 | 2019 |
| Jago | 1 | 2018 |

**Canadian sites (out of scope for SPADE; filter at adapter level):** Bylot (2019), Tuktoyaktuk (2019).

---

## License

CC0 1.0 Universal Public Domain Dedication. https://creativecommons.org/publicdomain/zero/1.0/

No attribution required by license; SPADE still cites the dataset per scholarly norms.

---

## Funding

NSF awards 1820883, 1806213, 1806287 (recorded in EML `<project>` block). Also referenced in companion PDFs.

---

## Gotchas

**Schema variation across the 22 CSVs.** Documented in `memory/knowledge/findings/20260616-archive-metadata-variability.md`; summary:

| Pattern | Files (count) |
|---|---|
| Standard 11 cols (Borehole, Date, Lat, Lon, Unit Depth, Cryo units, Sample depth, GMC%, VMC%, EIC%, Notes) | ~14 |
| + EC column (electrical conductivity) | 4 (Teshekpuk-Lake-Utqiagvik Apr-May 2021, Point Lay June 2022, Teshekpuk Lake July 2021, Utqiagvik July-Aug 2022) |
| + Elevation column (variably named: `Elevation`, `Elevation, m a.s.l.`, `Elevation (2014), m asl`) | 4 (Anaktuvuk River Fire June 2021, Point Lay June 2022, Prudhoe Bay August 2020, Anaktuvuk Fire August 2022) |
| **NO Lat/Lon columns** | 1 (Utqiagvik July 2023) |
| **Completely different schema** (reports layer thicknesses: Borehole, Date, Lat, Lon, ALU, ALF, IL cm, Depth to massive ice cm, TL+IL (PL2) cm, Notes) | 1 (Prudhoe Bay Aug 2022) |

**Column-name aliasing for the same concept.** Adapter must map by concept, not by exact string:

- Borehole: `Borehole` / `Borehole, type of drilling` / `Borehole/Exposure` / `Borehole (B) or Exposure (E)` / `Borehole (B) Exposure (E)` / `Exposure`
- Depth: `Unit Depth` / `Unit Depth, cm` / `Depth` / `Depth, cm`

**EML-vs-disk filename mismatch (predecessor version; may be fixed in current).** In the predecessor three `<entityName>` values did not match the file on disk:

| EML claimed | Actual on disk |
|---|---|
| `Teshekpuk-Utqiagvik-April-May-2022.csv` | `Teshekpuk_Utqiagvik_April_May_2022.csv` |
| `Teshekpuk-July-2022.csv` | `Teshekpuk_July_2022.csv` |
| `Prudhoe Bay-August 2022.csv` | `Prudhoe_Bay_August_2022.csv` |

Whether the 2025-08-08 current version fixes this is unconfirmed; verify after re-downloading. **General lesson regardless:** match files by BagIt `manifest-md5.txt` MD5 sum, not by metadata-declared filename.

**Whitespace in identifiers.** Borehole IDs may carry trailing whitespace (`C1-SI1 ` vs `C1-SI1`). Strip and normalize before any join.

**Blank rows separate boreholes within a single CSV file** (lines like `,,,,,,,,,,`). Parsers that treat blank rows as EOF will truncate.

**The Canadian sites must be filtered for Alaska-only training** (Bylot, Tuktoyaktuk).

---

## Adapter design notes (when one lands)

**Adapter scope.** A single `KanevskiyCryostratigraphyAdapter` is sufficient (one dataset, one DOI). Not part of a portal; no DOI-dispatch needed. If a Tier-2/3 ADC adapter eventually materializes for other ADC datasets, the EML-parsing helpers should be lifted to a shared `e2sa/data/_arctic_data_center/` module rather than duplicated.

**Observation type.** `EVENT` (per-campaign destructive sampling). One observation per (borehole, depth-range) tuple. The dataset is not a time series.

**Variable mapping (to unified schema):**

| Source column | Unified-schema variable |
|---|---|
| EIC, % | `Variable.EXCESS_ICE_CONTENT` (units: dimensionless fraction in [0, 1] after /100) |
| GMC, % | `Variable.GRAVIMETRIC_MOISTURE_CONTENT` |
| VMC, % | `Variable.VOLUMETRIC_MOISTURE_CONTENT` |
| Cryostratigraphic units | `Variable.CRYOSTRATIGRAPHIC_UNIT` (categorical; valid values from the abbreviation table above) |
| EC (where present) | `Variable.SOIL_ELECTRICAL_CONDUCTIVITY` |

**Per-file parsing recipe (drive from EML, not assumptions):**

1. Read `metadata/science-metadata.xml`; locate the `<dataTable>` whose checksum matches the file's BagIt MD5 (not the `<entityName>` string).
2. Read `<physical><numHeaderLines>` and `<numFooterLines>`; pass to `pandas.read_csv(skiprows=, skipfooter=)`.
3. Read `<attributeList>` for per-column types, units, and missing-value conventions; build the dtype map.
4. Read with `encoding="utf-8"`; if `UnicodeDecodeError` on a legend row, fall back to `encoding="latin-1"`.
5. Split string-range columns (`Unit Depth`, `Sample depth`) into `_lo_cm` and `_hi_cm` floats.
6. Split combined-concept column (`Cryostratigraphic units / soils`) on `/` into `cryo_unit` and `soil_composition`.
7. Strip whitespace on all string columns.
8. Drop blank-row borehole separators (or use them to assign a per-borehole row group).
9. Tag observations with `(site, year, month_of_campaign)` from the filename; emit per-row provenance with the dataset DOI + BagIt MD5.

**CRS.** Tier 3 of the indexer CRS-fallback ladder: not in metadata, no companion CRS file, **assume WGS84 with a low-confidence flag in provenance**. Lat/lon are decimal degrees; the bounding box matches WGS84 ranges.

**Provenance.** Each emitted Observation carries: the current dataset DOI (not the predecessor), the BagIt MD5 of the source CSV, the EML `<entityName>` (for traceability even though it may mismatch the filename), the CC0 license, and the campaign-specific note "Direct field measurement; SIPRE corer; Shur et al. 2021 Methods S1". The PDFs are not parsed into provenance text, but the per-CSV PDF basename is recorded in `Provenance.companion_files`.

**Discovery flow** is not needed (single DOI; no portal search). **Authentication** is not needed (open download).

---

## Local copy on disk

| Field | Value |
|---|---|
| Path | `projects/spade/data/raw/arctic_data_center/kanevskiy_2024_cryostratigraphy/` (gitignored) |
| Folder naming | Option C layout `raw/<data_center>/<dataset_id>/` per `CLAUDE.md` §9 (data center `arctic_data_center`, slug `kanevskiy_2024_cryostratigraphy`; set 2026-06-23 with the connector refactor) |
| Version on disk | **Current** (`10.18739/A2H12V928`, uploaded 2025-08-08) |
| How fetched | Automated, via the `arctic_data_center` connector (`e2sa.data.connectors.arctic_data_center`), 2026-06-23. DataONE `packages` BagIt-zip download, no auth. |
| Payload | ~62 MB (61,947,840 bytes, 51 files: 22 CSV + 22 PDF + EML + resource-map RDF + BagIt tag files) |
| BagIt integrity | Verified by the indexer (0 MD5 mismatches). Manual: `cd projects/spade/data/raw/arctic_data_center/kanevskiy_2024_cryostratigraphy && md5sum -c manifest-md5.txt` |

**EML layout note (current version).** Unlike the predecessor (`metadata/science-metadata.xml`), the current-version BagIt places the EML at the package root as `Cryostratigraphy_and_ground_ice_content_of_the_upp.xml`, with data under `data/`. The indexer's `_find_eml` handles both layouts (identify EML by content, not declared path).

---

## Related datasets at the same sites (from PDF narratives)

The per-CSV PDFs reference companion ADC datasets at the same study locations. Worth following up if SPADE needs longer time series at any of these sites:

| Related DOI | Site | Year | Relationship |
|---|---|---|---|
| `10.18739/A28K8J` | Jago River | 2009 | Earlier study at the same transect; 22 boreholes, established baseline |
| `10.18739/A22J6853K` | Jago River | 2018 | Early 2018 release at the same transect (likely an interim or companion package) |

Additional related-dataset DOIs may appear in PDFs not yet inspected (Anaktuvuk Fire, Point Lay, Teshekpuk, Prudhoe Bay, Utqiagvik). Index by parsing the PDFs opening paragraphs.

---

## Verified inputs to this card

- Dev log: `memory/dev_logs_intern/20260615a_Task_A_Arctic_Data_Center_Ice_Content_Inspection.md` (predecessor-version inspection)
- Dev log: `memory/dev_logs_intern/20260616a_Task_A_Deliverables_Comparison_And_Credentials.md` (cross-source comparison drafted from the above)
- Dev log: `memory/dev_logs_intern/20260617a_Kanevskiy_Source_Card_And_Folder_Renames.md` (this session: version verification, folder renames, PDF inspection, card written)
- Finding: `memory/knowledge/findings/20260616-archive-metadata-variability.md` (cross-source archive variability, ESS-DIVE vs ADC)
- Convention: `projects/spade/data/sources/README.md` (source-card and data-center-registry conventions)
- Folder naming rule: `CLAUDE.md` §9
- Skill: `.claude/skills/e2sa-add-data-source/SKILL.md` (the procedure followed to write this card)

---

## References

- Kanevskiy, M., Y. Shur, B. Jones, M. T. Jorgenson. 2024. *Cryostratigraphy and ground-ice content of the upper permafrost in Alaska and Northern Canada, 2018-2023*. NSF Arctic Data Center. https://doi.org/10.18739/A2H12V928
- Shur, Y., M. Kanevskiy, and M. T. Jorgenson. 2021. Methods for ground-ice content quantification. Supporting Information Methods S1, referenced in the Kanevskiy 2024 EML methodStep.
- French, H. M., and Y. Shur. 2010. The principles of cryostratigraphy. *Earth-Science Reviews* 101 (3-4): 190-206.
- Kanevskiy, M., Y. Shur, T. Jorgenson, D. Fortier, M. Stephani, and A. Vasiliev. 2013. Cryostratigraphy and permafrost evolution in the lacustrine lowlands of west-central Alaska. *Permafrost and Periglacial Processes* 24 (1): 14-30.
- EML 2.2.0 specification: https://eml.ecoinformatics.org/
- DataONE Member Node API (Tier 1): https://releases.dataone.org/online/api-documentation-v2.0.1/apis/MN_APIs.html
- BagIt 1.0 (RFC 8493): https://www.rfc-editor.org/rfc/rfc8493

