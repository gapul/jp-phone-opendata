#!/usr/bin/env python3
"""Build a phone list from NPPES, the US registry of healthcare providers.

Every clinic, hospital, pharmacy and lab that bills US health insurance, with its
practice telephone number. Public domain, published monthly by CMS.

Only organisations are taken. NPPES also enumerates individual practitioners, and
for a sole practitioner the "practice telephone" is often a personal line — the
same reasoning that keeps individuals out of the other registers here.

The dissemination file is ~1.1 GB zipped and about nine uncompressed, so the CSV
is streamed out of the archive rather than extracted.

Usage:
    python3 scripts/fetch_nppes_us.py data/world [Month_Year]
"""

from __future__ import annotations

import csv
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

BASE = "https://download.cms.gov/nppes"
CONFIDENCE = 0.97

USER_AGENT = "jp-phone-opendata (+https://github.com/gapul/jp-phone-opendata)"

# NPPES stores names in capitals, so they need casing down — but blindly title
# casing turns LLC into Llc, and these suffixes are most of what a US practice
# name ends with.
ACRONYMS = {
    "LLC", "L.L.C.", "INC", "INC.", "PLLC", "P.C.", "PC", "PA", "LP", "LLP", "DDS",
    "MD", "DO", "DPM", "OD", "DC", "PT", "OT", "RN", "LPC", "LCSW", "PHD", "USA",
    "II", "III", "IV",
}


def present(name: str) -> str:
    return " ".join(
        word if word.upper().strip(",") in ACRONYMS else word.title()
        for word in name.split()
    )


ENTITY_COLUMN = "Entity Type Code"
NAME_COLUMN = "Provider Organization Name (Legal Business Name)"
PHONE_COLUMN = "Provider Business Practice Location Address Telephone Number"
ORGANISATION = "2"


def normalize(raw: str) -> int | None:
    """US numbers to E.164 digits. NPPES is domestic, so anything else is noise."""
    digits = "".join(character for character in raw if character.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None
    # Area codes and exchanges never start with 0 or 1.
    if digits[0] in "01" or digits[3] in "01":
        return None
    return int("1" + digits)


def download(month: str, destination: Path) -> Path:
    name = f"NPPES_Data_Dissemination_{month}_V2.zip"
    archive = destination / name
    if archive.exists():
        print(f"using cached {name}")
        return archive

    destination.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(f"{BASE}/{name}", headers={"User-Agent": USER_AGENT})
    print(f"downloading {name}")
    with urllib.request.urlopen(request, timeout=600) as response, archive.open("wb") as out:
        while chunk := response.read(1 << 20):
            out.write(chunk)
    return archive


def harvest(archive: Path) -> dict[int, str]:
    with zipfile.ZipFile(archive) as bundle:
        members = [
            name for name in bundle.namelist()
            if name.startswith("npidata_pfile") and name.endswith(".csv")
            and "fileheader" not in name.lower()
        ]
        if not members:
            raise SystemExit(f"no provider file inside {archive.name}")

        found: dict[int, str] = {}
        organisations = 0
        with bundle.open(members[0]) as handle:
            # csv.reader with column indices rather than DictReader: the file has
            # 330 columns and 8.5M rows, and building a dict per row dominates
            # the runtime.
            reader = csv.reader(io.TextIOWrapper(handle, encoding="utf-8", errors="replace"))
            header = next(reader)
            entity_at = header.index(ENTITY_COLUMN)
            name_at = header.index(NAME_COLUMN)
            phone_at = header.index(PHONE_COLUMN)
            widest = max(entity_at, name_at, phone_at)

            for row in reader:
                if len(row) <= widest or row[entity_at] != ORGANISATION:
                    continue
                organisations += 1
                number = normalize(row[phone_at])
                label = row[name_at].strip()
                if number and label:
                    # A hospital shares one switchboard across many NPIs; the
                    # first name seen is as good as any.
                    found.setdefault(number, present(label))
        print(f"{organisations:,} organisations")
    return found


def main(out_root: Path, month: str) -> None:
    cache = Path("data/_cache")
    archive = download(month, cache)
    found = harvest(archive)

    out_dir = out_root / "source_key=US-NPPES"
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "data_0.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["source_key", "number", "label", "confidence"])
        for number in sorted(found):
            writer.writerow(["US-NPPES", number, found[number], CONFIDENCE])

    print(f"{len(found):,} unique numbers")


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    main(Path(sys.argv[1]), sys.argv[2] if len(sys.argv) == 3 else "August_2026")
