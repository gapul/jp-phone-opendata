#!/usr/bin/env python3
"""Refuse to publish a build where a source appears to have collapsed.

Half of these lists come from scraping government sites that change layout, move
files, or simply fail to answer. Every fetcher tolerates individual failures so
one dead link cannot stop a run — which means a site-wide change shows up not as
an error but as a list that quietly lost most of its rows.

Publishing that over a good release would push the damage to every subscriber, so
compare against the copy being replaced and stop if anything shrank sharply. Also
writes the release notes, since it has both sides in hand.

Usage:
    python3 scripts/check_release.py dist
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

# Real month-to-month movement in these registers is low single digits, so this
# is loose enough never to fire on ordinary churn.
MAX_SHRINK = 0.20
# Below this a list is small enough that percentages are meaningless.
IGNORE_BELOW = 100


def main(dist: Path) -> None:
    catalog = json.loads((dist / "catalog.json").read_text(encoding="utf-8"))
    previous_path = dist / "catalog.previous.json"
    previous = {}
    if previous_path.exists():
        previous = {
            entry["id"]: entry
            for entry in json.loads(previous_path.read_text(encoding="utf-8"))
        }

    problems = []
    lines = []
    for entry in catalog:
        before = previous.get(entry["id"], {}).get("entryCount")
        now = entry["entryCount"]
        if before and before >= IGNORE_BELOW:
            change = (now - before) / before
            if change < -MAX_SHRINK:
                problems.append(
                    f"{entry['id']}: {before:,} -> {now:,} ({change:+.0%})"
                )
            lines.append(f"- {entry['country']} {entry['title']}: {now:,} ({change:+.1%})")
        else:
            lines.append(f"- {entry['country']} {entry['title']}: {now:,}")

    if problems:
        print("refusing to publish; these lists lost too much:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        sys.exit(1)

    removals = Path("data/suppressions/source=Suppressions/data_0.csv")
    if removals.exists():
        with removals.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        verified = sum(1 for row in rows if row["verified"] == "yes")
        lines.append(f"- Removals honoured: {len(rows):,} "
                     f"({verified:,} verified, {len(rows) - verified:,} on request)")

    total = sum(entry["entryCount"] for entry in catalog)
    patched = [entry for entry in catalog if entry.get("patch")]
    notes = [f"{total:,} numbers across {len(catalog)} lists.", ""]
    notes.extend(lines)
    if patched:
        notes += ["", "Incremental updates available for:"]
        notes += [
            f"- {entry['title']}: {entry['patch']['byteCount'] / 1024 / 1024:.2f} MB"
            f" vs {entry['byteCount'] / 1024 / 1024:.1f} MB"
            for entry in patched
        ]
    (dist / "RELEASE_NOTES.md").write_text("\n".join(notes) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
