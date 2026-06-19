"""`e2sa catalog <subcommand>` - inspect the DuckDB catalog.

Subcommands:
    inspect   Print a structured summary of catalog contents (sources, datasets,
              files, bytes, variables, parseable count, md5 mismatches).

Both interactive users and other commands can re-run these to see what's in
the catalog without writing one-off Python.
"""
from __future__ import annotations

import sys
from pathlib import Path

import click

from e2sa.catalog import DEFAULT_CATALOG_PATH, open_catalog


@click.group("catalog")
def catalog_grp() -> None:
    """Inspect and operate on the DuckDB catalog."""


@catalog_grp.command("query")
@click.option(
    "--variable",
    "variable_name",
    required=True,
    help="Variable name (Variable enum value, e.g. soil_temperature).",
)
@click.option(
    "--catalog",
    "catalog_path",
    type=click.Path(file_okay=True, dir_okay=False, path_type=Path),
    default=None,
    help=f"DuckDB catalog file. Defaults to {DEFAULT_CATALOG_PATH}.",
)
def query_cmd(variable_name: str, catalog_path: Path | None) -> None:
    """Find which datasets in the catalog contain a given variable.

    Example:
        e2sa catalog query --variable soil_temperature \\
            --catalog projects/spade/data/catalog.duckdb
    """
    path = catalog_path if catalog_path is not None else DEFAULT_CATALOG_PATH
    if not Path(path).exists():
        click.echo(f"error: catalog not found at {path}", err=True)
        sys.exit(2)
    conn = open_catalog(path)
    try:
        report = _build_query_report(conn, variable_name)
    finally:
        conn.close()
    click.echo(report)


def _build_query_report(conn, variable_name: str) -> str:
    """Build the per-variable hit report.

    Joins dataset_variables → package_files → datasets so each hit carries
    source_id, dataset_id, dataset_name, file relative_path, and unit.
    Only parseable=TRUE rows count as a "hit" (raw unmapped names would be
    misleading matches).
    """
    rows = conn.execute(
        """
        SELECT
            d.source_id,
            dv.dataset_id,
            d.name,
            pf.relative_path,
            COALESCE(dv.unit, ''),
            COALESCE(dv.depth_range, '')
        FROM dataset_variables dv
        JOIN package_files pf ON dv.file_id = pf.file_id
        JOIN datasets d ON dv.dataset_id = d.dataset_id
        WHERE dv.variable = ? AND dv.parseable = TRUE
        ORDER BY d.source_id, dv.dataset_id, pf.relative_path
        """,
        [variable_name],
    ).fetchall()

    if not rows:
        return (
            f"no hits for variable {variable_name!r} in catalog.\n"
            f"(try `e2sa catalog inspect` to see mapped variables actually present)"
        )

    lines = [
        f"=== query: variable = {variable_name!r} ===",
        f"\n{len(rows)} file(s) across {len({(r[0], r[1]) for r in rows})} dataset(s):\n",
    ]
    cur_ds = None
    for src, dsid, name, rel, unit, depth in rows:
        ds_key = (src, dsid)
        if ds_key != cur_ds:
            short_name = (name or "")[:60]
            lines.append(f"[{src}] {dsid}  ({short_name})")
            cur_ds = ds_key
        unit_str = f" [{unit}]" if unit else ""
        depth_str = f" depth={depth}" if depth else ""
        lines.append(f"  {rel}{unit_str}{depth_str}")
    return "\n".join(lines)


@catalog_grp.command("inspect")
@click.option(
    "--catalog",
    "catalog_path",
    type=click.Path(file_okay=True, dir_okay=False, path_type=Path),
    default=None,
    help=f"Path to the DuckDB catalog file. Defaults to {DEFAULT_CATALOG_PATH}.",
)
def inspect_cmd(catalog_path: Path | None) -> None:
    """Print a structured summary of catalog contents."""
    path = catalog_path if catalog_path is not None else DEFAULT_CATALOG_PATH
    if not Path(path).exists():
        click.echo(f"error: catalog not found at {path}", err=True)
        sys.exit(2)
    conn = open_catalog(path)
    try:
        report = _build_report(conn)
    finally:
        conn.close()
    click.echo(report)


