#!/usr/bin/env python3
"""Build a phone list from municipal facility open data published via BODIK.

Town halls, community centres, libraries, childcare centres and sports grounds —
the numbers that ring when a local authority calls. Municipalities publish these
themselves rather than through any national catalogue: data.e-gov.go.jp (formerly
data.go.jp) indexes only central government, so it is no help here.

BODIK runs a shared CKAN for several hundred municipalities, which is the closest
thing to an aggregator that exists. That is also the limitation: this covers the
municipalities that use BODIK, not all ~1,700.

Most files follow the national 推奨データセット template, but plenty do not, so
columns are matched by name and anything without a phone column is skipped.

Output matches what `extract_jp_places.sql` writes, so `build_calldir_db.py`
picks it up as just another source.

Usage:
    python3 scripts/fetch_municipal_facilities_jp.py data/ios
"""

from __future__ import annotations

import csv
import io
import json
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from jp_phone import normalize

CKAN = "https://data.bodik.jp/api/3/action"
SEARCH_TERM = "施設"
PAGE_SIZE = 100

# Official municipal registers, but published on each authority's own schedule
# and in each authority's own shape, so a notch below the national ones.
CONFIDENCE = 0.96

USER_AGENT = "jp-phone-opendata (+https://github.com/gapul/jp-phone-opendata)"

# Header spellings seen in the wild. The 推奨データセット template uses 名称 and
# 電話番号, but plenty of authorities roll their own.
NAME_HEADERS = ("名称", "施設名", "施設名称", "名前", "館名")
PHONE_HEADERS = ("電話番号", "電話", "TEL", "Tel", "ｔｅｌ", "連絡先")


def open_url(url: str, timeout: int):
    return urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=timeout
    )


def search(start: int) -> dict:
    query = urllib.parse.urlencode(
        {"q": SEARCH_TERM, "rows": PAGE_SIZE, "start": start, "fq": "res_format:CSV"}
    )
    with open_url(f"{CKAN}/package_search?{query}", 90) as response:
        return json.load(response)["result"]


def pick(headers: list[str], candidates: tuple[str, ...]) -> int | None:
    """Exact match first, then substring — '電話番号（代表）' should still count."""
    for wanted in candidates:
        for index, header in enumerate(headers):
            if header.strip() == wanted:
                return index
    for wanted in candidates:
        for index, header in enumerate(headers):
            if wanted in header:
                return index
    return None


def decode(raw: bytes) -> str | None:
    for encoding in ("utf-8-sig", "cp932", "utf-8"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def fetch(url: str) -> list[tuple[int, str]]:
    try:
        with open_url(url, 25) as response:
            raw = response.read(20_000_000)
    except Exception:  # noqa: BLE001 - dead links are common in municipal catalogues
        return []  # a slow or missing file is not worth waiting on: most yield nothing

    text = decode(raw)
    if text is None:
        return []

    reader = csv.reader(io.StringIO(text))
    headers = next(reader, None)
    if not headers:
        return []

    name_at = pick(headers, NAME_HEADERS)
    phone_at = pick(headers, PHONE_HEADERS)
    if name_at is None or phone_at is None:
        return []

    found = []
    for row in reader:
        if len(row) <= max(name_at, phone_at):
            continue
        number = normalize(row[phone_at])
        label = row[name_at].strip()
        if number and label:
            found.append((number, label))
    return found


def main(out_root: Path) -> None:
    resources: list[str] = []
    start = 0
    while True:
        result = search(start)
        for package in result["results"]:
            for resource in package.get("resources", []):
                if (resource.get("format") or "").upper() == "CSV" and resource.get("url"):
                    resources.append(resource["url"])
        start += PAGE_SIZE
        if start >= result["count"]:
            break
    print(f"{len(resources)} CSV resources")

    # Most of these hosts are slow and many links are dead, so lean on width
    # and a short timeout rather than patience.
    with ThreadPoolExecutor(max_workers=16) as pool:
        harvested = list(pool.map(fetch, resources))

    merged: dict[int, str] = {}
    contributing = 0
    for rows in harvested:
        if rows:
            contributing += 1
        for number, label in rows:
            merged.setdefault(number, label)

    out_dir = out_root / "source=Municipal"
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "data_0.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["source", "number", "label", "confidence"])
        for number in sorted(merged):
            writer.writerow(["Municipal", number, merged[number], CONFIDENCE])

    print(f"{len(merged):,} unique numbers from {contributing} usable files")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
