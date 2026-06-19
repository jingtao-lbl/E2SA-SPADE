"""`e2sa acquire --source <id> --dataset <id>` - fetch + index one dataset.

Thin wrapper over `e2sa.orchestrator.acquire`. Both the interactive agent
(via direct Python import) and a shell user (via this CLI) hit the same
underlying function, so behavior stays consistent.
"""
from __future__ import annotations

import sys
from pathlib import Path

import click

from e2sa.orchestrator import acquire


@click.command("acquire")
@click.option(
    "--source",
    "source_id",
    required=True,
    help="Source ID (e.g. ess_dive, calm, gtnp, alaska_thaw_db, above).",
)
@click.option(
    "--dataset",
    "dataset_id",
    required=True,
    help="Dataset ID the adapter knows (e.g. sloan_2014_barrow_soil).",
)
@click.option(
    "--catalog",
    "catalog_path",
    type=click.Path(file_okay=True, dir_okay=False, path_type=Path),
    default=None,
    help="DuckDB catalog file. Defaults to data/catalog.duckdb.",
)
@click.option(
    "--raw-dir",
    "raw_dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("data/raw"),
    show_default=True,
    help="Root directory for raw downloads. Adapters write to raw-dir/<source>/<dataset>/.",
)
@click.option(
    "--parse",
    "parse",
    is_flag=True,
    default=False,
    help="Also parse the dataset and ingest Observations into the catalog. "
         "Off by default (parse is on-demand per docs/design/04).",
)
def acquire_cmd(
    source_id: str, dataset_id: str, catalog_path: Path | None, raw_dir: Path,
    parse: bool,
) -> None:
    """Fetch a dataset and index it into the catalog end-to-end.

    Example:
        e2sa acquire --source ess_dive --dataset sloan_2014_barrow_soil \\
            --raw-dir projects/spade/data/raw \\
            --catalog projects/spade/data/catalog.duckdb
    """
    try:
        result = acquire(
            source_id=source_id,
            dataset_id=dataset_id,
            catalog_path=catalog_path,
            raw_dir=raw_dir,
            parse=parse,
        )
    except KeyError as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(2)
    except Exception as e:
        click.echo(f"error: {type(e).__name__}: {e}", err=True)
        sys.exit(1)

    click.echo(f"acquired: {result.source_id}/{result.dataset_id}")
    click.echo(f"  dataset_dir: {result.dataset_dir}")
    click.echo(f"  files downloaded: {result.n_files_downloaded}")
    click.echo(f"  bytes: {result.bytes_downloaded:,}")
    click.echo(f"  indexed files: {result.n_indexed_files}")
    click.echo(f"  indexed variables: {result.n_indexed_variables}")
    click.echo(f"  package checksum: {result.package_checksum}")
    if result.n_observations_ingested:
        click.echo(f"  observations ingested: {result.n_observations_ingested:,}")
    if result.md5_mismatches:
        n = len(result.md5_mismatches)
        sample = result.md5_mismatches[:3]
        more = "..." if n > 3 else ""
        click.echo(
            f"  WARNING: {n} md5 mismatch(es) vs manifest: {sample}{more}",
            err=True,
        )
