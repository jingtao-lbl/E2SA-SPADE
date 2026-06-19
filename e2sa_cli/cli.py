"""Click entry point for the `e2sa` CLI."""
from __future__ import annotations

import click

from e2sa_cli import __version__
from e2sa_cli.commands import acquire as acquire_cmd
from e2sa_cli.commands import catalog as catalog_cmd
from e2sa_cli.commands import init as init_cmd
from e2sa_cli.commands import user as user_cmd
from e2sa_cli.commands import validate as validate_cmd


@click.group()
@click.version_option(__version__, prog_name="e2sa")
def cli() -> None:
    """E2SA: End-to-End Science Agent command-line interface."""


cli.add_command(acquire_cmd.acquire_cmd)
cli.add_command(catalog_cmd.catalog_grp)
cli.add_command(init_cmd.init)
cli.add_command(user_cmd.user)
cli.add_command(validate_cmd.validate)
