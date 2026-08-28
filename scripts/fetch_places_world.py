#!/usr/bin/env python3
"""Run the worldwide Overture extraction across every part file.

The Japanese slice happens to sit in a single part, which is why
`extract_jp_places.sql` can read one file. Worldwide there is no such luck: the
release is 16 files and roughly 10 GB, so this walks them one at a time. Column
pruning means far less than that crosses the network, but a single query over
all of them times out, which is the reason for the loop.

Output lands in `data/world/source_key=<CC>-<Source>/`, matching what
`build_calldir_db.py` already consumes.

Usage:
    python3 scripts/fetch_places_world.py data/world [release]
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

BUCKET = "https://overturemaps-us-west-2.s3.amazonaws.com"
S3_ROOT = "s3://overturemaps-us-west-2/release"
DEFAULT_RELEASE = "2026-08-19.0"
SQL = Path(__file__).with_name("extract_places.sql")


def parts(release: str) -> list[str]:
    prefix = f"release/{release}/theme%3Dplaces/type%3Dplace/"
    with urllib.request.urlopen(f"{BUCKET}/?list-type=2&prefix={prefix}", timeout=90) as response:
        listing = response.read().decode("utf-8")
    names = re.findall(r"<Key>([^<]+\.parquet)</Key>", listing)
    return [name.split("/")[-1] for name in sorted(names)]


def run(part: str, index: int, release: str, out: Path) -> None:
    location = f"{S3_ROOT}/{release}/theme=places/type=place/{part}"
    script = SQL.read_text().format(
        part=location,
        out=out,
        # Each part writes its own file inside the shared partition directories,
        # so later parts do not overwrite earlier ones.
        pattern=f"part{index:02d}",
    )
    with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False) as handle:
        handle.write(script)
        rendered = handle.name
    try:
        subprocess.run(["duckdb", "-c", f".read {rendered}"], check=True)
    finally:
        Path(rendered).unlink(missing_ok=True)


def main(out: Path, release: str) -> None:
    files = parts(release)
    print(f"{len(files)} part files in {release}")
    for index, part in enumerate(files):
        print(f"[{index + 1}/{len(files)}] {part}", flush=True)
        try:
            run(part, index, release, out)
        except subprocess.CalledProcessError as error:
            # One unreadable part costs its share of the world, not the run.
            print(f"  failed: {error}", file=sys.stderr)

    countries = sorted({
        directory.name.split("=", 1)[1].split("-", 1)[0]
        for directory in out.glob("source_key=*")
    })
    print(f"{len(countries)} countries: {' '.join(countries)}")


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    release = sys.argv[2] if len(sys.argv) == 3 else DEFAULT_RELEASE
    main(Path(sys.argv[1]), release)
