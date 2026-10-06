"""Data roots, resolved on every call (not at import) so tests can point them at fixtures.

Env overrides: MX_DATA_DIR (default data/mx), MX_CORPUS_DIR (default corpus_mx),
MX_STORE_DIR (default <OUT_DIR>/mx_store).
"""

from __future__ import annotations

import os
from pathlib import Path

from extractor import config


def root() -> Path:
    return config.ROOT


def data_root() -> Path:
    return Path(os.getenv("MX_DATA_DIR", config.ROOT / "data" / "mx"))


def corpus_root() -> Path:
    return Path(os.getenv("MX_CORPUS_DIR", config.ROOT / "corpus_mx"))


def store_dir() -> Path:
    return Path(os.getenv("MX_STORE_DIR", config.OUT_DIR / "mx_store"))


def validation_path() -> Path:
    return config.OUT_DIR / "mx_validation.json"


def resolve(p: str, corpus: Path) -> Path:
    """Manifest paths are repo-relative ("corpus_mx/fed/CCF.txt"); also accept corpus-relative."""
    path = Path(p)
    if path.is_absolute():
        return path
    for base in (corpus.parent, corpus, config.ROOT):
        if (base / path).exists():
            return base / path
    return corpus.parent / path
