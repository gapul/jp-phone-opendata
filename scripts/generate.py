#!/usr/bin/env python3
"""Build the phone-number lookup dataset from Japan MIC (Soumu) open data.

Downloads the "電気通信番号指定状況" spreadsheets (mobile 070/080/090, M2M 060,
IP 050), flattens the matrix layout (row = number prefix, columns 0-9 = next
digit, cell = carrier) into a prefix -> carrier map, and emits:

  data/prefixes.json  - prefix -> carrier (inspectable source of truth)
  data/import.sql     - D1 import (DELETE + batched INSERT) for the Worker
  data/meta.json      - counts and source note

Source: https://www.soumu.go.jp/main_sosiki/joho_tsusin/top/tel_number/number_shitei.html
License of source data: MIC open data (CC BY 4.0 compatible). Attribute MIC.
"""
import json
import os
import urllib.request
from pathlib import Path

import openpyxl

# Soumu "main_content" IDs for each allocation spreadsheet (.xlsx).
SOURCES = {
    "050": "000697573",  # IP phone
    "060": "001012639",  # M2M / PHS successor
    "070": "000697563",  # mobile
    "080": "000697565",  # mobile
    "090": "000697567",  # mobile
}
BASE_URL = "https://www.soumu.go.jp/main_content/{id}.xlsx"

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = DATA / "_cache"


def download(cache: Path) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    for label, cid in SOURCES.items():
        dest = cache / f"{cid}.xlsx"
        url = BASE_URL.format(id=cid)
        req = urllib.request.Request(url, headers={"User-Agent": "jp-phone-opendata"})
        with urllib.request.urlopen(req, timeout=60) as r:
            dest.write_bytes(r.read())
        print(f"[download] {label} <- {url} ({dest.stat().st_size} bytes)")


def parse(path: Path) -> dict:
    """Flatten one matrix sheet into {prefix+digit: carrier}."""
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb.active
    out = {}
    in_body = False
    for row in ws.iter_rows(values_only=True):
        head = row[0]
        if head == "番号":          # header row; columns 1..10 are '0'..'9'
            in_body = True
            continue
        if not in_body or head is None:
            continue
        prefix = str(head).strip()
        if not prefix.isdigit():
            continue
        for d in range(10):          # column 0-9 = next single digit
            carrier = row[1 + d]
            if carrier:
                out[prefix + str(d)] = str(carrier).strip()
    return out


def write_sql(ranges: dict, path: Path) -> None:
    lines = ["DELETE FROM prefixes;"]
    items = sorted(ranges.items())
    for i in range(0, len(items), 500):   # batched multi-row INSERT
        chunk = items[i:i + 500]
        values = ",".join(
            "('{}','{}')".format(p, c.replace("'", "''")) for p, c in chunk
        )
        lines.append(f"INSERT INTO prefixes (prefix,carrier) VALUES {values};")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def lookup(number: str, ranges: dict) -> str | None:
    d = "".join(ch for ch in number if ch.isdigit())
    if d.startswith("81") and len(d) >= 11:
        d = "0" + d[2:]
    for n in (7, 6):                 # longest prefix first (050 = 7, mobile = 6)
        if d[:n] in ranges:
            return ranges[d[:n]]
    return None


def main() -> None:
    DATA.mkdir(exist_ok=True)
    if os.environ.get("SKIP_DOWNLOAD") != "1":
        download(CACHE)

    ranges = {}
    for cid in SOURCES.values():
        ranges.update(parse(CACHE / f"{cid}.xlsx"))

    lengths = sorted({len(k) for k in ranges})
    carriers = sorted(set(ranges.values()))
    print(f"[parse] {len(ranges)} prefixes, lengths={lengths}, {len(carriers)} carriers")

    (DATA / "prefixes.json").write_text(
        json.dumps(ranges, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    write_sql(ranges, DATA / "import.sql")
    (DATA / "meta.json").write_text(
        json.dumps(
            {"prefix_count": len(ranges), "carriers": carriers,
             "source": "総務省 電気通信番号指定状況",
             "source_url": "https://www.soumu.go.jp/main_sosiki/joho_tsusin/top/tel_number/number_shitei.html"},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    print("[write] data/prefixes.json, data/import.sql, data/meta.json")

    for t in ["09011234567", "08055556666", "07012345678",
              "05012345678", "+819012345678"]:
        print(f"  self-test {t:>15} -> {lookup(t, ranges)}")


if __name__ == "__main__":
    main()