def _build_report(conn) -> str:
    """Build the inspect report as a single string.

    Pulled out as a pure-ish function (takes a connection, returns text) so
    tests can assert on the output without invoking the CLI wrapper.
    """
    lines: list[str] = []
    lines.append("=== E2SA catalog inspect ===")

    # Summary counts
    n_datasets = conn.execute("SELECT COUNT(*) FROM datasets").fetchone()[0]
    n_downloads = conn.execute("SELECT COUNT(*) FROM downloads").fetchone()[0]
    n_files = conn.execute("SELECT COUNT(*) FROM package_files").fetchone()[0]
    n_vars = conn.execute("SELECT COUNT(*) FROM dataset_variables").fetchone()[0]
    n_parseable = conn.execute(
        "SELECT COUNT(*) FROM dataset_variables WHERE parseable = TRUE"
    ).fetchone()[0]
    total_bytes = conn.execute(
        "SELECT COALESCE(SUM(bytes), 0) FROM package_files"
    ).fetchone()[0]

    lines.append(
        f"\ntotals: {n_datasets} datasets, {n_downloads} downloads, "
        f"{n_files} files ({_fmt_bytes(total_bytes)}), "
        f"{n_vars} variables ({n_parseable} parseable)"
    )

    if n_datasets == 0:
        lines.append("\n(catalog is empty)")
        return "\n".join(lines)

    # Per-dataset breakdown
    lines.append("\nper-dataset:")
    rows = conn.execute(
        """
        SELECT
            d.source_id,
            d.dataset_id,
            d.name,
            (SELECT COUNT(*) FROM package_files pf
             WHERE pf.dataset_id = d.dataset_id) AS n_files,
            (SELECT COALESCE(SUM(bytes), 0) FROM package_files pf
             WHERE pf.dataset_id = d.dataset_id) AS bytes,
            (SELECT COUNT(*) FROM dataset_variables dv
             WHERE dv.dataset_id = d.dataset_id) AS n_vars,
            (SELECT COUNT(*) FROM dataset_variables dv
             WHERE dv.dataset_id = d.dataset_id
               AND dv.parseable = TRUE) AS n_parseable
        FROM datasets d
        ORDER BY d.source_id, d.dataset_id
        """
    ).fetchall()
    for src, dsid, name, nf, nb, nv, np in rows:
        short_name = (name or "")[:50]
        lines.append(
            f"  [{src:18s}] {dsid:35s} "
            f"files={nf:>3d} bytes={_fmt_bytes(nb):>10s} "
            f"vars={nv:>4d} parseable={np:>3d}"
        )
        if short_name:
            lines.append(f"    name: {short_name}")

    # Mapped-variable breakdown across the whole catalog
    by_var = conn.execute(
        """
        SELECT variable, COUNT(*) FROM dataset_variables
        WHERE parseable = TRUE
        GROUP BY variable ORDER BY COUNT(*) DESC
        """
    ).fetchall()
    if by_var:
        lines.append("\nmapped variables (across all datasets):")
        for var, n in by_var:
            lines.append(f"  {var:30s} {n:>4d}")

    # Number of observations ingested (if any)
    try:
        n_obs = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        if n_obs:
            lines.append(f"\nobservations ingested: {n_obs:,}")
    except Exception:
        pass  # observations table may not exist on older catalogs

    return "\n".join(lines)


def _fmt_bytes(n: int) -> str:
    """Human-friendly byte formatting (B / KB / MB / GB)."""
    if n < 1024:
        return f"{n}B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f}KB"
    if n < 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024):.1f}MB"
    return f"{n / (1024 * 1024 * 1024):.2f}GB"
