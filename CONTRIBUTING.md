# Contributing to E2SA / SPADE

A short, practical guide to the workflow and conventions in this repository. New
to the project? Start with `projects/spade/ONBOARDING.md`, then keep this open as
the conventions cheat-sheet. The authoritative, longer-form rules live in
`CLAUDE.md` (framework) and `projects/spade/CLAUDE.md` (project).

---

## Branch and pull-request workflow

Nobody commits to `main` directly. Every change goes on a branch and through a
reviewed pull request. This is a strict team convention enforced by review, not by
the platform (the private repo is on a plan without branch protection), so the
discipline is on each contributor.

```bash
git checkout main && git pull
git checkout -b <yourname>/<short-description>   # e.g. yourname/add-neon-adapter
# ... work, commit ...
git push -u origin <yourname>/<short-description>
# open a PR against main on GitHub; a maintainer reviews and merges
```

Keep a branch focused on one logical change. Smaller PRs get reviewed faster and
merge cleaner.

## Commit messages

Plain, descriptive messages. State what the change does.

**No attribution trailers of any kind.** Do not add `Co-Authored-By:`, do not add
AI tool credits, do not add a human name in the message body. The git author
metadata already records who committed. This is a hard repository rule.

## Coding rules (the short version)

The full list is in `CLAUDE.md` under "Rules when coding." The essentials:

- **Think before coding.** State assumptions; ask when unsure instead of guessing.
- **Simplicity first.** The minimum change that solves the problem. Nothing
  speculative.
- **Surgical changes.** Touch only what you must. Do not reformat or "improve"
  adjacent code. Match the existing style.
- **Read before you write.** Read the function, its callers, and shared utilities
  before adding code near them.
- **Fail loud.** "Done" is wrong if anything was skipped. Surface uncertainty
  rather than hiding it.

## Code style and tests

- Format with `black`, lint with `ruff`, type-check with `mypy`. Dataframes are
  validated with `pandera` at module boundaries.
- Public functions get a short docstring: input contract, output contract, side
  effects. No decorative comments.
- One adapter module per data source under `e2sa/data/`. The adapter interface
  (`list_available`, `fetch`, `parse_to_schema`) is fixed; add functionality
  inside the adapter, not in callers.
- Every adapter has a unit test against a tiny fixture in `tests/fixtures/`.
  Run the suite before opening a PR:
  ```bash
  source e2sa_env/bin/activate
  pytest -q
  ```
- Integration tests that hit real APIs run only when `E2E_LIVE=1` is set, so the
  default suite stays fast and offline.

## Runs: where analysis lives

Analysis work is scaffolded into self-contained runs, never created by hand:

```bash
e2sa init spade <run_id>          # projects/spade/runs/<run_id>/
e2sa validate <run_id>            # structural checks before you open a PR
```

Notebooks live in the run's `notebooks/` folder with **saved outputs** (the
validator checks this). Run-specific intermediates go in the run's `data/`;
reusable project-wide data goes in `projects/spade/data/`. Both data trees are
gitignored.

## Never commit

- Anything under `data/` (raw, interim, processed) or `projects/spade/data/`.
- `.env` or any credentials or API keys. Build your `.env` from `.env.example`.
- Large binaries, model checkpoints, downloaded datasets.
- Generated artifacts that are reproducible from code.

If `git status` shows one of these as staged, stop and remove it before
committing.

## Provenance (non-negotiable)

Every downloaded record carries provenance: source id, source URL or endpoint,
access timestamp (UTC), sha256 checksum, license, adapter version, schema
version. Raw downloads are immutable; never edit them. Anything derived must be
reproducible from raw plus code.

## Progress logs

Before switching tasks, write a dated entry
(`YYYYMMDDx_Topic_In_Title_Case.md`) using the standard header and sections
documented in `CLAUDE.md`. This is the project's durable, reviewable memory and
the primary way asynchronous reviewers catch up on your work. The intern writes
to `memory/dev_logs_intern/`; the maintainer uses `memory/dev_logs/`. The split
keeps the two log streams from colliding on same-day filenames.

## Public mirror caution

A filtered subset of this repo is published to a separate public mirror.
Contributors work only in this private repo; releases to the mirror are handled
by the maintainer. Internal-only content (dev logs, `CLAUDE.md` files, anything
referencing internal strategy or funding) must never be copied into public-facing
files. Do not push to the public mirror.
