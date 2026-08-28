#!/usr/bin/env python3
"""Pack the extracted per-source CSVs into the binaries the extension reads.

Each upstream source becomes its own list, so the app can offer them the way an
ad blocker offers filter lists. Alongside the binaries this writes `catalog.json`,
the index the app fetches to show what is available for download.

The extension runs in a memory-constrained process, so it cannot afford to parse
CSV or build an object graph. It memory-maps these files and reads them in place.

Layout (little-endian, matching every iOS device):

    magic    "JPCD"      4 bytes
    version  UInt32      1
    count    UInt32      number of entries
    _pad     UInt32      keeps `numbers` 8-byte aligned
    numbers  Int64  x count        ascending, unique
    offsets  UInt32 x (count + 1)  byte ranges into `labels`
    labels   UTF-8 bytes           concatenated, not terminated

Usage:
    python3 scripts/build_calldir_db.py data/ios data/world dist
"""

from __future__ import annotations

import csv
import datetime
import json
import os
import shutil
import struct
import sys
from pathlib import Path

import list_format

MAGIC = b"JPCD"
VERSION = 1

# Must match DirectoryCatalog.suggestionsURL's directory in the app. A fixed tag
# rather than "latest": the apps are released separately and would otherwise take
# that name and leave subscribers with no catalogue.
DOWNLOAD_BASE_URL = "https://github.com/gapul/jp-phone-opendata/releases/download/lists/"

# CallKit truncates long labels in the call UI anyway, and labels dominate the
# file size, so cap them. Generous enough to keep real business names intact.
MAX_LABEL_CHARS = 48

# Overture reaches 252 countries, and the tail of that is a handful of numbers
# per source. Below this a list is not worth a line in the catalogue.
MIN_ENTRIES = 200

# A list of numbers to blank out rather than name. It exists so a removal request
# can be honoured without waiting for the upstream source to drop the entry, and
# it sorts above everything so it can actually override them.
SUPPRESSIONS = "Suppressions"

# Redistributing these lists carries attribution duties, and the set of sources
# changes as fetchers are added, so the notice is generated from what actually
# shipped rather than kept by hand.
ATTRIBUTION = {
    "meta": ("Overture Maps Foundation — Places", "CDLA Permissive 2.0",
             "https://overturemaps.org/"),
    "Foursquare": ("Overture Maps Foundation — Places", "CDLA Permissive 2.0",
                   "https://overturemaps.org/"),
    "Microsoft": ("Overture Maps Foundation — Places", "CDLA Permissive 2.0",
                  "https://overturemaps.org/"),
    "PinMeTo": ("Overture Maps Foundation — Places", "CDLA Permissive 2.0",
                "https://overturemaps.org/"),
    "DAC": ("Overture Maps Foundation — Places", "CDLA Permissive 2.0",
            "https://overturemaps.org/"),
    "AllThePlaces": ("All the Places", "CC0 1.0", "https://alltheplaces.xyz/"),
    "NPPES": ("NPPES — National Plan and Provider Enumeration System (CMS)",
              "US public domain", "https://download.cms.gov/nppes/NPI_Files.html"),
    "MHLWCare": ("厚生労働省 介護サービス情報公表システム オープンデータ", "政府標準利用規約",
                 "https://www.mhlw.go.jp/stf/kaigo-kouhyou_opendata.html"),
    "KouseikyokuIryo": ("地方厚生局 コード内容別医療機関一覧表", "政府標準利用規約",
                        "https://kouseikyoku.mhlw.go.jp/"),
    "Municipal": ("各地方公共団体のオープンデータ (BODIK ODCS 経由)", "各団体の定めるところによる",
                  "https://data.bodik.jp/"),
}

TITLES = {
    "MHLWCare": "Long-term care providers (MHLW)",
    "Municipal": "Municipal facilities (BODIK)",
    # Named for what it actually covers: half the bureaus publish PDF only.
    "KouseikyokuIryo": "Clinics & pharmacies (6 of 8 bureaus)",
    "meta": "Meta (Facebook Pages)",
    "Foursquare": "Foursquare",
    "Microsoft": "Microsoft",
    "AllThePlaces": "All the Places",
    "NPPES": "Healthcare providers (NPPES)",
    "Suppressions": "Removals",
    "PinMeTo": "PinMeTo",
    "DAC": "DAC",
}


