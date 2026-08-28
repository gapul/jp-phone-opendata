#!/usr/bin/env python3
"""Build phone lists from All the Places, worldwide.

All the Places scrapes brands' own store-locator pages, so the numbers are
first-party rather than platform- or crowd-sourced. Overture ingests the project
but drops its phone numbers, so this goes upstream.

Output is partitioned by country into `data/world/source_key=<CC>-AllThePlaces/`.

Usage:
    python3 scripts/fetch_alltheplaces.py data/world
"""

from __future__ import annotations

import csv
import json
import sys
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from jp_phone import normalize as normalize_jp

RUNS_INDEX = "https://data.alltheplaces.xyz/runs/latest.json"
DATA_ROOT = "https://alltheplaces-data.openaddresses.io/runs"

# No per-record score here. Official store locators are more trustworthy than any
# crowd- or platform-sourced feed, but scrapes still lag closures.
CONFIDENCE = 0.95

# The CDN rejects urllib's default User-Agent.
USER_AGENT = "jp-phone-opendata (+https://github.com/gapul/jp-phone-opendata)"


def open_url(url: str, timeout: int):
    return urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=timeout
    )


def normalize(raw: str, country: str) -> int | None:
    """Japan gets the full numbering-plan check; elsewhere, E.164 or nothing.

    Expanding another country's national notation would need that country's
    dialling rules, and guessing them invents numbers that do not exist.
    """
    if country == "JP":
        return normalize_jp(raw)
    if not raw.strip().startswith("+"):
        return None
    digits = "".join(character for character in raw if character.isdigit())
    if not 8 <= len(digits) <= 15:
        return None
    return int(digits)


def label_for(properties: dict) -> str | None:
    """Prefers a name that identifies the branch, not just the chain.

    Spiders split these two ways: some follow the OSM convention of `name` for
    the brand plus `branch` for the outlet, others put the whole thing in `name`.
    """
    name = None
    for key in ("name", "brand", "operator"):
        value = properties.get(key)
        if isinstance(value, str) and value.strip():
            name = value.strip()
            break
    if name is None:
        return None

    branch = properties.get("branch")
    if isinstance(branch, str) and branch.strip() and branch.strip() not in name:
        return f"{name} {branch.strip()}"
    return name


def fetch(run: str, spider: str) -> list[tuple[str, int, str]]:
    url = f"{DATA_ROOT}/{run}/output/{spider}.geojson"
    try:
        with open_url(url, 300) as response:
            document = json.load(response)
    except Exception:  # noqa: BLE001 - one bad spider must not stop the run
        return []

    rows = []
    for feature in document.get("features", []):
        properties = feature.get("properties", {})
        phone = properties.get("phone")
        country = properties.get("addr:country")
        if not isinstance(phone, str) or not isinstance(country, str) or len(country) != 2:
            continue
        label = label_for(properties)
        if label is None:
            continue
        # A few spiders emit several numbers in one field.
        for part in phone.replace("/", ";").split(";"):
            number = normalize(part, country.upper())
            if number:
                rows.append((country.upper(), number, label))
    return rows


def main(out_root: Path) -> None:
    with open_url(RUNS_INDEX, 60) as response:
        run = json.load(response)["run_id"]
    with open_url(f"{DATA_ROOT}/{run}/stats/_results.json", 180) as response:
        spiders = [result["spider"] for result in json.load(response)["results"]]

    print(f"run {run}: {len(spiders)} spiders", flush=True)
    by_country: dict[str, dict[int, str]] = defaultdict(dict)
    with ThreadPoolExecutor(max_workers=16) as pool:
        for index, rows in enumerate(pool.map(lambda spider: fetch(run, spider), spiders)):
            for country, number, label in rows:
                by_country[country].setdefault(number, label)
            if (index + 1) % 500 == 0:
                print(f"  {index + 1}/{len(spiders)} spiders", flush=True)

    written = 0
    for country, entries in sorted(by_country.items()):
        out_dir = out_root / f"source_key={country}-AllThePlaces"
        out_dir.mkdir(parents=True, exist_ok=True)
        with (out_dir / "data_0.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["source_key", "number", "label", "confidence"])
            for number in sorted(entries):
                writer.writerow([f"{country}-AllThePlaces", number, entries[number], CONFIDENCE])
        written += len(entries)

    print(f"{written:,} numbers across {len(by_country)} countries")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
