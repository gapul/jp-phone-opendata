#!/usr/bin/env python3
"""Harvest the health bureaus that publish their clinic lists as PDF only.

Four bureaus never produce a spreadsheet — including the ones covering Tokyo,
Nagoya, Osaka and Fukuoka — so `fetch_kouseikyoku_iryo_jp.py` cannot see them.
The PDFs are renderings of the same fixed-width report, which `pdftotext -layout`
turns back into something parseable.

Finding the files is most of the work: the bureaus share no URL scheme, and some
label the links only "医科（PDF）", so this crawls each bureau and keeps PDFs that
either say コード内容別 or are named like the designation lists.

Requires pdftotext (poppler):
    nix shell nixpkgs#poppler-utils --command \\
        python3 scripts/fetch_kouseikyoku_pdf_jp.py data/ios
"""

from __future__ import annotations

import csv
import re
import subprocess
import sys
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin

from jp_phone import normalize

BUREAUS = ["kantoshinetsu", "tokaihokuriku", "kinki", "kyushu"]

# Same report as the spreadsheet bureaus publish, so the same trust level.
CONFIDENCE = 0.97

USER_AGENT = "jp-phone-opendata (+https://github.com/gapul/jp-phone-opendata)"

# Kanto-Shinetsu labels its links just "医科（PDF）", so the filename is the only
# signal; the other bureaus spell the report name out in the anchor text.
DESIGNATION_FILE = re.compile(r"shitei_[a-z]+_[a-z]+_r\d+\.pdf$", re.IGNORECASE)
FOLLOWABLE = ("hoken_kikan", "gyomu", "shitei", "chousa", "tyousa", "ichiran",
              "itiran", "code", "newpage", "bu_ka")

PHONE = re.compile(r"0\d{1,4}[-‐－]\d{1,4}[-‐－]\d{3,4}")
LEADING_INDEX = re.compile(r"^\s*\d+\s+")
# The institution code separator varies by bureau: "01,1002,3", "01-2152-5",
# "20・1710・5" and "533,053.5" all occur, sometimes with a parenthesised second
# code. Leaving one unstripped also misaligns the wrapped-name columns below, so
# a missed separator costs more than a stray prefix.
LEADING_CODE = re.compile(r"^[\d,.．()（）\-‐－・･]+\s+")


def open_url(url: str, timeout: int):
    return urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=timeout
    )


def read(url: str) -> str:
    try:
        with open_url(url, 45) as response:
            return response.read().decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - dead links are normal on these sites
        return ""


def discover(bureau: str) -> list[str]:
    root = f"https://kouseikyoku.mhlw.go.jp/{bureau}/"
    seen = {root}
    frontier = [root]
    found: set[str] = set()

    for _ in range(4):
        following = []
        for page in frontier:
            body = read(page)
            if not body:
                continue
            for href, anchor in re.findall(r'href="([^"]+)"[^>]*>(.*?)</a>', body, re.S):
                # The sites mix http and https internally; normalise or the
                # same-origin check throws away most of the site.
                target = urljoin(page, href).replace("http://", "https://").split("#")[0]
                if target.lower().endswith(".pdf"):
                    text = re.sub(r"<[^>]+>", "", anchor)
                    if "コード内容別" in text or DESIGNATION_FILE.search(target):
                        found.add(target)
                    continue
                if target.lower().endswith((".xlsx", ".xls", ".zip", ".csv")):
                    continue
                if not target.startswith(root) or target in seen:
                    continue
                if any(key in target for key in FOLLOWABLE):
                    seen.add(target)
                    following.append(target)
        frontier = following[:120]
    return sorted(found)


def harvest(text: str) -> list[tuple[int, str]]:
    """Pulls (number, name) from the report's first line per record.

    Layout is: 項番, institution code, name, 〒address, phone. Only the first line
    of a record carries a phone number, so that is what marks a record; the name
    is whatever sits between the code and the postal address.
    """
    found = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = PHONE.search(line)
        if not match:
            continue
        number = normalize(match.group())
        if number is None:
            continue

        # The name column is whatever sits between the code and the postal
        # address, so measure it on this line and reuse those columns below.
        end = line.index("〒") if "〒" in line[: match.start()] else match.start()
        head = line[:end]
        stripped = LEADING_CODE.sub("", LEADING_INDEX.sub("", head))
        start = len(head) - len(stripped)
        name = stripped.strip()

        # The column is narrow, so long names wrap onto the record's remaining
        # lines. Take the same columns from those until the next record starts.
        for continuation in lines[index + 1:]:
            if PHONE.search(continuation):
                break
            fragment = continuation[start:end].strip()
            if not fragment:
                continue
            # Staffing counts and dates bleed into neighbouring columns; a real
            # continuation never looks like a bare number.
            if re.fullmatch(r"[\d\s,.()（）:：]+", fragment):
                continue
            name += fragment

        if name:
            found.append((number, name))
    return found


def fetch(url: str) -> list[tuple[int, str]]:
    try:
        with open_url(url, 300) as response:
            blob = response.read()
    except Exception as error:  # noqa: BLE001
        print(f"  {url}: {error}", file=sys.stderr)
        return []

    with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
        handle.write(blob)
        handle.flush()
        try:
            text = subprocess.run(
                ["pdftotext", "-layout", handle.name, "-"],
                capture_output=True, check=True, timeout=600,
            ).stdout.decode("utf-8", errors="replace")
        except FileNotFoundError:
            sys.exit("pdftotext not found: run under `nix shell nixpkgs#poppler-utils`")
        except Exception as error:  # noqa: BLE001
            print(f"  {url}: {error}", file=sys.stderr)
            return []
    return harvest(text)


def main(out_root: Path) -> None:
    urls: list[str] = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for bureau, found in zip(BUREAUS, pool.map(discover, BUREAUS)):
            print(f"{bureau}: {len(found)} PDFs")
            urls.extend(found)

    with ThreadPoolExecutor(max_workers=6) as pool:
        harvested = list(pool.map(fetch, urls))

    merged: dict[int, str] = {}
    for rows in harvested:
        for number, label in rows:
            merged.setdefault(number, label)

    out_dir = out_root / "source=KouseikyokuIryo"
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "data_1.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["source", "number", "label", "confidence"])
        for number in sorted(merged):
            writer.writerow(["KouseikyokuIryo", number, merged[number], CONFIDENCE])

    print(f"{len(merged):,} unique numbers from {len(urls)} PDFs")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
