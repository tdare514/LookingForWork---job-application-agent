# Architecture

## Shape

A local, single-user application. No server, no multi-tenancy, no hosted state.
The agent runs on demand or on a schedule, does a unit of work, writes to a
local database, and exits.

```
                  ┌────────────────────────────────────────────┐
                  │                  CLI                       │
                  │  run · shortlist · draft · review · track   │
                  └───────────────────┬────────────────────────┘
                                      │
              ┌───────────────────────┼───────────────────────┐
              │                       │                       │
     ┌────────▼────────┐    ┌─────────▼────────┐    ┌─────────▼────────┐
     │   Discovery     │    │    Matching      │    │   Application    │
     │  source         │    │  extraction      │    │  tailoring       │
     │  adapters       │───▶│  scoring         │───▶│  rendering       │
     │  normalization  │    │  ranking         │    │  approval gate   │
     │  dedupe         │    │                  │    │                  │
     └────────┬────────┘    └─────────┬────────┘    └─────────┬────────┘
              │                       │                       │
              └───────────────────────┼───────────────────────┘
                                      │
                    ┌─────────────────▼──────────────────┐
                    │        Core services               │
                    │  profile · storage · secrets       │
                    │  audit log · rate limiter · LLM    │
                    └─────────────────┬──────────────────┘
                                      │
                    ┌─────────────────▼──────────────────┐
                    │  Local store (embedded relational  │
                    │  DB + generated documents on disk) │
                    └────────────────────────────────────┘
```

## Components

### Core services

**Profile.** The user's declared intent: target titles, seniority, must-haves,
deal-breakers, compensation floor, locations, work arrangement, visa status.
Validated on load. A malformed profile is a hard failure, not a warning — a
silently empty filter produces a shortlist of noise.

The YAML file is an import, not the store. `jobagent profile set` validates it
and writes the `profile` singleton; every filter and score reads the database.
That is what makes `schema_version` and its upgrade chain load-bearing: a
profile stored in September has to keep loading after the shape changes in
November, mid-search, without the user re-editing a file to find out.

Scoring weights live here rather than as constants, per
[job-matching](job-matching.md). `semantic_fit` is in the schema and refuses a
non-zero value: it needs an embedding model, a metered API is out of scope, and
no local backend has been decided (#31). A weight that silently does nothing
produces a score that looks complete.

**Storage.** One embedded relational database file. Forward-only migrations,
versioned in the repo, applied on startup. Generated documents live on disk
next to it, referenced by path. Rationale: a single file is trivially backed up
and trivially deleted, which the privacy model depends on.

**Secrets.** Credentials resolve from the OS keychain, falling back to
environment variables. Never read from a config file, never written to the
database, never logged. A secret that reaches the audit log is a bug with a
test.

**Audit log.** Append-only record of what the agent did: what it fetched, what
it scored, what it drafted, what a human approved, when. This is the artifact
that makes the human-in-the-loop guarantee auditable rather than aspirational.

**Rate limiter.** Enforced centrally and per source. An adapter cannot opt out;
it declares its limit and the framework applies it. Politeness that depends on
each adapter's author remembering is not politeness.

**LLM client.** One boundary for all model calls, so prompt inputs, token
spend, and redaction policy have a single place to live. Every call is logged
with its purpose; PII sent to a model is limited to what the task needs.

### Discovery

Adapters are the only component that touches the network for job data. Each
declares its source, its rate limit, its terms constraints, and a mapper to the
canonical schema. Adding a source means adding an adapter and nothing else.

De-duplication runs after normalization: the same role appears across sources
and is reposted over time. One job, many sightings, with the sighting history
preserved — a role reposted three times in six weeks is a signal.

### Matching

Two-stage. Hard filters first: company blocklist, visa requirement, seniority
distance, work arrangement, location, compensation floor, profile deal-breakers.
These are boolean and cheap, and they cut the candidate set before anything
expensive runs. A cut is stored with the rule that made it, never discarded, so
an over-eager filter is a query rather than a guess. Missing data always passes:
a posting silent on pay has not offered a low one.

Then a decomposed score over skill overlap, seniority fit, domain relevance and
freshness. Semantic fit is in the schema and carries no weight, per
[job-matching](job-matching.md).

Scores are stored with their components, each with the weight it carried and a
line on what it looked at. "Why is this ranked 7th" must be answerable from the
database, not from re-running the model. A component with nothing to judge on is
stored as unavailable and the remaining weights rescale, so a posting that has
not been fetched in detail is ranked on what is known rather than sunk for what
is not.

### Application

Tailoring reads the structured resume — the source of truth — and produces a
variant targeted at one posting. The constraint that shapes this component: the
output may select, reorder, and rephrase; it may not introduce a claim absent
from the source. A validation pass diffs generated content against the source of
truth and fails the package on an unsupported claim.

Rendering produces PDF and DOCX from the tailored structure. Layout is chosen
for machine readability first — columns, tables, and graphics defeat the
parsers that read these documents before a human does.

The approval gate is the last component before anything leaves the machine. It
presents the package with its diff, records approval or rejection with a reason,
and only then marks the application submittable.

### Tracking

One record per application with an explicit state machine. Transitions are
recorded with timestamps, which makes both "what is stale" and "where does the
funnel leak" queries rather than recollection.

## Data flow

1. Scheduled or manual run triggers discovery across enabled adapters.
2. Raw postings are normalized, de-duplicated, and persisted.
3. Extraction pulls structured requirements from the description text.
4. Hard filters cut the set; the scorer ranks what remains.
5. The shortlist is written and surfaced as a digest.
6. The user selects roles to pursue; tailoring drafts a package per role.
7. Validation checks the package against the resume source of truth.
8. The user approves or rejects at the gate.
9. Approved applications enter the tracker and the follow-up schedule.
10. Status changes — manual, or suggested from mail ingestion — advance the
    state machine and feed the funnel report.

## Boundaries

What this is not:
- Not a scraper that defeats bot protection or logs into sites on the user's
  behalf without authorization.
- Not an auto-submitter. The gate is structural, not a preference.
- Not a service. If it ever grows a server, that is a new threat model and a new
  architecture document.
