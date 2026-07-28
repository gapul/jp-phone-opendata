-- D1 schema for the number-prefix -> carrier table.
CREATE TABLE IF NOT EXISTS prefixes (
  prefix  TEXT PRIMARY KEY,
  carrier TEXT NOT NULL
);
