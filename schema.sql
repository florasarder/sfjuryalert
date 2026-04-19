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
  id      SERIAL PRIMARY KEY,
  ran_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  status  TEXT NOT NULL,
  blocks  INTEGER,
  error   TEXT
);
