"""Address -> jurisdiction stack with the Census Geocoder (``data/jurisdictions.json``).

1. **Batch** (``geographies/addressbatch``, benchmark ``Public_AR_Current``, vintage
   ``Current_Current``, one request for all rows; the service takes up to 10,000): match
   quality, matched address, coordinates, state/county FIPS. NJ rows are sent WITHOUT a ZIP:
   the sample's NJ ZIPs are mostly owner mailing ZIPs (other cities, NY, TX).
   Unmatched rows whose street has zero-padded ordinals ("05TH AV") are sent once more as a
   second batch with the zeros removed ("5TH AV"); a match there records ``retried_street``.
2. **Places**: the batch output has no incorporated place, so each matched point is looked up
   once on ``geographies/coordinates`` (layers States, Counties, Incorporated Places, County
   Subdivisions, Census Designated Places), 4 requests at a time with retries.

Raw responses are versioned in ``data/geocode_raw/`` (``batch_input.csv``,
``batch_output.csv``, ``places.jsonl``) and reused on later runs, so the demo does not depend
on the service; ``--refresh`` queries again.

Stack per address: state, county (informational; rules have no county level), city = the
incorporated place in rules.json format ("Boston city" -> "Boston, MA"), ``match_quality``
(exact | non_exact | no_match) and ``source`` (census | dataset_fallback). Without a match the
dataset city is used with lower certainty. When the geocoder's place differs from the dataset
city, the geocoder wins and the case is listed in ``discrepancies``.
"""

from __future__ import annotations

import csv
import io
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from extractor import config

from .addresses import Address, addresses_sha256, load_addresses

CENSUS = "https://geocoding.geo.census.gov/geocoder"
BENCHMARK, VINTAGE = "Public_AR_Current", "Current_Current"
LAYERS = ["States", "Counties", "Incorporated Places", "County Subdivisions", "Census Designated Places"]
KEEP = ("GEOID", "NAME", "BASENAME", "STUSAB", "LSADC", "FUNCSTAT")
BATCH_MAX = 10_000
WORKERS = 4
RETRIES = 4

RAW_DIR: Path = config.DATA_DIR / "geocode_raw"
JURISDICTIONS_PATH: Path = config.DATA_DIR / "jurisdictions.json"
NO_ZIP_STATES = {"NJ"}  # ZIP column is not the property's ZIP (see module doc)
_BATCH_COLS = ["address_id", "input_address", "match", "match_type", "matched_address", "lonlat",
               "tigerline_id", "side", "state_fips", "county_fips", "tract", "block"]


# --------------------------------------------------------------------------- #
# Census calls
# --------------------------------------------------------------------------- #


def _request(req: urllib.request.Request | str, timeout: int) -> bytes:
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except (urllib.error.URLError, TimeoutError) as e:
            if isinstance(e, urllib.error.HTTPError) and e.code < 500 and e.code != 429:
                raise
            if attempt == RETRIES - 1:
                raise
            time.sleep(2 ** attempt * 2)
    raise AssertionError("unreachable")


