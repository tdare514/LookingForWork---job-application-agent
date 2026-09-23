-- Forward-only: 0001-0003 may already be applied to a dev database.
--
-- notes is free text that routinely names recruiters and internal contacts. It
-- is CRITICAL and NOWHERE in jobagent.core.pii, so it has no place off-machine.
ALTER TABLE jobs DROP COLUMN notes;

-- The hosted status vocabulary now matches the local board's states, so a row
-- round-trips. "pursue" was the hosted name for a triaged-in row; "closed" had
-- no local meaning and is taken as a skip.
UPDATE jobs SET status = 'ready' WHERE status = 'pursue';
UPDATE jobs SET status = 'skipped' WHERE status = 'closed';
