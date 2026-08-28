"""Read and write the packed list and patch formats.

Both are described in `build_calldir_db.py`. Patches exist because a monthly
refresh of a 57 MB list changes only a small part of it, and the tables are
already sorted by number — so the difference between two releases is a linear
merge rather than a binary diff.

Patch layout (little-endian):

    magic        "JPCP"      4 bytes
    version      UInt32      1
    removeCount  UInt32      numbers that disappeared
    upsertCount  UInt32      numbers added, or whose label changed
    removals     Int64  x removeCount        ascending
    numbers      Int64  x upsertCount        ascending
    offsets      UInt32 x (upsertCount + 1)  byte ranges into `labels`
    labels       UTF-8 bytes
"""

from __future__ import annotations

import struct
from pathlib import Path

LIST_MAGIC = b"JPCD"
PATCH_MAGIC = b"JPCP"
VERSION = 1
HEADER_SIZE = 16


def write_list(rows: list[tuple[int, str]], out_path: Path) -> int:
    """Rows must be ascending by number; duplicates are dropped."""
    numbers: list[int] = []
    offsets: list[int] = [0]
    labels = bytearray()

    previous = -1
    for number, label in rows:
        # CallKit rejects the whole batch if numbers are not strictly ascending.
        if number <= previous:
            continue
        previous = number
        numbers.append(number)
        labels.extend(label.encode("utf-8"))
        offsets.append(len(labels))

    count = len(numbers)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("wb") as out:
        out.write(LIST_MAGIC)
        out.write(struct.pack("<III", VERSION, count, 0))
        out.write(struct.pack(f"<{count}q", *numbers))
        out.write(struct.pack(f"<{count + 1}I", *offsets))
        out.write(labels)
    return count


def read_list(path: Path) -> list[tuple[int, str]]:
    blob = path.read_bytes()
    if blob[:4] != LIST_MAGIC:
        raise ValueError(f"{path} is not a packed list")
    version, count, _ = struct.unpack_from("<III", blob, 4)
    if version != VERSION:
        raise ValueError(f"{path} has version {version}")

    numbers = struct.unpack_from(f"<{count}q", blob, HEADER_SIZE)
    offsets_at = HEADER_SIZE + count * 8
    offsets = struct.unpack_from(f"<{count + 1}I", blob, offsets_at)
    labels = blob[offsets_at + (count + 1) * 4:]
    return [
        (numbers[i], labels[offsets[i]:offsets[i + 1]].decode("utf-8"))
        for i in range(count)
    ]


def write_patch(old: list[tuple[int, str]], new: list[tuple[int, str]], out_path: Path) -> tuple[int, int]:
    """Diffs two ascending tables. Returns (removals, upserts)."""
    old_by_number = dict(old)
    new_by_number = dict(new)

    removals = sorted(number for number in old_by_number if number not in new_by_number)
    upserts = sorted(
        (number, label)
        for number, label in new_by_number.items()
        if old_by_number.get(number) != label
    )

    numbers = [number for number, _ in upserts]
    offsets = [0]
    labels = bytearray()
    for _, label in upserts:
        labels.extend(label.encode("utf-8"))
        offsets.append(len(labels))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("wb") as out:
        out.write(PATCH_MAGIC)
        out.write(struct.pack("<III", VERSION, len(removals), len(upserts)))
        out.write(struct.pack(f"<{len(removals)}q", *removals))
        out.write(struct.pack(f"<{len(numbers)}q", *numbers))
        out.write(struct.pack(f"<{len(offsets)}I", *offsets))
        out.write(labels)
    return len(removals), len(upserts)


def apply_patch(base: list[tuple[int, str]], patch_path: Path) -> list[tuple[int, str]]:
    """Reference implementation of what the app does, used to check the writer."""
    blob = patch_path.read_bytes()
    if blob[:4] != PATCH_MAGIC:
        raise ValueError(f"{patch_path} is not a patch")
    version, remove_count, upsert_count = struct.unpack_from("<III", blob, 4)
    if version != VERSION:
        raise ValueError(f"{patch_path} has version {version}")

    at = HEADER_SIZE
    removals = set(struct.unpack_from(f"<{remove_count}q", blob, at))
    at += remove_count * 8
    numbers = struct.unpack_from(f"<{upsert_count}q", blob, at)
    at += upsert_count * 8
    offsets = struct.unpack_from(f"<{upsert_count + 1}I", blob, at)
    at += (upsert_count + 1) * 4
    labels = blob[at:]

    merged = {number: label for number, label in base if number not in removals}
    for index in range(upsert_count):
        merged[numbers[index]] = labels[offsets[index]:offsets[index + 1]].decode("utf-8")
    return sorted(merged.items())
