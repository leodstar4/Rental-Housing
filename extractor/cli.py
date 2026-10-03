"""Command line: ``python -m extractor.cli <command>``."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import typer

from . import config

app = typer.Typer(add_completion=False, help="Module A: extract rule records from the corpus.")


@app.command("extract-all")
def extract_all(
    no_cache: bool = typer.Option(False, help="Ignore .cache/ and call the API."),
    only: list[str] = typer.Option(None, help="Restrict to these doc_ids (repeatable)."),
) -> None:
    """Load -> clean -> extract -> validate -> normalize; writes the internal snapshot."""
    raise NotImplementedError


@app.command("extract-doc")
def extract_doc(
    path: Path = typer.Argument(..., exists=True, dir_okay=False, help="corpus/text/Dxxx.txt"),
    no_cache: bool = typer.Option(False),
) -> None:
    """Extract one document and print its rules (debugging)."""
    raise NotImplementedError


@app.command("export")
def export(
    as_of: datetime = typer.Option(
        config.DEFAULT_AS_OF.isoformat(), formats=["%Y-%m-%d"], help="Query date."
    ),
    out: Path = typer.Option(config.RULES_PATH),
) -> None:
    """Compute status for ``--as-of`` and write schema-valid ``rules.json``."""
    raise NotImplementedError


@app.command("smoke-check")
def smoke_check() -> None:
    """Offline checks, no API calls: corpus loads, every kept clean line is
    verbatim in raw_text, schema loads, cached rules (if any) still validate."""
    raise NotImplementedError


if __name__ == "__main__":
    app()
