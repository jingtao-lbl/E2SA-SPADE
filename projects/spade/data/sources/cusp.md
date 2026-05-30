# CUSP (CommUnity near-Surface Permafrost dataset)

Schwenk, J. et al. (in active development). CUSP: CommUnity near-Surface Permafrost dataset.
Los Alamos National Laboratory. https://github.com/jonschwenk/cusp

Cited in the DOE ECRP FY26 proposal narrative §3.1.1 as a SPADE data source via collaborator Joel Rowland (LANL).

## Role in SPADE

Labeled near-surface permafrost observations. CUSP synthesizes permafrost presence, active layer thickness, and thaw-depth measurements compiled from published sources, research groups, collaborator contributions, and the maintainers' own field work. The maintainers describe CUSP as "the largest collection of permafrost presence and active layer measurements" they are aware of.

For SPADE specifically, CUSP provides:

1. A pan-Arctic complement to [alaska_thaw_db.md](alaska_thaw_db.md) (Webb et al. 2026), which is Alaska-only. CUSP extends the observation footprint beyond Alaska.
2. A near-surface permafrost presence/absence signal for conditioning the SPADE ice content model.
3. Active layer thickness observations that overlap with [calm.md](calm.md) (CALM network) but draw from a broader set of contributing studies and methods.
4. A live, versioned synthesis (CSV-based, GitHub-hosted) that the SPADE agent can re-fetch as new versions land.

## Access

| Field | Value |
|---|---|
| Repository | https://github.com/jonschwenk/cusp |
| Documentation | https://jonschwenk.github.io/cusp/ |
| Format | CSV + BibTeX |
| License | LANL / DOE-NNSA grant, Triad National Security, LLC. Permissive: reproduce, derivative works, distribute (see `LICENSE.txt` in the repo) |
| DOI | None as of 2026-05-29 (no formal release yet) |
| Versioning | `vX.Y` filename suffix scheme; current state is "Unreleased" per `CHANGELOG.md` |
| Authentication | None (public GitHub repo) |

Acquisition is by cloning or fetching specific raw-file URLs from the GitHub repository.

```bash
git clone https://github.com/jonschwenk/cusp.git
# or, for a single file
curl -L -o cusp_v0.1.csv https://raw.githubusercontent.com/jonschwenk/cusp/main/data/cusp_v0.1.csv
```

(Exact file paths and version tags should be verified at fetch time since the repo is under active development. The `vX.Y` scheme is the filename convention but no semver-style git tag has been pushed yet.)

## Summary

CUSP is a tabular synthesis of permafrost observations across the northern circumpolar region. The dataset is delivered as three coordinated files per version:

- `cusp_vX.Y.csv` — main observations table (permafrost presence, ALT, thaw depth, with provenance per row)
- `cusp_features_vX.Y.csv` — environmental features sampled at each observation location (e.g., terrain from ArcticDEM v4 2 m mosaic via Google Earth Engine)
- `cusp_sources_vX.Y.bib` — BibTeX bibliography of contributing studies

The repository also ships command-line Python utilities for aggregations, feature-sampling operations, citation-list generation for downstream papers, and reconstruction of CUSP from its original sources.

## Variables