def batch_input(addresses: list[Address]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    for a in addresses:
        w.writerow([a.address_id, a.street_address, a.postal_city, a.state,
                    "" if a.state in NO_ZIP_STATES else a.zip])
    return buf.getvalue()


def run_batch(csv_text: str) -> str:
    if csv_text.count("\n") > BATCH_MAX:
        raise ValueError(f"the batch geocoder takes at most {BATCH_MAX} rows")
    b = uuid.uuid4().hex
    fields = [("benchmark", BENCHMARK), ("vintage", VINTAGE)]
    body = "".join(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n' for k, v in fields)
    body += (f'--{b}\r\nContent-Disposition: form-data; name="addressFile"; filename="addresses.csv"\r\n'
             f"Content-Type: text/csv\r\n\r\n{csv_text}\r\n--{b}--\r\n")
    req = urllib.request.Request(f"{CENSUS}/geographies/addressbatch", data=body.encode("utf-8"),
                                 headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    return _request(req, timeout=900).decode("utf-8")


def parse_batch(text: str) -> dict[str, dict]:
    out = {}
    for row in csv.reader(io.StringIO(text)):
        if row:
            out[row[0]] = dict(zip(_BATCH_COLS, row))
    return out


def lookup_point(lon: str, lat: str) -> dict:
    q = urllib.parse.urlencode({"x": lon, "y": lat, "benchmark": BENCHMARK, "vintage": VINTAGE,
                                "layers": ",".join(LAYERS), "format": "json"})
    geo = json.loads(_request(f"{CENSUS}/geographies/coordinates?{q}", timeout=120))["result"]["geographies"]
    return {layer: [{k: g[k] for k in KEEP if k in g} for g in geo.get(layer, [])] for layer in LAYERS}


_ZERO_ORDINAL = re.compile(r"\b0+(\d+)(ST|ND|RD|TH)\b", re.I)


def retry_street(street: str) -> str:
    """Second-pass street spelling: "397 05TH AV" -> "397 5TH AV" (SF assessor zero-pads ordinals)."""
    return _ZERO_ORDINAL.sub(r"\1\2", street)


# --------------------------------------------------------------------------- #
# Raw cache (data/geocode_raw/)
# --------------------------------------------------------------------------- #


def _retry(addresses: list[Address], batch: dict[str, dict], *, refresh: bool, log) -> None:
    """Re-geocode unmatched rows whose street changes under ``retry_street``; a match replaces
    the first result and records ``retried_street``. Raw files: batch_retry_{input,output}.csv."""
    todo = [a for a in addresses if batch.get(a.address_id, {}).get("match") != "Match"
            and retry_street(a.street_address) != a.street_address]
    inp, outp = RAW_DIR / "batch_retry_input.csv", RAW_DIR / "batch_retry_output.csv"
    if not todo:
        return
    csv_text = batch_input([replace(a, street_address=retry_street(a.street_address)) for a in todo])
    if refresh or not outp.exists() or not inp.exists() or inp.read_text(encoding="utf-8") != csv_text:
        log(f"retrying {len(todo)} unmatched addresses with zero-padded ordinals removed...")
        inp.write_text(csv_text, encoding="utf-8", newline="\n")
        outp.write_text(run_batch(csv_text).replace("\r\n", "\n"), encoding="utf-8", newline="\n")
    for aid, row in parse_batch(outp.read_text(encoding="utf-8")).items():
        if row.get("match") == "Match":
            batch[aid] = {**row, "retried_street": retry_street(next(a.street_address for a in todo
                                                                      if a.address_id == aid))}


def fetch(addresses: list[Address], *, refresh: bool = False, log=print) -> tuple[dict, dict]:
    """Batch results and place lookups, from data/geocode_raw/ when present."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    inp, outp, places_path = RAW_DIR / "batch_input.csv", RAW_DIR / "batch_output.csv", RAW_DIR / "places.jsonl"
    csv_text = batch_input(addresses)
    if refresh or not outp.exists() or not inp.exists() or inp.read_text(encoding="utf-8") != csv_text:
        log(f"batch geocoding {len(addresses)} addresses ({BENCHMARK}/{VINTAGE})...")
        t = time.perf_counter()
        inp.write_text(csv_text, encoding="utf-8", newline="\n")
        outp.write_text(run_batch(csv_text).replace("\r\n", "\n"), encoding="utf-8", newline="\n")
        log(f"  done in {time.perf_counter() - t:.0f}s")
        if places_path.exists():
            places_path.unlink()
    batch = parse_batch(outp.read_text(encoding="utf-8"))
    _retry(addresses, batch, refresh=refresh, log=log)

    places: dict[str, dict] = {}
    if places_path.exists():
        for line in places_path.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            places[rec["address_id"]] = rec
    todo = [(aid, b["lonlat"]) for aid, b in batch.items()
            if b.get("match") == "Match" and b.get("lonlat") and (aid not in places or places[aid]["lonlat"] != b["lonlat"])]
    if todo:
        log(f"looking up places for {len(todo)} points ({WORKERS} at a time)...")

        def one(item):
            aid, lonlat = item
            lon, lat = lonlat.split(",")
            return {"address_id": aid, "lonlat": lonlat, "geographies": lookup_point(lon, lat)}

        with ThreadPoolExecutor(WORKERS) as ex:
            for rec in ex.map(one, todo):
                places[rec["address_id"]] = rec
    lines = [json.dumps(places[k], ensure_ascii=False, sort_keys=True) for k in sorted(places)]
    places_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return batch, places


# --------------------------------------------------------------------------- #
# Jurisdiction stack
# --------------------------------------------------------------------------- #


def census_city(place: dict, state: str) -> str:
    """Census place -> rules.json jurisdiction: "Jersey City city" (BASENAME "Jersey City") -> "Jersey City, NJ"."""
    return f"{place['BASENAME']}, {state}"


def build_stack(a: Address, b: dict | None, p: dict | None) -> dict:
    s: dict = {"address_id": a.address_id, "dataset_city": a.dataset_city,
               "input": {"street": a.street_address, "city": a.postal_city, "state": a.state,
                         "zip_sent": "" if a.state in NO_ZIP_STATES else a.zip}}
    matched = bool(b and b.get("match") == "Match" and p)
    if not matched:
        why = "no batch row" if not b else {"No_Match": "no match", "Tie": "tie (several candidates)"}.get(
            b.get("match"), b.get("match")) if b.get("match") != "Match" else "no place lookup"
        s.update({"match_quality": "no_match", "census_result": why, "source": "dataset_fallback",
                  "certainty": "low", "matched_address": None, "coordinates": None,
                  "state": a.state, "county": None, "place": None, "county_subdivision": None,
                  "city": a.dataset_city, "city_check": "not_checked"})
    else:
        geo = p["geographies"]
        st = (geo["States"] or [{}])[0]
        co = (geo["Counties"] or [None])[0]
        pl = (geo["Incorporated Places"] or [None])[0]
        cs = (geo["County Subdivisions"] or [None])[0]
        state = st.get("STUSAB") or a.state
        city = census_city(pl, state) if pl else None
        lon, lat = b["lonlat"].split(",")
        check = "agrees" if city == a.dataset_city else ("no_place" if city is None else "differs")
        quality = "exact" if b["match_type"] == "Exact" else "non_exact"
        s.update({"match_quality": quality, "census_result": "match", "source": "census",
                  "certainty": "high" if quality == "exact" and check == "agrees" else "medium",
                  "matched_address": b["matched_address"], "coordinates": {"lon": float(lon), "lat": float(lat)},
                  "retried_street": b.get("retried_street"),
                  "state": state,
                  "county": {"name": co["NAME"], "fips": co["GEOID"], "informational": True} if co else None,
                  "place": {"name": pl["NAME"], "geoid": pl["GEOID"]} if pl else None,
                  "county_subdivision": {"name": cs["NAME"], "geoid": cs["GEOID"]} if cs else None,
                  "city": city, "city_check": check})
    s["levels"] = [{"level": "state", "jurisdiction": s["state"]}] + (
        [{"level": "city", "jurisdiction": s["city"]}] if s["city"] else [])
    return s


def discrepancies(stacks: list[dict]) -> list[dict]:
    out = []
    for s in stacks:
        if s["city_check"] in ("differs", "no_place"):
            out.append({"address_id": s["address_id"], "kind": f"city_{s['city_check']}",
                        "dataset_city": s["dataset_city"], "census_city": s["city"],
                        "census_place": s["place"], "county_subdivision": s["county_subdivision"],
                        "matched_address": s["matched_address"], "match_quality": s["match_quality"],
                        "resolution": "geocoder wins" if s["city_check"] == "differs"
                        else "no incorporated place: state rules only"})
        if s["source"] == "census" and s["state"] != s["input"]["state"]:
            out.append({"address_id": s["address_id"], "kind": "state_differs", "dataset_state": s["input"]["state"],
                        "census_state": s["state"], "matched_address": s["matched_address"],
                        "resolution": "geocoder wins"})
        if s["source"] == "dataset_fallback":
            out.append({"address_id": s["address_id"], "kind": "no_match", "dataset_city": s["dataset_city"],
                        "census_result": s["census_result"], "input": s["input"],
                        "resolution": "dataset city (postal_city / source_dataset), certainty low"})
    return out


def resolve(*, refresh: bool = False, log=print) -> dict:
    addresses = load_addresses()
    batch, places = fetch(addresses, refresh=refresh, log=log)
    stacks = [build_stack(a, batch.get(a.address_id), places.get(a.address_id)) for a in addresses]
    data = {"source": "participant-final-no-hour16 3/data/sample_addresses.csv",
            "source_sha256": addresses_sha256(),
            "geocoder": {"service": CENSUS, "benchmark": BENCHMARK, "vintage": VINTAGE,
                         "raw": "data/geocode_raw/", "zip_omitted_for_states": sorted(NO_ZIP_STATES)},
            "stacks": {s["address_id"]: s for s in stacks},
            "discrepancies": discrepancies(stacks)}
    JURISDICTIONS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    return data


def match_summary(data: dict) -> list[tuple[str, int, Counter]]:
    by: dict[str, Counter] = {}
    for s in data["stacks"].values():
        by.setdefault(s["dataset_city"], Counter())[s["match_quality"]] += 1
    return [(c, sum(v.values()), v) for c, v in sorted(by.items(), key=lambda kv: (kv[0][-2:], kv[0]))]
