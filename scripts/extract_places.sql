-- Extract business phone numbers from one Overture Places part file, worldwide.
--
-- Japan is handled by `extract_jp_places.sql`, which can be strict because it
-- knows the national numbering plan. Everywhere else there is no such knowledge
-- here, so this leans on Overture already storing E.164 and only checks shape.
--
-- Places are businesses and public venues by definition, which is what keeps
-- this on the right side of the line: no individuals, only organisations that
-- published a contact number.
--
-- A template rather than a runnable script: DuckDB only accepts literals as a
-- COPY target, so `fetch_places_world.py` substitutes the three placeholders.

INSTALL httpfs;
LOAD httpfs;
SET s3_region = 'us-west-2';
SET http_timeout = 600000;

COPY (
    WITH raw AS (
        SELECT
            unnest(phones)       AS phone,
            names.primary        AS label,
            addresses[1].country AS country,
            sources[1].dataset   AS source,
            confidence
        FROM read_parquet('{part}')
        WHERE phones IS NOT NULL
          AND len(phones) > 0
          AND names.primary IS NOT NULL
          -- Some rows carry an empty country rather than a null one.
          AND length(addresses[1].country) = 2
          -- Japan comes from the dedicated script, which validates properly.
          AND addresses[1].country <> 'JP'
    ),
    normalized AS (
        SELECT
            regexp_replace(phone, '[^0-9]', '', 'g') AS digits,
            label,
            country,
            source,
            confidence
        FROM raw
        -- Only take numbers already written in international form. Anything in
        -- national notation would need that country's dialling rules to expand,
        -- and guessing them is how you invent numbers that do not exist.
        WHERE starts_with(trim(phone), '+')
    )
    SELECT
        country || '-' || source     AS source_key,
        CAST(digits AS BIGINT)       AS number,
        arg_max(label, confidence)   AS label,
        max(confidence)              AS confidence
    FROM normalized
    -- E.164 allows at most 15 digits, and nothing real is shorter than 8.
    WHERE length(digits) BETWEEN 8 AND 15
    GROUP BY source_key, number
    ORDER BY source_key, number
) TO '{out}' (FORMAT CSV, HEADER, PARTITION_BY (source_key),
              OVERWRITE_OR_IGNORE, FILENAME_PATTERN '{pattern}');
