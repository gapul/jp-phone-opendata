# JP Phone Directory (iOS)

Shows the business name for an incoming call, from open data, entirely
on the device. No lookup leaves the phone.

The app ships with no data. It works like an ad blocker: subscribe to lists by
URL, or take one of the suggestions it fetches from a published catalogue. Lists
can be toggled and reordered, the topmost one wins a number that appears in
several, and subscriptions update themselves incrementally.

Coverage is worldwide: 49.0 million numbers, 338 lists, 222 countries. The app
offers the ones for its own region first, since a flat catalogue that size would
be unusable.

| Country | Lists | Numbers |
|---|---|---|
| United States | 7 | 10,769,510 |
| Japan | 7 | 2,500,025 |
| Italy | 2 | 1,699,972 |
| France | 4 | 1,541,645 |
| United Kingdom | 4 | 1,528,506 |
| Germany | 5 | 1,476,086 |

Most of that is Overture, which is bulk of mixed quality. The rest comes from
registers and store locators, which is smaller and much better: the Japanese
long-term care and clinic registers, US healthcare providers from NPPES, and All
the Places worldwide. In Japan, everything except Overture's Meta list is about
840,000 numbers and is entirely registry or first-party data.

Enabling too much is a real risk: a Call Directory extension only reliably takes
so many, so the app counts what the merge would actually register and warns above
1.5 million.

## Removal requests

A list can blank a number out rather than name it, and those entries sort above
every other list. That is how a request is answered without waiting for the
upstream source, which often will not move: a Japanese care provider's number is
in a statutory register, and nobody is going to get it struck from there.

```sh
python3 scripts/whois.py dist 03-1234-5678             # which lists, whose data
python3 scripts/verify_owner.py <url> 03-1234-5678 <token>
python3 scripts/suppress.py 03-1234-5678 --verified    # or --unverified
```

Ownership can sometimes be shown for free. Sending a one-time code to the number
would be better evidence, but call and SMS termination costs money, so there is
no free version of that. The website route is the free one, and the obvious way
to build it does not work: asking the requester to put a token on a page they
nominate proves only that they control some website, so anyone could remove a
competitor's listing and have it recorded as verified.

What it checks instead is a domain the *source data* already publishes alongside
that number, harvested by `fetch_number_websites.py` — 37 million number/host
pairs from Overture. Shared platforms are excluded, since controlling one page on
instagram.com says nothing about whose number it is; that exclusion is a list and
will always be incomplete. Numbers with no site of their own, and anyone whose
number was published by somebody else, still need a human.

`whois.py` says which lists carry the number and who published it upstream;
`suppress.py` records the removal. Then the requester is also pointed at the
upstream, since that is the only fix that stops it reaching other consumers of
the same data.

Requests are honoured either way — a wrongly granted removal costs a business a
listing it never asked for, a wrongly refused one leaves somebody's number
published, and those are not comparable. Whether ownership was confirmed is
recorded all the same, because it decides what happens if a removal is later
disputed: an unverified one can reasonably be reversed, a verified one cannot.
`data/suppressions/` is the only hand-maintained data here and the only data kept
in git, since it is the record of what was removed and why. Release notes carry
the running count.

## Running it

Needs Xcode, a paid signing team (the app and its extension share an App Group),
and a while for the data — the municipal sweep alone runs over half an hour.

```sh
duckdb -c ".read scripts/extract_jp_places.sql"
python3 scripts/fetch_places_world.py data/world   # 16 files, ~10 GB scanned
python3 scripts/fetch_alltheplaces.py data/world   # ~4,800 spiders
python3 scripts/fetch_nppes_us.py data/world       # 1.1 GB archive, cached
python3 scripts/fetch_mhlw_care_jp.py data/ios
python3 scripts/fetch_kouseikyoku_iryo_jp.py data/ios
nix shell nixpkgs#poppler-utils --command \
    python3 scripts/fetch_kouseikyoku_pdf_jp.py data/ios
python3 scripts/fetch_municipal_facilities_jp.py data/ios
python3 scripts/build_calldir_db.py data/ios data/world data/suppressions dist

cd ios && xcodegen generate && open JPPhoneDirectory.xcodeproj
```

Run on a device, then enable it under Settings › Apps › Phone › Call Blocking &
Identification. The simulator builds but cannot load the extension.

Lists and clients are released separately: `publish-lists.yml` replaces a rolling
`lists` release monthly, `publish-apps.yml` builds the IPA and APK when an
`apps-*` tag is pushed. The fixed tag matters — the app's catalogue URL points at
it, and an app release claiming "latest" would otherwise leave subscribers
without one.

## List format

A packed `.bin`, or text with one `number,label` per line. `-` at the start of a
line blanks that number out instead of naming it; `#` and `!` are comments.
Numbers may be written `03-1234-5678` or `+81 3 1234 5678`. Text lists are packed
on the device, so anyone can publish one from an editor.

```
# my corrections
-0120-000-000
03-1234-5678,Actually the dentist
```

## Contributing

Adding a source means writing a `scripts/fetch_*.py` that drops CSVs into
`data/<region>/source=<Name>/`, or `source_key=<CC>-<Name>/` when it spans
countries, and giving it a title in `build_calldir_db.py`. Everything downstream
picks it up. Japanese sources can use `jp_phone.normalize`; elsewhere the numbers
have to already be E.164, since guessing another country's dialling rules is how
you invent numbers that do not exist.

```sh
python3 scripts/jp_phone.py            # number rules
python3 scripts/build_calldir_db.py --demo
(cd ios/PhoneDirectoryKit && swift test)

swiftc -O -parse-as-library \
    ios/PhoneDirectoryKit/Sources/PhoneDirectoryKit/PhoneList.swift \
    scripts/verify_db.swift -o /tmp/verify_db
for f in dist/places_*.bin; do /tmp/verify_db "$f"; done
```

Known gaps, roughly in order of how much they would help:

- **Two bureaus missing.** Kinki (Osaka) publishes no clinic list this could
  find; Kyushu's only match was an explanatory note. Names from the PDF bureaus
  are reassembled from a wrapped fixed-width column, so some are clipped.
- **Municipal coverage is thin.** BODIK's shared CKAN covers a few hundred of the
  ~1,700 municipalities, and only 417 of its 5,605 CSVs carry a phone column.
- **Registry data covers Japan and the US only.** NHS ODS would be the obvious
  next one — it is OGL and carries contact details — but `files.digital.nhs.uk`
  answers 403 to everything from here, including its own landing page.
- **Country tags come from Overture and are sometimes wrong**, so a number can be
  filed under a country its dialling code does not match. Deriving the country
  from the E.164 prefix instead needs a calling-code table, which is ambiguous
  across the +1 countries.
- **A release is now about 1.6 GB.** Subscribers only fetch their own country,
  and updates are incremental, but the release itself is heavy.
- **Number validation checks shape, not allocation.** The MIC allocation table
  this repo already builds would be the authoritative fix.
