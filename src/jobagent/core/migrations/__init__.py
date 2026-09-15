"""Forward-only schema migrations.

Each migration is (version, name, SQL). They are applied in order on startup and
never edited after they ship -- a change gets a new migration. Only PII columns
registered in ``jobagent.core.pii`` may be added.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str


M0001 = Migration(
    1,
    "initial_schema",
    """
    -- Canonical job record. One row per real role, many sightings.
    CREATE TABLE jobs (
        id              INTEGER PRIMARY KEY,
        fingerprint     TEXT NOT NULL UNIQUE,
        title           TEXT NOT NULL,
        company         TEXT NOT NULL,
        company_norm    TEXT NOT NULL,
        location        TEXT,
        work_arrangement TEXT,
        seniority       TEXT,
        compensation_min INTEGER,
        compensation_max INTEGER,
        currency        TEXT,
        description     TEXT,
        posted_at       TEXT,
        first_seen_at   TEXT NOT NULL,
        last_seen_at    TEXT NOT NULL
    );
    CREATE INDEX idx_jobs_company_norm ON jobs(company_norm);
    CREATE INDEX idx_jobs_last_seen ON jobs(last_seen_at);

    -- A repost is a sighting, not a new job. Sighting count is signal.
    CREATE TABLE job_sightings (
        id          INTEGER PRIMARY KEY,
        job_id      INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
        source      TEXT NOT NULL,
        source_id   TEXT NOT NULL,
        url         TEXT,
        seen_at     TEXT NOT NULL,
        UNIQUE(source, source_id, seen_at)
    );
    CREATE INDEX idx_sightings_job ON job_sightings(job_id);

    -- Retained 30 days so a mapping bug is fixable without re-fetching.
    CREATE TABLE raw_payloads (
        id          INTEGER PRIMARY KEY,
        source      TEXT NOT NULL,
        source_id   TEXT NOT NULL,
        body        TEXT NOT NULL,
        fetched_at  TEXT NOT NULL
    );
    CREATE INDEX idx_raw_fetched ON raw_payloads(fetched_at);

    CREATE TABLE job_requirements (
        id              INTEGER PRIMARY KEY,
        job_id          INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
        payload         TEXT NOT NULL,
        prompt_version  TEXT NOT NULL,
        extracted_at    TEXT NOT NULL
    );
    CREATE INDEX idx_requirements_job ON job_requirements(job_id);

    -- Scores keep their decomposition. "Why is this ranked 7th" is a query.
    CREATE TABLE scores (
        id          INTEGER PRIMARY KEY,
        job_id      INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
        total       REAL NOT NULL,
        components  TEXT NOT NULL,
        filtered    INTEGER NOT NULL DEFAULT 0,
        filter_reason TEXT,
        scored_at   TEXT NOT NULL
    );
    CREATE INDEX idx_scores_job ON scores(job_id);
    CREATE INDEX idx_scores_total ON scores(total DESC);

    CREATE TABLE profile (
        id          INTEGER PRIMARY KEY CHECK (id = 1),
        payload     TEXT NOT NULL,
        version     INTEGER NOT NULL,
        updated_at  TEXT NOT NULL
    );

    CREATE TABLE resume (
        id          INTEGER PRIMARY KEY CHECK (id = 1),
        payload     TEXT NOT NULL,
        version     INTEGER NOT NULL,
        updated_at  TEXT NOT NULL
    );

    CREATE TABLE applications (
        id          INTEGER PRIMARY KEY,
        job_id      INTEGER NOT NULL REFERENCES jobs(id),
        state       TEXT NOT NULL,
        notes       TEXT,
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    );
    CREATE INDEX idx_applications_state ON applications(state);

    CREATE TABLE application_transitions (
        id              INTEGER PRIMARY KEY,
        application_id  INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
        from_state      TEXT,
        to_state        TEXT NOT NULL,
        reason          TEXT,
        occurred_at     TEXT NOT NULL
    );
    CREATE INDEX idx_transitions_app ON application_transitions(application_id);

    CREATE TABLE documents (
        id              INTEGER PRIMARY KEY,
        application_id  INTEGER REFERENCES applications(id) ON DELETE CASCADE,
        kind            TEXT NOT NULL,
        path            TEXT NOT NULL,
        sha256          TEXT NOT NULL,
        approved        INTEGER NOT NULL DEFAULT 0,
        created_at      TEXT NOT NULL
    );
    CREATE INDEX idx_documents_app ON documents(application_id);

    -- Append-only. The artifact that makes the approval gate auditable.
    CREATE TABLE audit_log (
        id          INTEGER PRIMARY KEY,
        action      TEXT NOT NULL,
        detail      TEXT NOT NULL,
        occurred_at TEXT NOT NULL
    );
    CREATE INDEX idx_audit_occurred ON audit_log(occurred_at);
    """,
)


M0002 = Migration(
    2,
    "board_state",
    """
    -- The board is the product. One row per opportunity, carrying its own state,
    -- so a personal tracker does not need a join to answer "where am I with BMO".
    ALTER TABLE jobs ADD COLUMN url TEXT;
    ALTER TABLE jobs ADD COLUMN state TEXT NOT NULL DEFAULT 'new';
    ALTER TABLE jobs ADD COLUMN deadline TEXT;
    ALTER TABLE jobs ADD COLUMN notes TEXT;
    ALTER TABLE jobs ADD COLUMN state_changed_at TEXT;
    CREATE INDEX idx_jobs_state ON jobs(state);
    """,
)


M0003 = Migration(
    3,
    "canonical_dedupe_keys",
    """
    -- Normalized forms of the three fields de-duplication compares (#28). Stored
    -- rather than computed per query so the index below is usable, and so a
    -- change to the normalization rules is visible as a data change.
    ALTER TABLE jobs ADD COLUMN title_norm    TEXT NOT NULL DEFAULT '';
    ALTER TABLE jobs ADD COLUMN location_norm TEXT NOT NULL DEFAULT '';

    -- Coarse identity: normalized company, title and city. Deliberately NOT
    -- UNIQUE, unlike `fingerprint`. A unique constraint here would mean a
    -- migration that silently merges rows the user already has on their board,
    -- and merging someone's tracked applications is not a thing a schema change
    -- should do quietly. It is consulted before an insert instead, so duplicates
    -- are never created and existing rows are never destroyed.
    ALTER TABLE jobs ADD COLUMN dedupe_key    TEXT NOT NULL DEFAULT '';
    CREATE INDEX idx_jobs_dedupe ON jobs(dedupe_key);
    CREATE INDEX idx_jobs_company_title ON jobs(company_norm, title_norm);
    """,
)


MIGRATIONS: tuple[Migration, ...] = (M0001, M0002, M0003)
