CREATE TABLE IF NOT EXISTS subscriptions (
  id           SERIAL PRIMARY KEY,
  email        TEXT NOT NULL,
  group_number INTEGER NOT NULL,
  week_start   DATE NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_subs_week ON subscriptions(week_start);

CREATE TABLE IF NOT EXISTS notifications_sent (
  subscription_id INTEGER NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
  court_day       DATE NOT NULL,
  sent_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (subscription_id, court_day)
);

CREATE TABLE IF NOT EXISTS scrape_log (
  id               SERIAL PRIMARY KEY,
  ran_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  status           TEXT NOT NULL,
  blocks           INTEGER,
  error            TEXT,
  page_fingerprint TEXT
);
ALTER TABLE scrape_log ADD COLUMN IF NOT EXISTS page_fingerprint TEXT;

-- Privacy-safe activity log. No PII stored. Never deleted so we can show
-- all-time counts in the weekly summary email.
CREATE TABLE IF NOT EXISTS events (
  id           SERIAL PRIMARY KEY,
  type         TEXT NOT NULL,      -- 'page_view' | 'registration' | 'notification'
  occurred_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_events_type_time ON events(type, occurred_at);
