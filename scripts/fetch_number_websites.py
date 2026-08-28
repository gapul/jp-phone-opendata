#!/usr/bin/env python3
"""Extract which websites a phone number is published on, for verifying removals.

A removal request that points at a page the requester controls proves nothing:
anyone can put anyone's number on their own site. The check is only worth
anything if the domain is one the *source data* already associates with that
number, so this pulls that association out of Overture, which carries `websites`
alongside `phones`.

Not published with the lists. It exists so `verify_owner.py` has something
independent to check a claim against.

Usage:
    python3 scripts/fetch_number_websites.py data/verification [release]
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

BUCKET = "https://overturemaps-us-west-2.s3.amazonaws.com"
S3_ROOT = "s3://overturemaps-us-west-2/release"
DEFAULT_RELEASE = "2026-08-19.0"

TEMPLATE = """
INSTALL httpfs;
LOAD httpfs;
SET s3_region = 'us-west-2';
SET http_timeout = 600000;

COPY (
    WITH raw AS (
        SELECT unnest(phones) AS phone, unnest(websites) AS website
        FROM read_parquet('{part}')
        WHERE phones IS NOT NULL AND len(phones) > 0
          AND websites IS NOT NULL AND len(websites) > 0
    )
    SELECT DISTINCT
        regexp_replace(phone, '[^0-9]', '', 'g') AS number,
        -- Host only: a page can move but the domain is what ownership follows.
        lower(regexp_extract(website, '^[a-zA-Z]+://([^/:]+)', 1)) AS host
    FROM raw
    WHERE length(regexp_replace(phone, '[^0-9]', '', 'g')) BETWEEN 8 AND 15
      AND regexp_extract(website, '^[a-zA-Z]+://([^/:]+)', 1) <> ''
) TO '{out}' (FORMAT CSV, HEADER);
"""


def parts(release: str) -> list[str]:
    prefix = f"release/{release}/theme%3Dplaces/type%3Dplace/"
    with urllib.request.urlopen(f"{BUCKET}/?list-type=2&prefix={prefix}", timeout=90) as response:
        listing = response.read().decode("utf-8")
    return [name.split("/")[-1]
            for name in sorted(re.findall(r"<Key>([^<]+\.parquet)</Key>", listing))]


def main(out_root: Path, release: str) -> None:
    out_root.mkdir(parents=True, exist_ok=True)
    files = parts(release)
    print(f"{len(files)} part files in {release}")

    for index, part in enumerate(files):
        destination = out_root / f"websites_{index:02d}.csv"
        if destination.exists():
            continue
        print(f"[{index + 1}/{len(files)}] {part}", flush=True)
        script = TEMPLATE.format(
            part=f"{S3_ROOT}/{release}/theme=places/type=place/{part}",
            out=destination,
        )
        with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False) as handle:
            handle.write(script)
            rendered = handle.name
        try:
            subprocess.run(["duckdb", "-c", f".read {rendered}"], check=True)
        except subprocess.CalledProcessError as error:
            print(f"  failed: {error}", file=sys.stderr)
        finally:
            Path(rendered).unlink(missing_ok=True)

    rows = sum(
        sum(1 for _ in path.open(encoding="utf-8")) - 1
        for path in out_root.glob("websites_*.csv")
    )
    print(f"{rows:,} number/host pairs")


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    main(Path(sys.argv[1]), sys.argv[2] if len(sys.argv) == 3 else DEFAULT_RELEASE)
