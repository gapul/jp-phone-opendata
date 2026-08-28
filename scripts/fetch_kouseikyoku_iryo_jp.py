#!/usr/bin/env python3
"""Build a phone list from the regional health bureaus' clinic and pharmacy lists.

Every clinic, dental practice and pharmacy contracted to the national health
insurance scheme, published by each 地方厚生局 as the "コード内容別医療機関一覧表".
These are places that telephone patients, so they earn their space on a device
that can only hold so many numbers.

Coverage is partial and that is not a bug in this script: the bureaus publish in
whatever format they like. Hokkaido and Tohoku offer Excel, Chugoku-Shikoku and
Shikoku offer Excel inside ZIPs, and the rest publish only PDF renderings of the
same report — Kanto-Shinetsu, Tokai-Hokuriku, Kinki and Kyushu are therefore
missing, which unfortunately includes Tokyo, Nagoya, Osaka and Fukuoka. Reading
those means parsing a paginated PDF report, which is a different project.

Output matches what `extract_jp_places.sql` writes, so `build_calldir_db.py`
picks it up as just another source.

Usage:
    python3 scripts/fetch_kouseikyoku_iryo_jp.py data/ios
"""

from __future__ import annotations

import csv
import io
import re
import sys
import urllib.request
import xml.etree.ElementTree as ElementTree
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin

from jp_phone import normalize

# Bureaus that publish a machine-readable version. Discovered by hand because the
# bureaus do not share a URL scheme and none of them link the file predictably.
BUREAU_PAGES = {
    "hokkaido": "https://kouseikyoku.mhlw.go.jp/hokkaido/gyomu/gyomu/hoken_kikan/code_ichiran.html",
    "tohoku": "https://kouseikyoku.mhlw.go.jp/tohoku/gyomu/gyomu/hoken_kikan/itiran.html",
    "chugokushikoku": "https://kouseikyoku.mhlw.go.jp/chugokushikoku/chousaka/iryoukikanshitei.html",
    "shikoku": "https://kouseikyoku.mhlw.go.jp/shikoku/gyomu/gyomu/hoken_kikan/shitei/index.html",
}

# A register, but each bureau regenerates it on its own schedule, so entries lag.
CONFIDENCE = 0.97

USER_AGENT = "jp-phone-opendata (+https://github.com/gapul/jp-phone-opendata)"

DOCUMENT_LINK = re.compile(r'href="([^"]+\.(?:xlsx|xls|zip))"', re.IGNORECASE)
PHONE_CELL = re.compile(r"^0\d{1,4}[-‐－]\d{1,4}[-‐－]\d{3,4}$")
# The sequence number and the institution code sit before the name and must not
# be mistaken for it. The code is comma-grouped digits, but the group widths vary
# by bureau ("01,1021,0" and "021,142,4" both occur), so match the shape only.
CODE_CELL = re.compile(r"^[\d,]+$")


def open_url(url: str, timeout: int):
    return urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=timeout
    )


def column_index(reference: str) -> int:
    """'C7' -> 2. Cells carry their address rather than their position."""
    index = 0
    for character in reference:
        if not character.isalpha():
            break
        index = index * 26 + (ord(character.upper()) - ord("A") + 1)
    return index - 1


def read_xlsx(blob: bytes) -> list[list[str]]:
    """Minimal xlsx reader: enough to walk a generated report, no dependencies."""
    rows: list[list[str]] = []
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root:
                shared.append("".join(node.text or "" for node in item.iter()
                                      if node.tag.endswith("}t")))

        for name in sorted(n for n in archive.namelist()
                           if n.startswith("xl/worksheets/") and n.endswith(".xml")):
            root = ElementTree.fromstring(archive.read(name))
            for row in root.iter():
                if not row.tag.endswith("}row"):
                    continue
                cells: list[str] = []
                for cell in row:
                    position = column_index(cell.get("r", ""))
                    value = ""
                    if cell.get("t") == "s":
                        for node in cell:
                            if node.tag.endswith("}v") and node.text is not None:
                                index = int(node.text)
                                value = shared[index] if index < len(shared) else ""
                    else:
                        value = "".join(node.text or "" for node in cell.iter()
                                        if node.tag.endswith("}t") or node.tag.endswith("}v"))
                    while len(cells) <= position:
                        cells.append("")
                    cells[position] = value.strip()
                if any(cells):
                    rows.append(cells)
    return rows


def harvest(rows: list[list[str]]) -> list[tuple[int, str]]:
    """Pulls (number, name) out of the report's three-row records.

    Only the first row of each record carries a phone number, so finding the
    phone is what identifies a record. The name is then the widest text cell
    before it that is neither the sequence number, the institution code, nor the
    postal address.
    """
    found = []
    for cells in rows:
        phone_at = next((i for i, cell in enumerate(cells) if PHONE_CELL.match(cell)), None)
        if phone_at is None:
            continue
        number = normalize(cells[phone_at])
        if number is None:
            continue

        candidates = [
            cell for cell in cells[:phone_at]
            if cell and not cell.startswith("〒") and not CODE_CELL.match(cell)
        ]
        if not candidates:
            continue
        found.append((number, max(candidates, key=len)))
    return found


def documents(page_url: str) -> list[str]:
    with open_url(page_url, 60) as response:
        body = response.read().decode("utf-8", errors="replace")
    return sorted({urljoin(page_url, href) for href in DOCUMENT_LINK.findall(body)})


def fetch(url: str) -> list[tuple[int, str]]:
    try:
        with open_url(url, 300) as response:
            blob = response.read()
    except Exception as error:  # noqa: BLE001 - one bad file must not stop the run
        print(f"  {url}: {error}", file=sys.stderr)
        return []

    try:
        if url.lower().endswith(".zip"):
            found = []
            with zipfile.ZipFile(io.BytesIO(blob)) as archive:
                for name in archive.namelist():
                    if name.lower().endswith((".xlsx", ".xls")):
                        found.extend(harvest(read_xlsx(archive.read(name))))
            return found
        return harvest(read_xlsx(blob))
    except Exception as error:  # noqa: BLE001 - formats vary by bureau
        print(f"  {url}: {error}", file=sys.stderr)
        return []


def main(out_root: Path) -> None:
    urls: list[str] = []
    for bureau, page in BUREAU_PAGES.items():
        try:
            found = documents(page)
        except Exception as error:  # noqa: BLE001
            print(f"{bureau}: {error}", file=sys.stderr)
            continue
        print(f"{bureau}: {len(found)} documents")
        urls.extend(found)

    with ThreadPoolExecutor(max_workers=6) as pool:
        harvested = list(pool.map(fetch, urls))

    # A practice listed under several categories keeps its first name.
    merged: dict[int, str] = {}
    for rows in harvested:
        for number, label in rows:
            merged.setdefault(number, label)

    out_dir = out_root / "source=KouseikyokuIryo"
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "data_0.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["source", "number", "label", "confidence"])
        for number in sorted(merged):
            writer.writerow(["KouseikyokuIryo", number, merged[number], CONFIDENCE])

    print(f"{len(merged):,} unique numbers from {len(BUREAU_PAGES)} of 8 bureaus")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
