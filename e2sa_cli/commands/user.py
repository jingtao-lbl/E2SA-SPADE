"""`e2sa user` - print user identity from config or git fallback."""
from __future__ import annotations

import json

import click

from e2sa_cli.config import load_user


@click.command()
@click.option("--json", "as_json", is_flag=True, help="Emit JSON instead of human format.")
def user(as_json: bool) -> None:
    """Print user identity used to author runs."""
    info = load_user()
    if as_json:
        click.echo(json.dumps(info, indent=2, sort_keys=True))
    else:
        click.echo(f"name:        {info['name']}")
        click.echo(f"email:       {info['email']}")
        if info["affiliation"]:
            click.echo(f"affiliation: {info['affiliation']}")
        click.echo(f"source:      {info['source']}")