Per the documentation (https://jonschwenk.github.io/cusp/), CUSP records cover:

- Near-surface permafrost presence/absence
- Active layer thickness
- Thaw depth
- Related field observations contributed by upstream studies

Specific column names, units, and the full schema should be confirmed against the `cusp_vX.Y.csv` header and the schema page in the project documentation at fetch time. The schema page slug was not stable as of 2026-05-29 (returned 404 on direct access); start from https://jonschwenk.github.io/cusp/ and follow the in-site navigation.

## Data format

- **Main observations and features**: CSV
- **Citations**: BibTeX

Tabular, one row per observation. Coordinates included per row (assumed WGS84 unless the schema documents otherwise).

## Spatial coverage

Pan-Arctic / northern circumpolar. Exact bounding box not enumerated in the available documentation as of 2026-05-29; should be confirmed by inspecting the lat/lon ranges in `cusp_vX.Y.csv` after fetch. Alaska is included.

## Temporal coverage

Multi-decadal, drawing from published permafrost monitoring studies that span the late 20th century through present. Specific date range to be confirmed from the observation timestamps in `cusp_vX.Y.csv` after fetch.

## Versioning and update cadence

`vX.Y` filename suffix. As of 2026-05-29 the `CHANGELOG.md` lists only an "Unreleased" section, suggesting no v1.0 has been declared yet. The unreleased work includes:

- Supported module entry points for build, aggregation, QC, and feature-sampling operations
- Deterministic ID generation
- Canonical CSV outputs for observations
- Structured TOML metadata for source processing
- Terrain features switched to UMN/PGC/ArcticDEM/V4/2m_mosaic
- Earth Engine request optimization

Pinning to a specific commit SHA (rather than `main`) is recommended for reproducibility until the project starts cutting versioned releases.

## Known gotchas

1. **No formal release tag yet.** The `vX.Y` filename suffix is internal versioning, not a git tag. Reproducibility requires pinning to a commit SHA.
2. **No DOI yet.** Cite the GitHub repository and commit SHA until a Zenodo or other registry DOI is minted.
3. **Active development.** Schema and module entry points are still stabilizing per the changelog. Expect breaking changes between commits.
4. **Government license, not a standard open-source license.** The Triad/LANL grant is broad and permissive, but is not OSI-recognized. Downstream consumers concerned with OSI compliance should record the license terms explicitly rather than mapping to BSD/MIT/Apache.
5. **Feature sampling depends on Google Earth Engine.** The `cusp_features_vX.Y.csv` companion file is generated by sampling environmental layers (notably ArcticDEM v4 2 m mosaic) via GEE. Re-generating features requires GEE credentials.
6. **Heterogeneity of upstream sources.** Like the Alaska Thaw DB and CALM, CUSP aggregates across study designs and measurement methods. Field-by-field method tagging should be preserved when ingesting.

## Adapter design notes

**Observation type.** `ObservationType.POINT` for permafrost presence and surface-only measurements; `ObservationType.PROFILE` for active layer thickness and thaw depth measurements that include a depth axis.

**Variable mapping.**
- Permafrost presence/absence -> a categorical permafrost-presence variable (extend the unified schema if no equivalent exists)
- Active layer thickness -> `Variable.ACTIVE_LAYER_THICKNESS` (consistent with CALM and ABoVE adapters)
- Thaw depth -> `Variable.THAW_DEPTH` (or align with how the Alaska Thaw DB adapter handles thaw-event records)

**Provenance.** Each row in `cusp_vX.Y.csv` should carry its upstream-study DOI / BibTeX key from `cusp_sources_vX.Y.bib` into the Observation's extra metadata, so the per-record source attribution survives ingestion. This matches the pattern used in the Alaska Thaw DB adapter.

**Fetch strategy.** Single-shot download of the three vX.Y files from the GitHub repo, pinned to a specific commit SHA. SHA256 checksum on each file. The repository is small enough that a full mirror is feasible if desired.

**Environmental features.** The `cusp_features_vX.Y.csv` companion is optional for SPADE ingestion. If SPADE generates its own environmental features at the same locations (via the harmonization module), include the CUSP features only as a comparison signal, not as the primary feature layer. This avoids GEE-dependent reproducibility.

**Relationship to other SPADE sources.**

- Complements [[alaska_thaw_db]] by extending the geographic footprint beyond Alaska.
- Overlaps with [[calm]] on active layer thickness; CUSP draws from a broader study set, CALM is the long-running standardized network. Deduplicate at ingestion time where the same site/year appears in both.
- The terrain features in `cusp_features_vX.Y.csv` come from ArcticDEM v4, which is also a SPADE roadmap source ([PGC] in DMSP §1).

## Citation

A formal paper or Zenodo DOI is not yet available as of 2026-05-29. Until one lands, cite as:

> Schwenk, J. et al. CUSP: CommUnity near-Surface Permafrost dataset. Los Alamos National Laboratory. https://github.com/jonschwenk/cusp (accessed YYYY-MM-DD, commit `<sha>`).

When the project publishes a paper or mints a DOI, update this section and the BibTeX in any downstream SPADE deliverables.

## SPADE collaboration context

ECRP FY26 proposal narrative §3.1.1 names CUSP (with collaborator Rowland, Appendix 7) as one of the SPADE-ingested observation streams. The collaboration channel is via Joel Rowland at LANL. Jon Schwenk (also LANL) is the GitHub maintainer.
