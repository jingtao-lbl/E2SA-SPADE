"""User-identity config loader for the CLI.

Reads `~/.config/e2sa/config.toml`. Falls back to `git config user.name` /
`user.email` if the config file is absent. Used by `e2sa user --json` and to
populate run.yaml authorship at `e2sa init`.
"""
from __future__ import annotations

import shutil
import subprocess
import tomllib
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "e2sa" / "config.toml"


def load_user() -> dict[str, str]:
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open("rb") as f:
            data = tomllib.load(f)
        user = data.get("user", {})
        if user.get("name") and user.get("email"):
            return {
                "name": str(user["name"]),
                "email": str(user["email"]),
                "affiliation": str(user.get("affiliation", "")),
                "source": str(CONFIG_PATH),
            }

    name = _git_config("user.name") or "unknown"
    email = _git_config("user.email") or "unknown@unknown"
    return {
        "name": name,
        "email": email,
        "affiliation": "",
        "source": "git-config-fallback",
    }


def _git_config(key: str) -> str | None:
    if shutil.which("git") is None:
        return None
    try:
        out = subprocess.run(
            ["git", "config", "--get", key],
            capture_output=True,
            text=True,
            check=False,
        )
        value = out.stdout.strip()
        return value or None
    except OSError:
        return None
