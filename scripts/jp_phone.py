"""Japanese phone number normalisation, shared by the list fetchers.

Kept in one place because the rules are subtle enough that three drifting copies
would eventually disagree about which numbers exist. `extract_jp_places.sql`
implements the same rules in SQL, and `PhoneListPacker.swift` in Swift for lists
imported on the device.
"""

from __future__ import annotations


def normalize(raw: str) -> int | None:
    """Returns E.164 digits without the leading '+', or None if unusable.

    Accepts national notation (`03-1234-5678`), E.164 (`+81 3 1234 5678`), and
    the common data-entry mistake of keeping both the country code and the
    national trunk prefix (`+81 03-...`).
    """
    # Only ASCII digits, after folding the full-width forms Japanese sources mix
    # in. `str.isdigit()` is not enough: it accepts things like '⑹', which then
    # fail to convert — the ministry's register really does contain those.
    folded = "".join(
        chr(ord(character) - 0xFEE0) if "０" <= character <= "９" else character
        for character in raw
    )
    digits = "".join(character for character in folded if "0" <= character <= "9")

    if digits.startswith("810"):
        e164 = "81" + digits[3:]
    elif digits.startswith("81"):
        e164 = digits
    elif digits.startswith("0"):
        e164 = "81" + digits[1:]
    else:
        return None

    # 81 + 9 or 10 national digits.
    if len(e164) not in (11, 12):
        return None

    national = e164[2:]
    # No Japanese national number starts with 0 once the trunk prefix is stripped.
    if not national or national[0] == "0":
        return None
    # A 10-digit national number is only valid for mobile (70/80/90), IP phones
    # (50), M2M (20) and 0800 toll-free, which shares the 80 prefix. Geographic
    # numbers are always 9 digits, so checking one digit is not enough: it would
    # admit things like 098-485-71117, an Okinawa number with a digit too many.
    if len(national) == 10 and national[:2] not in ("70", "80", "90", "50", "20"):
        return None
    # And the reverse: the non-geographic ranges are *always* ten digits, so a
    # nine-digit one is a number with a digit missing rather than a landline.
    # Geographic area codes never start 050/060/070/080/090, so this is safe.
    if len(national) == 9 and national[:2] in ("50", "60", "70", "80", "90"):
        return None

    return int(e164)


def demo() -> None:
    """Self-check. Every case here is one the real feeds actually produced."""
    cases = [
        ("03-1234-5678", 81312345678),
        ("+81 3 1234 5678", 81312345678),
        ("+81 03-1234-5678", 81312345678),      # country code plus retained trunk zero
        ("０３－１２３４－５６７８", 81312345678),   # full-width digits
        ("090-1234-5678", 819012345678),
        ("0120-123-456", 81120123456),
        ("0800-123-4567", 818001234567),        # toll-free shares the 80 prefix
        ("816⑹6550823", None),                  # circled numeral in the care register
        ("+1 202 555 0100", None),              # not Japanese
        ("0001495688", None),                   # malformed
        ("098-485-71117", None),                # Okinawa number with a digit too many
        ("050-280-8888", None),                 # 050 with a digit missing
        ("082-123-4567", 81821234567),          # Hiroshima, not an 080 mobile
        ("", None),
    ]
    for raw, expected in cases:
        actual = normalize(raw)
        assert actual == expected, f"{raw!r} -> {actual}, expected {expected}"
    print(f"normalize: {len(cases)} cases ok")


if __name__ == "__main__":
    demo()
