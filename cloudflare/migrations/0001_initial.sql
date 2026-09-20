CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  company TEXT NOT NULL,
  title TEXT NOT NULL,
  location TEXT NOT NULL,
  url TEXT NOT NULL,
  created_at TEXT NOT NULL
);

-- Synthetic examples only. Never put personal dossier or live application data here.
INSERT OR IGNORE INTO jobs (id, company, title, location, url, created_at) VALUES
  ('synthetic-001', 'Example North', 'Operations Analyst', 'Toronto, ON', 'https://example.invalid/jobs/1', '2026-09-19T00:00:00Z'),
  ('synthetic-002', 'Sample Works', 'Data Co-op', 'Montreal, QC', 'https://example.invalid/jobs/2', '2026-09-18T00:00:00Z');