def write_attribution(dist_dir: Path, descriptors: list[dict]) -> None:
    lines = [
        "# Sources",
        "",
        "These lists are derived from open data. Redistribution keeps the "
        "attribution each publisher asks for.",
        "",
    ]
    seen = set()
    for item in descriptors:
        credit = ATTRIBUTION.get(item["source"])
        if credit is None or credit in seen:
            continue
        seen.add(credit)
        name, licence, url = credit
        lines.append(f"- {name} — {licence} — {url}")
    (dist_dir / "ATTRIBUTION.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def country_and_source(directory: Path) -> tuple[str, str]:
    """Splits a partition directory into the country it covers and its source.

    Two conventions live side by side. The worldwide extraction writes
    `source_key=DE-meta`, while the Japanese harvesters predate the split and
    write plain `source=MHLWCare`; those are all Japan by construction.
    """
    key = directory.name.split("=", 1)[1]
    head, _, tail = key.partition("-")
    if tail and len(head) == 2 and head.isupper():
        return head, tail
    return "JP", key


def harvested_at(source_dir: Path) -> str:
    """When the source CSVs were last written, as ISO-8601 UTC."""
    newest = max(path.stat().st_mtime for path in source_dir.glob("*.csv"))
    return (datetime.datetime.fromtimestamp(newest, datetime.timezone.utc)
            .replace(microsecond=0).isoformat())


def read_source(csv_path: Path, allow_blank: bool = False) -> tuple[list[tuple[int, str]], float]:
    rows: list[tuple[int, str]] = []
    total_confidence = 0.0
    with csv_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            label = row["label"].strip()[:MAX_LABEL_CHARS]
            # A blank label means "show nothing for this number", which only the
            # suppression list is allowed to say. Anywhere else it is a harvester
            # bug, and silently hiding numbers is the worst way to find out.
            if not label and not allow_blank:
                continue
            rows.append((int(row["number"]), label))
            total_confidence += float(row["confidence"])
    mean = total_confidence / len(rows) if rows else 0.0
    return rows, mean


def build(input_dirs: list[Path], dist_dir: Path) -> None:
    """Pack every source and write the catalogue the app offers as suggestions.

    Nothing ships inside the app: `dist_dir` is uploaded somewhere, and the phone
    downloads only the lists its owner picks. Refreshing the data is therefore a
    download, not a reinstall.
    """
    out_dir = dist_dir
    old_catalog = {}
    previous_catalog = dist_dir / "catalog.json"
    if previous_catalog.exists():
        old_catalog = {
            entry["id"]: entry
            for entry in json.loads(previous_catalog.read_text(encoding="utf-8"))
        }
    if previous_catalog.exists():
        # Kept for `check_release.py`, which compares the two before publishing.
        (dist_dir / "catalog.previous.json").write_text(
            previous_catalog.read_text(encoding="utf-8"), encoding="utf-8"
        )

    descriptors = []
    directories = sorted(
        directory
        for input_dir in input_dirs
        for pattern in ("source=*", "source_key=*")
        for directory in input_dir.glob(pattern)
    )
    for source_dir in directories:
        country, source = country_and_source(source_dir)
        rows: list[tuple[int, str]] = []
        confidences = []
        for csv_path in sorted(source_dir.glob("*.csv")):
            part, mean = read_source(csv_path, allow_blank=source == SUPPRESSIONS)
            rows.extend(part)
            confidences.append(mean)
        if not rows:
            continue
        # A suppression list is worth publishing at any size; nothing else is.
        if len(rows) < MIN_ENTRIES and source != SUPPRESSIONS:
            continue
        rows.sort(key=lambda row: row[0])

        filename = f"places_{country}-{source}.bin"
        out_path = out_dir / filename
        stamp = harvested_at(source_dir)

        # Keep the copy this build replaces, so the difference can be published
        # instead of making every phone re-download a mostly unchanged table.
        previous = None
        published = old_catalog.get(f"{country.lower()}.{source}")
        if out_path.exists() and published and published.get("updatedAt") != stamp:
            try:
                previous = list_format.read_list(out_path)
            except ValueError:
                previous = None
        count = list_format.write_list(rows, out_path)
        confidence = sum(confidences) / len(confidences)

        patch = None
        if previous is not None:
            current = list_format.read_list(out_path)
            patch_name = f"places_{country}-{source}.patch"
            removals, upserts = list_format.write_patch(previous, current, out_dir / patch_name)
            # The publisher is the only place this can be checked cheaply, and a
            # wrong patch would corrupt every subscriber's copy silently.
            assert list_format.apply_patch(previous, out_dir / patch_name) == current, patch_name
            # Whether it is worth fetching is the subscriber's call: it knows
            # both sizes, so there is no threshold to guess at here.
            patch = {
                "from": published["updatedAt"],
                "filename": patch_name,
                "url": DOWNLOAD_BASE_URL + patch_name,
                "byteCount": (out_dir / patch_name).stat().st_size,
                "removals": removals,
                "upserts": upserts,
            }
        descriptors.append(
            {
                # Not all sources are Overture any more, so keep the id neutral.
                "id": f"{country.lower()}.{source}",
                "title": TITLES.get(source, source),
                # The app offers the lists for the phone's own region first;
                # a flat worldwide catalogue would be unusable.
                "country": country,
                # Carried so the attribution notice can name the publisher.
                "source": source,
                "filename": filename,
                "entryCount": count,
                "confidence": round(confidence, 4),
                "byteCount": (out_dir / filename).stat().st_size,
                "url": DOWNLOAD_BASE_URL + filename,
                # Stamped from the harvest, not the build, so rebuilding
                # unchanged data does not make every phone re-download it.
                "updatedAt": stamp,
                "patch": patch,
            }
        )

    # Highest-confidence sources first: on a number carried by several lists, the
    # earliest enabled one supplies the label. Suppressions go above even a
    # perfect-confidence source, since removing a name is the whole point.
    descriptors.sort(key=lambda item: (item["source"] != SUPPRESSIONS, -item["confidence"]))

    write_attribution(dist_dir, descriptors)

    # The index the app fetches to populate its suggestions.
    (dist_dir / "catalog.json").write_text(
        json.dumps(descriptors, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    total = sum(item["entryCount"] for item in descriptors)
    for item in descriptors:
        if item["entryCount"] < 1000 and len(descriptors) > 20:
            continue  # too many tiny lists to be worth printing one by one
        print(f"{item['entryCount']:>9,}  conf {item['confidence']:.2f}  "
              f"{item['byteCount'] / 1024 / 1024:>6.1f} MB  "
              f"{item['country']}  {item['title']}")
    countries = len({item["country"] for item in descriptors})
    print(f"{total:>9,}  total across {len(descriptors)} lists in {countries} countries")


def demo() -> None:
    """Self-check: pack a tiny source tree, then rebuild it and check the patch."""
    import tempfile

    global MIN_ENTRIES
    MIN_ENTRIES = 1

    header = "source,number,label,confidence\n"
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source_dir = root / "in" / "source=Demo"
        source_dir.mkdir(parents=True)
        (source_dir / "data_0.csv").write_text(
            header
            + "Demo,81312345678,渋谷クリニック,0.9\n"
            + "Demo,81312345678,重複なので捨てる,0.5\n"
            + "Demo,81398765432,Test Cafe,0.8\n",
            encoding="utf-8",
        )
        out_dir = root / "out"
        build([root / "in"], out_dir)

        manifest = json.loads((out_dir / "catalog.json").read_text(encoding="utf-8"))
        assert len(manifest) == 1, manifest
        assert manifest[0]["entryCount"] == 2, manifest
        assert manifest[0]["country"] == "JP", manifest
        assert manifest[0]["url"].endswith(manifest[0]["filename"]), manifest
        # Present and parseable, so the app can compare it against its copy.
        assert datetime.datetime.fromisoformat(manifest[0]["updatedAt"]), manifest
        assert manifest[0]["patch"] is None, "nothing to diff against on a first build"

        rows = list_format.read_list(out_dir / manifest[0]["filename"])
        assert rows == [(81312345678, "渋谷クリニック"), (81398765432, "Test Cafe")], rows

        # Rebuild with one row changed and one added: the patch must describe it.
        # The stamp comes from the file's mtime, so move it on explicitly rather
        # than relying on the clock ticking between two writes.
        (source_dir / "data_0.csv").write_text(
            header
            + "Demo,81312345678,渋谷クリニック 分院,0.9\n"
            + "Demo,81355556666,New Place,0.8\n",
            encoding="utf-8",
        )
        stamp = (source_dir / "data_0.csv").stat().st_mtime + 3600
        os.utime(source_dir / "data_0.csv", (stamp, stamp))
        build([root / "in"], out_dir)

        manifest = json.loads((out_dir / "catalog.json").read_text(encoding="utf-8"))
        patch = manifest[0]["patch"]
        assert patch is not None, "a changed source should produce a patch"
        assert (patch["removals"], patch["upserts"]) == (1, 2), patch
        assert (out_dir / patch["filename"]).exists()

        # The publisher's own reference application must reproduce the new table.
        assert list_format.apply_patch(rows, out_dir / patch["filename"]) == \
            list_format.read_list(out_dir / manifest[0]["filename"])

        # A suppression list may carry blank labels, and must outrank everything
        # else so that it can actually withdraw a name.
        removals = root / "in" / "source=Suppressions"
        removals.mkdir(parents=True)
        (removals / "data_0.csv").write_text(
            header + "Suppressions,81398765432,,1.0\n", encoding="utf-8"
        )
        build([root / "in"], out_dir)
        manifest = json.loads((out_dir / "catalog.json").read_text(encoding="utf-8"))
        assert manifest[0]["source"] == "Suppressions", [m["source"] for m in manifest]
        assert manifest[0]["entryCount"] == 1, manifest[0]
        assert list_format.read_list(out_dir / manifest[0]["filename"]) == [(81398765432, "")]
    print("demo ok")


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--demo":
        demo()
    elif len(sys.argv) >= 3:
        # Several input directories so the Japanese harvest and the worldwide
        # one land in a single catalogue.
        build([Path(argument) for argument in sys.argv[1:-1]], Path(sys.argv[-1]))
    else:
        sys.exit(__doc__)
