#!/usr/bin/env python3
"""Record a removal request, so the number stops being published.

The suppression list is the one piece of data here that is maintained by hand
rather than harvested, and the only one kept in git — it is the record of what
was removed and on what basis. Entries are written through this rather than by
editing the CSV because the number has to be stored as E.164 digits, and a
mistyped one silently suppresses nothing.

Whether the requester's ownership was confirmed is recorded but does not change
what happens: both are honoured. It matters afterwards — if a removal is later
disputed, an unverified one can reasonably be reversed and a verified one cannot.

Usage:
    python3 scripts/suppress.py 03-1234-5678 --verified   [--note "..."]
    python3 scripts/suppress.py +4930123456  --unverified
"""

from __future__ import annotations

import argparse
import csv
import datetime
from pathlib import Path

from jp_phone import normalize as normalize_jp

LIST = Path("data/suppressions/source=Suppressions/data_0.csv")
FIELDS = ["source", "number", "label", "confidence", "verified", "method", "requested", "note"]

# How ownership was shown, when it was. Kept alongside the yes/no because
# "verified" on its own is not something anyone can re-examine later.
METHODS = ("website", "otp", "manual", "none")


def parse(raw: str) -> int | None:
    """Accepts what a person would paste: national Japanese, or E.164."""
    japanese = normalize_jp(raw)
    if japanese is not None:
        return japanese
    digits = "".join(character for character in raw if character.isdigit())
    return int(digits) if 8 <= len(digits) <= 15 else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("number")
    ownership = parser.add_mutually_exclusive_group(required=True)
    ownership.add_argument("--verified", action="store_true",
                           help="the requester showed the number is theirs")
    ownership.add_argument("--unverified", action="store_true",
                           help="honoured on request alone")
    parser.add_argument("--method", choices=METHODS, default=None,
                        help="how ownership was shown; defaults to website when "
                             "verified, none when not")
    parser.add_argument("--note", default="")
    parser.add_argument("--date", default=None,
                        help="ISO date; defaults to today (UTC)")
    arguments = parser.parse_args()

    number = parse(arguments.number)
    if number is None:
        parser.error(f"{arguments.number!r} is not a usable phone number")

    rows = []
    if LIST.exists():
        with LIST.open(newline="", encoding="utf-8") as handle:
            rows = [row for row in csv.DictReader(handle) if int(row["number"]) != number]

    requested = arguments.date or datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    rows.append({
        "source": "Suppressions",
        "number": str(number),
        # Empty is what makes it a suppression rather than a name.
        "label": "",
        "confidence": "1.0",
        "verified": "yes" if arguments.verified else "no",
        "method": arguments.method or ("website" if arguments.verified else "none"),
        "requested": requested,
        "note": arguments.note,
    })
    rows.sort(key=lambda row: int(row["number"]))

    LIST.parent.mkdir(parents=True, exist_ok=True)
    with LIST.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    verified = sum(1 for row in rows if row["verified"] == "yes")
    print(f"+{number} suppressed ({'verified' if arguments.verified else 'unverified'})")
    print(f"{len(rows)} total, {verified} verified")


if __name__ == "__main__":
    main()
