#!/usr/bin/env python3
"""Check a removal request against the domain the source data ties to the number.

Sending a one-time code to the number itself would be better evidence, but call
and SMS termination costs money, so there is no free way to do it.

The free alternative has a trap in it. Asking the requester to put a token on a
page they nominate proves only that they control *some* website — anyone can put
anyone else's number on their own page and pass, which would let someone remove a
competitor's listing and have it recorded as verified. So the domain is not the
requester's to choose: it has to be one the upstream data already publishes
alongside that number, from `fetch_number_websites.py`. Then passing means the
site that claims the number vouches for the request.

Requesters whose number has no website in the data cannot use this, and neither
can anyone whose number was published by somebody else. Those need a human.

Usage:
    python3 scripts/verify_owner.py https://example.jp/contact 03-1234-5678 TOKEN
    python3 scripts/verify_owner.py --demo
"""

from __future__ import annotations

import csv
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from jp_phone import normalize as normalize_jp

USER_AGENT = "jp-phone-opendata (+https://github.com/gapul/jp-phone-opendata)"
WEBSITES = Path("data/verification")
# Long enough that it cannot appear by chance on a page.
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9]{16,}$")

# Hosts where anyone can publish a page. A business's own domain covering many
# numbers is fine — a chain vouching for its own branches — but on these the
# numbers belong to unrelated people, so controlling one page there says nothing
# about the number. Counting how many numbers a host covers cannot tell the two
# apart, so this is a list, and it will always be incomplete.
MULTI_TENANT = {
    "instagram.com", "facebook.com", "m.facebook.com", "business.site",
    "sites.google.com", "wixsite.com", "jimdofree.com", "jimdosite.com",
    "wordpress.com", "blogspot.com", "hatenablog.com", "amebaownd.com",
    "ameblo.jp", "jugem.jp", "goo.ne.jp", "fc2.com", "web.fc2.com",
    "shopify.com", "myshopify.com", "square.site", "linktr.ee", "peraichi.com",
    "tabelog.com", "hotpepper.jp", "ekiten.jp", "yelp.com", "tripadvisor.com",
}


def is_multi_tenant(host: str) -> bool:
    """True for a shared platform, matching subdomains as well as the apex."""
    return any(host == known or host.endswith("." + known) for known in MULTI_TENANT)


def hosts_for(number: int) -> set[str]:
    """Domains the source data publishes alongside this number."""
    found: set[str] = set()
    for path in sorted(WEBSITES.glob("websites_*.csv")):
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if row["number"] == str(number) and row["host"]:
                    found.add(row["host"].lower().removeprefix("www."))
    return found


def check(page: str, url: str, number: int, token: str, known: set[str]) -> tuple[bool, str]:
    if not TOKEN_PATTERN.match(token):
        return False, "the token is too short to be meaningful"

    host = (urllib.parse.urlparse(url).hostname or "").lower().removeprefix("www.")
    if not host:
        return False, "that is not a usable URL"
    usable = {name for name in known if not is_multi_tenant(name)}
    if not usable:
        return False, ("no website of their own is associated with that number, "
                       "so this route cannot prove anything")
    if is_multi_tenant(host):
        return False, f"{host} is a shared platform; anyone can publish there"
    if host not in usable:
        return False, f"{host} is not a site the data ties to that number ({', '.join(sorted(usable))})"
    if token not in page:
        return False, "token not found on the page"
    return True, f"{host} publishes that number and carries the token"


def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read(2_000_000).decode("utf-8", errors="replace")
    except Exception as error:  # noqa: BLE001 - the URL comes from a stranger
        # An unreachable page is an ordinary outcome here, not a crash.
        sys.exit(f"not verified: could not fetch {url} ({error})")


def demo() -> None:
    token = "A1b2C3d4E5f6G7h8"
    page = f"<!-- ownership: {token} -->"
    number = 81312345678
    known = {"example.jp"}

    assert check(page, "https://example.jp/contact", number, token, known)[0]
    # www is the same site.
    assert check(page, "https://www.example.jp/contact", number, token, known)[0]

    # The whole point: a site the requester controls but the data does not tie to
    # this number must fail, however convincing the page is.
    passed, reason = check(page, "https://attacker.example/", number, token, known)
    assert not passed and "not a site the data ties" in reason, reason

    assert not check(page, "https://example.jp/", number, token, set())[0]

    # A shared platform must not stand in for a domain of one's own, in either
    # direction: not as the URL offered, and not as the only thing on record.
    passed, reason = check(page, "https://instagram.com/someone", number, token,
                           {"instagram.com", "example.jp"})
    assert not passed and "shared platform" in reason, reason
    passed, reason = check(page, "https://example.jp/", number, token, {"instagram.com"})
    assert not passed and "website of their own" in reason, reason
    # Subdomains of a platform count as the platform.
    assert is_multi_tenant("cafe-maru.jugem.jp")
    assert not check("no token here", "https://example.jp/", number, token, known)[0]
    assert not check(page, "https://example.jp/", number, "short", known)[0]
    print("verify_owner: demo ok")


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--demo":
        demo()
    elif len(sys.argv) == 4:
        url, raw, token = sys.argv[1:]
        target = normalize_jp(raw) or int("".join(c for c in raw if c.isdigit()) or 0)
        passed, reason = check(fetch(url), url, target, token, hosts_for(target))
        print(("verified: " if passed else "not verified: ") + reason)
        sys.exit(0 if passed else 1)
    else:
        sys.exit(__doc__)
