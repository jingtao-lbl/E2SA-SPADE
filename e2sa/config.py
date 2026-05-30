"""Run configuration for an E2SA pipeline invocation."""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel


class RunConfig(BaseModel):
    name: str
    question: str
    sources: list[str]
    variables: list[str]
    bbox: tuple[float, float, float, float] | None = None
    time_range: tuple[str, str] | None = None
    model: str = "geocryoai_baseline"
    output_dir: Path = Path("data/processed")


def load_run_config(path: Path | str) -> RunConfig:
    with open(path) as f:
        data = yaml.safe_load(f)
    return RunConfig(**data)
