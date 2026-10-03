"""The sample addresses (``data/sample_addresses.csv``) and their dataset city.

Every column is kept as a string: ZIPs and use codes have leading zeros (``07030``, ``0500``).
"""

from __future__ import annotations

import csv
import functools
import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml

from extractor import config

ADDRESSES_PATH: Path = config.STARTER_DIR / "data" / "sample_addresses.csv"
USE_CODE_MAP_PATH: Path = config.DATA_DIR / "use_code_map.yaml"


@dataclass(frozen=True)
class Address:
    address_id: str
    street_address: str
    postal_city: str
    state: str
    zip: str
    year_built: str
    units: str
    use_code: str
    use_description: str
    source_dataset: str
    retrieved_at: str

    @property
    def dataset_city(self) -> str:
        """Legal city per the source dataset, in rules.json format ("Boston, MA")."""
        d = use_code_map()["datasets"][self.source_dataset]
        return d["city"] if "city" in d else f"{self.postal_city}, {self.state}"


@functools.lru_cache(maxsize=1)
def use_code_map() -> dict:
    return yaml.safe_load(USE_CODE_MAP_PATH.read_text(encoding="utf-8"))


def load_addresses(path: Path | None = None) -> list[Address]:
    with open(path or ADDRESSES_PATH, encoding="utf-8", newline="") as f:
        return [Address(**{k: (v or "").strip() for k, v in row.items()}) for row in csv.DictReader(f)]


def addresses_sha256(path: Path | None = None) -> str:
    return hashlib.sha256((path or ADDRESSES_PATH).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
