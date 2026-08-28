-- Extract Japanese business phone numbers from Overture Places.
--
-- Output: one CSV per upstream source, each sorted ascending with unique numbers.
-- CallKit's Call Directory extension requires strictly ascending, unique numbers,
-- so ordering and per-list deduplication happen here rather than in the client.
--
-- Splitting by source is what lets the app work like an ad blocker: the sources
-- differ a lot in quality (Microsoft ~0.90 confidence, AllThePlaces ~0.81 from
-- official store locators, Meta ~0.77 but 76% of the volume), so the user picks
-- which lists to subscribe to. Numbers present in several enabled lists are
-- resolved at merge time by list priority.
--
-- Japan's places all live in a single parquet part file, so we read only that one
-- instead of scanning the whole 74M-row global theme (which times out).
--
-- Usage:
--   duckdb -c ".read scripts/extract_jp_places.sql"

INSTALL httpfs;
LOAD httpfs;
SET s3_region = 'us-west-2';
SET http_timeout = 300000;

COPY (
    WITH raw AS (
        SELECT
            unnest(phones)     AS phone,
            names.primary      AS label,
            sources[1].dataset AS source,
            confidence
        FROM read_parquet(
            's3://overturemaps-us-west-2/release/2026-08-19.0/theme=places/type=place/part-00015-*.parquet'
        )
        WHERE bbox.xmin BETWEEN 122.9 AND 153.99
          AND bbox.ymin BETWEEN 20.4 AND 45.6
          AND phones IS NOT NULL
          AND len(phones) > 0
          AND names.primary IS NOT NULL
    ),
    digits AS (
        SELECT regexp_replace(phone, '[^0-9]', '', 'g') AS d, label, source, confidence
        FROM raw
    ),
    normalized AS (
        -- Overture mixes E.164 (+81332221111) with domestic notation (0332221111),
        -- plus the common data-entry mistake of keeping both the country code and
        -- the national trunk prefix (+81 03-xxxx-xxxx -> 810312345678).
        -- All three become the E.164 digits CallKit wants, without the leading '+'.
        SELECT
            CASE
                WHEN starts_with(d, '810') THEN '81' || substr(d, 4)
                WHEN starts_with(d, '81')  THEN d
                WHEN starts_with(d, '0')   THEN '81' || substr(d, 2)
            END AS e164,
            label,
            source,
            confidence
        FROM digits
    )
    SELECT
        source,
        CAST(e164 AS BIGINT)          AS number,
        arg_max(label, confidence)    AS label,
        max(confidence)               AS confidence
    FROM normalized
    -- 81 + 9 or 10 national digits. Anything else is a foreign or malformed number.
    WHERE e164 IS NOT NULL
      AND length(e164) BETWEEN 11 AND 12
      -- No Japanese national number starts with 0 once the trunk prefix is stripped,
      -- so this drops junk like 0001495688 that survives the length check.
      AND substr(e164, 3, 1) BETWEEN '1' AND '9'
      -- A 10-digit national number is only valid for mobile (70/80/90), IP phones
      -- (50), M2M (20) and 0800 toll-free, which shares the 80 prefix. Geographic
      -- numbers are always 9 digits, so anything else of this length is malformed.
      AND (
          length(e164) = 11
          OR substr(e164, 3, 2) IN ('70', '80', '90', '50', '20')
      )
      -- And the reverse: those ranges are always ten digits, so a nine-digit one
      -- has a digit missing. Geographic area codes never start 050/060/070/080/090.
      AND NOT (
          length(e164) = 11
          AND substr(e164, 3, 2) IN ('50', '60', '70', '80', '90')
      )
      AND source IS NOT NULL
    GROUP BY source, number
    ORDER BY source, number
) TO 'data/ios' (FORMAT CSV, HEADER, PARTITION_BY (source), OVERWRITE_OR_IGNORE);
