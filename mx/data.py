"""Everything the /mx routes read, loaded once and verified in memory (never from a stale out/)."""

from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path

from . import paths
from .contracts import ClauseTemplate, load_clauses
from .verify import ValidationReport, VerifiedRequirement, verify_all
from .zones import ZonesIndex, load_zones


@dataclass
class MxData:
    report: ValidationReport
    verified: dict[str, VerifiedRequirement]
    zones: ZonesIndex | None
    zones_error: str | None
    clauses: list[ClauseTemplate]
    clauses_error: str | None

    @property
    def docs(self):
        return self.report.sources.docs


def load(data_root: Path | None = None, corpus_root: Path | None = None) -> MxData:
    data_root = data_root or paths.data_root()
    corpus_root = corpus_root or paths.corpus_root()
    report = verify_all(data_root, corpus_root)
    known = set(report.sources.valid())
    zones, zerr = None, None
    zpath = data_root / "zones.json"
    if zpath.exists():
        try:
            zones = load_zones(zpath, known)
        except (ValueError, KeyError, TypeError) as e:
            zerr = f"zones.json ilegible: {e}"
    else:
        zerr = "zones.json todavía no existe"
    clauses, cerr = [], None
    cpath = data_root / "contract_clauses.yaml"
    try:
        clauses = load_clauses(cpath)
    except FileNotFoundError:
        cerr = "contract_clauses.yaml no existe"
    except Exception as e:  # noqa: BLE001 - surfaced as 503 detail
        cerr = f"contract_clauses.yaml inválido: {e}"
    return MxData(report, report.verified(), zones, zerr, clauses, cerr)


@functools.lru_cache(maxsize=1)
def current() -> MxData:
    return load()
