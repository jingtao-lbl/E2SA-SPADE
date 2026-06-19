---
name: e2sa-add-data-source
description: Onboard a new data source (data center, archive, or dataset) into an E2SA project. Use when the human or agent has found a dataset to bring in, is inspecting a new archive, or says "add a data source", "onboard this dataset", "I found data at X", or after downloading data from a center not yet documented. Walks the full procedure: inventory check, download whole package, inspect (format/metadata-standard/CRS/license/citation), write the project-named source card, update the sources index and data-center registry, capture a finding, and credential setup. Always uses the latest dataset version and records a full citation.
allowed-tools: [Read, Glob, Grep, Write, Edit, Bash, WebFetch]
---

# e2sa-add-data-source

The reusable procedure for bringing a new data source into an E2SA project (SPADE is the current one). Distilled from the SPADE Task A familiarization work. It is the durable home for "what to do when we onboard a dataset," replacing ad-hoc task instructions and the day-one ONBOARDING doc.

Canonical references this skill enforces:
- Folder + source-card convention: `projects/<project>/data/sources/README.md`.
- Indexer / metadata-standard design + the data-center registry: `docs/design/04_retrieval_and_indexing.md`.
- Credential setup: `projects/<project>/design/04_credentials_setup.md` and `docs/design/05_agent_credentials.md`.
- The fetch/index/parse architecture and both agent modes: `docs/design/07_dataset_acquisition_workflow.md`.

## When to fire

- The human or the agent identifies a dataset to bring into the project.
- A new archive/data center is encountered that is not yet in the data-center registry.
- Right after a manual download of a dataset that has no source card yet (the gap Josue's Kanevskiy download hit).

## The procedure

1. **Inventory check first (non-negotiable).** Before downloading anything, scan `projects/<project>/data/sources/README.md`, the existing `data/raw/` tree, and the DuckDB catalog for the dataset/variables/region/time. If it is already on disk, do not re-download; note the match and ask the human whether to reuse.

2. **Use the latest version.** If the data center versions datasets (e.g. the NSF Arctic Data Center mints a new DOI per version), select the **latest** version. Record the exact version DOI and version date; never silently use an older version.

3. **Download the whole package** into immutable `projects/<project>/data/raw/<source>/<dataset>/` (per `CLAUDE.md` §9). Fetch every file in the dataset, not just the one variable needed today (the fetch-whole-package / index / parse-on-demand model). Confirm `.gitignore` covers `**/data/raw/`.
   - **Folder naming** (all lowercase snake_case, no spaces): `<source>` = the source-card / adapter `source_id` name — the program/network (`ngee_arctic`, `above`, `calm`) or a standalone-dataset slug (`kanevskiy_cryostratigraphy`), **not the data center**. `<dataset>` = a descriptive slug with a stable identifier + year (`barrow_soil_2014`); for a standalone dataset where `<source>` already names it, `<dataset>` may be the version (`v2024`) or omitted. So a NGEE-Arctic dataset goes in `raw/ngee_arctic/barrow_soil_2014/`, not `raw/ess_dive/...`.

4. **Inspect and record**, per the cross-source findings template:
   - Metadata standard (ESS-DIVE FLMD + `*_dd.csv`? DataONE EML XML + BagIt? something else) — this decides the indexer parser path.
   - File format(s), variable names + units, cadence, spatial scope.
   - CRS via the tiered fallback: machine-readable metadata → PDF user-file → assume WGS84 with a low-confidence flag. Record which tier.
   - Missing-value sentinel(s), per file (`-9999`? blank? is `0` meaningful?).
   - License, and the **full dataset citation + landing/download page URL** (required).
   - Gotchas: header/footer line counts (read declared values), metadata-vs-disk filename mismatches (match by content / BagIt MD5, never trust declared names), encoding, identifier whitespace.

5. **Write the source card.** Create `projects/<project>/data/sources/<project_or_dataset_name>.md`, named by **project/dataset, not data center** (the data center goes inside under "Access"). **Card granularity:** one card per program/network or per standalone dataset; a single dataset *within* a tracked program (e.g. Sloan 2014 inside NGEE-Arctic) is recorded in the program card's dataset list + the catalog provenance, not given its own card. Sections: Role, Access, Summary, Variables, Format, Coverage, Gotchas, Adapter design notes. **Required: the full citation and the landing page.** Add a row to the appropriate table in the sources `README.md`, and a row to the **Data centers (registry)** there if the hosting center is new (keep it in sync with `docs/design/04_retrieval_and_indexing.md`).

6. **Capture a finding** in `memory/knowledge/findings/` if the archive surfaced a novel convention or trap worth carrying across datasets (a new metadata standard, a new CRS-omission mode, etc.).

7. **Credentials.** If fetching needs auth, follow `projects/<project>/design/04_credentials_setup.md` (and the design spec `docs/design/05_agent_credentials.md`). Never commit a secret. Note: many archives (ESS-DIVE, ADC) have open downloads; auth is only for programmatic search.

8. **Adapter + index (later).** If the source needs an adapter, write `e2sa/data/<source>.py` extending `BaseAdapter`, then index the package with `index_package`. This is downstream of the look-first inspection above.

## Guardrails

- Latest version always; record the version DOI + date.
- Source cards by project, not data center; data center under "Access" and in the registry.
- Full citation + landing page are required fields.
- Raw is immutable; no secrets in the repo; cite every dataset per its required citation when used.

## Changelog
- 2026-06-17: Adopted the Changelog convention (`docs/design/09_skill_evolution.md`); prior history is in git.
