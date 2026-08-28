#!/usr/bin/env python3
"""Build a phone list from the MHLW long-term care provider open data.

Every licensed care provider in Japan, published by the ministry as CSV twice a
year under the open data policy. Unlike the platform-sourced feeds this is a
register rather than a scrape, and these are places that genuinely telephone
people — which matters more than raw coverage when the device can only hold so
many numbers.

Output matches what `extract_jp_places.sql` writes, so `build_calldir_db.py`
picks it up as just another source.

Usage:
    python3 scripts/fetch_mhlw_care_jp.py data/ios
"""

from __future__ import annotations

import csv
import io
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from jp_phone import normalize

INDEX_URL = "https://www.mhlw.go.jp/stf/kaigo-kouhyou_opendata.html"
SITE_ROOT = "https://www.mhlw.go.jp"

# An official register, but republished only twice a year, so some entries lag
# reality. Above the scraped and platform-sourced lists, below a live feed.
CONFIDENCE = 0.98

# The ministry stamps each file with the time it was generated, so the links have
# to be read off the index page rather than constructed.
CSV_LINK = re.compile(r'href="(/content/\d+/jigyosho_[^"]+\.csv)"')

NAME_COLUMN = "事業所名"
PHONE_COLUMN = "電話番号"

USER_AGENT = "jp-phone-opendata (+https://github.com/gapul/jp-phone-opendata)"


def open_url(url: str, timeout: int):
    return urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=timeout
    )


def fetch(path: str) -> list[tuple[int, str]]:
    try:
        with open_url(SITE_ROOT + path, 300) as response:
            body = response.read()
    except Exception as error:  # noqa: BLE001 - one bad file must not stop the run
        print(f"  {path}: {error}", file=sys.stderr)
        return []

    text = body.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or PHONE_COLUMN not in reader.fieldnames:
        print(f"  {path}: unexpected columns", file=sys.stderr)
        return []

    rows = []
    for row in reader:
        number = normalize(row.get(PHONE_COLUMN) or "")
        label = (row.get(NAME_COLUMN) or "").strip()
        if number and label:
            rows.append((number, label))
    return rows


def main(out_root: Path) -> None:
    with open_url(INDEX_URL, 60) as response:
        index = response.read().decode("utf-8", errors="replace")
    paths = sorted(set(CSV_LINK.findall(index)))
    print(f"{len(paths)} service-type files")

    with ThreadPoolExecutor(max_workers=6) as pool:
        harvested = list(pool.map(fetch, paths))

    # A facility offering several service types appears once per type; the first
    # occurrence keeps the name.
    merged: dict[int, str] = {}
    for rows in harvested:
        for number, label in rows:
            merged.setdefault(number, label)

    out_dir = out_root / "source=MHLWCare"
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "data_0.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["source", "number", "label", "confidence"])
        for number in sorted(merged):
            writer.writerow(["MHLWCare", number, merged[number], CONFIDENCE])

    print(f"{len(merged):,} unique numbers")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
