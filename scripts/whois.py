#!/usr/bin/env python3
"""Say which published lists carry a number, and who published it upstream.

This exists to answer removal requests. Two things have to happen when one
arrives: the number goes into the suppression list so it disappears from every
subscriber at the next release, and the person is told which upstream source
carries it, since that is the only fix that stops it reaching anyone else.

Answering the second part means knowing where it came from, which is what this
prints.

Usage:
    python3 scripts/whois.py dist 03-1234-5678
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import list_format
from jp_phone import normalize as normalize_jp

# Where to send someone whose number appears in a given source. Overture is a
# conduit for several upstreams, so it gets pointed at its own removal process
# rather than at whichever member contributed the row.
UPSTREAM = {
    "meta": "Overture Maps — https://overturemaps.org/feedback/ (contributed by Meta)",
    "Foursquare": "Overture Maps — https://overturemaps.org/feedback/ (contributed by Foursquare)",
    "Microsoft": "Overture Maps — https://overturemaps.org/feedback/ (contributed by Microsoft)",
    "PinMeTo": "Overture Maps — https://overturemaps.org/feedback/",
    "DAC": "Overture Maps — https://overturemaps.org/feedback/",
    "BrightQuery": "Overture Maps — https://overturemaps.org/feedback/",
    "AllThePlaces": "All the Places — the brand's own store locator is the origin; "
                    "https://github.com/alltheplaces/alltheplaces/issues",
    "NPPES": "CMS NPPES — the provider updates it at https://nppes.cms.hhs.gov/",
    "MHLWCare": "厚生労働省 介護サービス情報公表システム（事業所が指定権者へ届け出た番号）",
    "KouseikyokuIryo": "地方厚生局（保険医療機関の届出情報）",
    "Municipal": "掲載自治体のオープンデータ窓口",
}


def parse(raw: str) -> int | None:
    """Accepts what a person would paste: national Japanese, or E.164."""
    japanese = normalize_jp(raw)
    if japanese is not None:
        return japanese
    digits = "".join(character for character in raw if character.isdigit())
    return int(digits) if 8 <= len(digits) <= 15 else None


SUPPRESSIONS = Path("data/suppressions/source=Suppressions/data_0.csv")


def suppression(number: int) -> dict | None:
    if not SUPPRESSIONS.exists():
        return None
    with SUPPRESSIONS.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if int(row["number"]) == number:
                return row
    return None


def main(dist: Path, raw: str) -> None:
    number = parse(raw)
    if number is None:
        sys.exit(f"{raw!r} is not a usable phone number")
    print(f"+{number}")

    catalog = json.loads((dist / "catalog.json").read_text(encoding="utf-8"))
    hits = 0
    for entry in catalog:
        rows = dict(list_format.read_list(dist / entry["filename"]))
        label = rows.get(number)
        if label is None:
            continue
        hits += 1
        shown = label if label else "(already suppressed)"
        print(f"  {entry['country']} {entry['title']}: {shown}")
        upstream = UPSTREAM.get(entry["source"])
        if upstream:
            print(f"      upstream: {upstream}")

    record = suppression(number)
    if record:
        basis = (f"verified by {record.get('method', 'unknown')}"
                 if record["verified"] == "yes" else "unverified")
        note = f" — {record['note']}" if record.get("note") else ""
        print(f"\nAlready suppressed on {record['requested']} ({basis}){note}")
    elif not hits:
        print("  not in any published list")
    else:
        print(f"\nTo remove it:  python3 scripts/suppress.py {raw} --verified|--unverified")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(Path(sys.argv[1]), sys.argv[2])
