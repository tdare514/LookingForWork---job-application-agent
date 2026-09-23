CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  company TEXT NOT NULL,
  title TEXT NOT NULL,
  location TEXT NOT NULL,
  url TEXT NOT NULL,
  deadline TEXT,
  status TEXT NOT NULL DEFAULT 'new',
  notes TEXT,
  next_action TEXT,
  next_action_date TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- Synthetic examples only. Never put personal dossier or live application data here.
INSERT OR IGNORE INTO jobs (id, company, title, location, url, deadline, status, notes, next_action, next_action_date, created_at, updated_at) VALUES
  ('synthetic-001', 'Example North', 'Operations Analyst', 'Toronto, ON', 'https://example.invalid/jobs/1', '2026-09-20', 'ready', 'Synthetic fixture: review the tailored package.', 'Review application package', '2026-09-19', '2026-09-19T00:00:00Z', '2026-09-19T00:00:00Z'),
  ('synthetic-002', 'Sample Works', 'Data Co-op', 'Montreal, QC', 'https://example.invalid/jobs/2', '2026-10-02', 'pursue', 'Synthetic fixture: compare requirements with the resume source.', 'Read posting and capture requirements', '2026-09-22', '2026-09-18T00:00:00Z', '2026-09-18T00:00:00Z');
