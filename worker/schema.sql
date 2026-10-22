-- D1: cliques sem IP e sem user-agent. O pipeline copia para o Postgres e apaga após 7 dias.
CREATE TABLE IF NOT EXISTS clicks (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  ts         TEXT NOT NULL,
  niche      TEXT NOT NULL,
  channel    TEXT NOT NULL,
  content_id TEXT,
  country    TEXT
);
CREATE INDEX IF NOT EXISTS ix_clicks_ts ON clicks (ts);
