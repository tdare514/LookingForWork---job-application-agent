# Cloudflare companion implementation plan

## Scope and status

This is a plan for a separate, mobile-friendly companion to `jobagent`, not
evidence that a Cloudflare checkout, account, OAuth application, credentials,
account ID, or deployment already exists. The reported companion (a mobile
tracker, persistent database support, owner-only GitHub login, 16 new security
tests, and 439 existing tests) is not present in this checkout, so those counts
are unverified inputs rather than acceptance evidence.

The current application is intentionally local-first: one SQLite database,
generated documents beside it, an append-only audit log, registered PII fields,
and a structural human approval gate before anything is sent. Hosting a
companion changes the threat model and conflicts with the current rule that the
dossier stays on this machine. Implementation must therefore begin with an
explicit decision to permit a narrowly scoped hosted tracker; it must not
silently sync the local `profile`, `resume`, documents, or critical application
history.

### Hard budget constraint

The companion is **free-only**. It must operate within the Cloudflare free
allowances and free GitHub OAuth; no paid Cloudflare or third-party service may
be required, enabled, or silently incurred. Explicitly out of scope are paid
Workers usage, paid D1 usage, Workers AI, paid APIs, Queues, Pipelines, email
delivery, analytics, premium observability/logging, and custom-domain
registration or renewal costs. Use the provider's free default hostname and
plain request/audit tests instead of buying a domain or adding a paid
observability product.

Free-tier quotas and limits are configurable safeguards, not assumptions hidden
in code. Deployment configuration must declare the quota snapshot and
operator-selected ceilings for requests, D1 reads/writes/storage, body size,
sync batch size, sessions, and log volume. The Worker must reject work before a
configured ceiling is crossed, and the UI must show a bounded/rate-limited
failure rather than retrying indefinitely. The CI/deploy gate must fail closed
when configuration, a dependency, a binding, or an API requests a required
paid feature or plan: it must not deploy on a paid account, fall back to a paid
service, or treat an unknown billing/plan state as free. Recheck the current
provider quotas at deployment time and update the configuration and tests when
they change.

## Target architecture

### Runtime and delivery

- **Cloudflare Pages** serves the responsive web application/PWA shell. The
  first release should be a small tracker UI that works at phone widths and
  supports installable/offline read-only viewing of the last successful board
  snapshot.
- **Cloudflare Workers** provides the same-origin API, GitHub OAuth callback,
  session handling, authorization checks, input validation, optimistic
  concurrency, audit writes, and cache-control headers. The browser never calls
  D1 directly.
- **D1** is the persistent SQLite-compatible store for the explicitly approved
  companion subset. Use forward-only numbered migrations, foreign keys, indexes
  matching board queries, and UTC timestamps, mirroring the local storage
  discipline without pretending the databases are interchangeable.
- **Workers secrets** hold the GitHub OAuth client secret and session-signing
  material. Neither secret belongs in Pages assets, D1, logs, migrations, or
  test fixtures. The OAuth client ID and callback URL are configuration, not
  authorization.
- **No Workers AI, paid API, queues/pipelines, email, analytics, premium
  observability, automated application submission, job-site login, or crawler
  is in scope.** The companion links back to a posting and can record a
  human-entered state; it cannot submit an application.

### Data boundary

The hosted allowlist should initially contain only the minimum tracker data:

| Data | Hosted in first release | Reason |
| --- | --- | --- |
| Job ID, title, company, URL, location, deadline | Yes | Required to render the board |
| Board state, state reason, snooze date, notes | Explicit opt-in; default no for notes/reasons | These reveal the application history |
| Follow-up dates and transition timestamps | Explicit opt-in | Needed for the mobile tracker, but sensitive |
| Profile, resume, contact details, work authorization, compensation, drafts, generated documents | No | Dossier data remains local |
| Raw posting payloads, model prompts, OAuth tokens | No | Unnecessary retention and high-value leakage |
| Audit events | Minimal hosted security/audit subset only | Record sign-in, authorization, and state-change metadata; never copy local audit detail wholesale |

The sync contract must be allowlisted by field, not “serialize the job row.”
Critical fields remain local unless a later ADR approves hosted storage,
retention, export, and purge semantics. The hosted UI should make this boundary
visible (for example, “synced tracker data,” not “your full jobagent data”).

### Authentication and authorization

1. The browser starts `/auth/github`; the Worker generates and stores a
   short-lived OAuth state and PKCE verifier in an encrypted, HttpOnly,
   Secure, SameSite=Lax transaction cookie.
2. The callback verifies state, exchanges the code server-to-server, fetches
   the GitHub user identity over TLS, and discards the provider token after
   deriving the local identity. Provider access tokens are never stored.
3. The Worker compares an immutable configured GitHub numeric user ID
   (`OWNER_GITHUB_ID`) rather than trusting a mutable login name. Every API
   request requires a valid, unexpired, HttpOnly session cookie and an
   owner-ID match.
4. Unknown GitHub users receive a generic denial and no session. Do not create
   an account, row, or useful timing distinction for them.
5. Logout revokes the server-side session record and expires the cookie.
   Sessions are short-lived and rotated after login; CSRF protection covers all
   state-changing requests.

The authorization check belongs in the Worker route boundary and is repeated
by repository tests. UI hiding is not authorization. GitHub OAuth proves
identity, not ownership; the configured owner ID is the access policy.

### Request and safety boundaries

- Validate JSON against explicit schemas; reject unknown fields where practical,
  cap string lengths, and use parameterized D1 statements.
- Apply a narrow same-origin CORS policy (ideally no cross-origin API use),
  `Content-Security-Policy`, `frame-ancestors 'none'`, `Referrer-Policy`,
  `X-Content-Type-Options`, and `Cache-Control: no-store` to authenticated
  responses.
- Never put job notes, application state, OAuth codes, or PII in URLs,
  analytics, exceptions, or Worker logs. Log event type, request ID, and
  outcome only, with redaction at the boundary.
- Use idempotency keys for sync/import and version columns for updates. A stale
  mobile write must return `409`, not overwrite a newer local decision.
- Keep the human gate intact: a hosted “mark ready/applied” action is a
  tracker transition only. There is no endpoint that submits, uploads, or
  hands credentials to a job site.

## D1 schema and migration strategy

### Proposed hosted schema

Use a new hosted schema rather than pointing the local migration runner at D1:

- `schema_migrations(version, name, applied_at)`
- `owner_sessions(id, owner_github_id, created_at, expires_at, revoked_at)`
- `jobs(id, local_id, fingerprint, title, company, location, url, deadline,
  hosted_state, version, first_seen_at, last_seen_at, updated_at)`
- `job_transitions(id, job_id, from_state, to_state, reason, occurred_at,
  source, request_id)`
- `sync_cursors(id, device_id, last_exported_at, updated_at)`
- `security_audit(id, event, occurred_at, request_id, github_user_id,
  metadata_json)` (metadata is allowlisted and must not contain content)

`local_id` and `fingerprint` support reconciliation without assuming the local
SQLite integer IDs are globally authoritative. `version` enables conditional
writes. Foreign keys and indexes should cover `jobs(hosted_state, deadline)`,
`jobs(updated_at)`, `job_transitions(job_id, occurred_at)`, and
`owner_sessions(expires_at)`.

### Import and ongoing sync

1. Add a local export command that emits only the approved companion schema,
   with a manifest containing schema version, row counts, export timestamp, and
   a checksum; it must not include resume/profile/documents/raw payloads.
2. Authenticate before accepting an import. Upload over TLS directly to the
   Worker; do not stage the archive in Pages or log its body.
3. Worker validates the manifest, row limits, field lengths, fingerprints, and
   allowed state transitions inside one D1 transaction. Reject the entire batch
   on a validation error.
4. For later sync, exchange changes by cursor and `updated_at`; use
   idempotency keys and return conflicts for the user to resolve. Never infer a
   conflict by silently choosing “cloud wins.”
5. Export from D1 in the same allowlisted shape. Local import must preserve the
   local approval/audit semantics and must not mark anything submitted.

The first release can use an explicit “sync now” action. Background push,
offline mutation queues, and automatic bidirectional reconciliation should be
separate issues after the conflict model is proven.

### Retention, export, and purge

Hosted retention must be documented before real data is enabled: postings can
follow the local 180-day policy only if the hosted subset is covered, while
application history and tracker notes should remain until the owner deletes
them. Implement owner-only export and purge endpoints, verify row counts after
purge, revoke all sessions, and provide a D1 backup/deletion runbook. D1
backups, logs, caches, browser storage, and deployment artifacts must be
included in the deletion review; “deleted from the main table” is not enough.

## Test plan

The reported 16 security tests and 439 existing tests cannot be verified here.
The implementation should preserve the existing Python `make check` suite and
add a separately named Worker/UI suite. Tests must run without live GitHub or
Cloudflare credentials.

### Security and authorization

- OAuth state mismatch, expired state, PKCE mismatch, callback replay, denied
  provider response, and token non-persistence.
- Owner numeric ID allowed; wrong ID, changed login name, missing identity,
  revoked session, expired session, and logout denied on protected routes.
- Session cookie flags, rotation, fixation resistance, CSRF rejection, generic
  unknown-user response, and no sensitive values in logs/errors/URLs.
- Route-level authorization for every read and write, including direct API
  calls; D1 parameter binding and unknown-field rejection.
- XSS payloads in title/company/notes rendered as text; security headers;
  no-cache behavior; bounded request/body/string sizes; rate limiting.
- Hosted allowlist rejects profile/resume/contact/work-authorization fields,
  raw payloads, documents, secrets, and arbitrary JSON.
- Purge/export completeness, audit append-only behavior, and no submission
  endpoint or code path.

### Data and mobile behavior

- Forward migrations apply in order and are repeatable; foreign-key cascades
  are intentional; indexes support board queries.
- Import is atomic, idempotent, checksum-checked, and rejects malformed or
  over-limit batches without partial writes.
- Equal-version duplicate sync is harmless; stale writes return `409`;
  concurrent transitions preserve ordering and never skip the human gate.
- Responsive board smoke tests at phone and desktop viewports; keyboard and
  screen-reader labels; offline snapshot is read-only and clearly stale.
- Local round-trip fixtures prove exported tracker data can be imported without
  changing local state outside the allowlist.

### Verification gates

- Existing: `make check` and `python3 scripts/check_context.py`.
- New: Worker unit/integration tests against a local D1-compatible test
  database, browser smoke tests, migration tests, and dependency/secret scans.
- Pre-deployment: test OAuth with a dedicated non-production GitHub OAuth app,
  inspect the final bundle for secrets and PII, run a D1 backup/restore drill,
  and verify the owner-only denial path from a second GitHub account.
- No test may use the real owner’s resume, contact details, application
  history, OAuth secret, production database, or live job-site submission.

## Deployment prerequisites

1. Decide and record the hosted-data exception to ADR 0003 and update the
   threat model/PII registry before collecting real tracker data. The decision
   must name exactly which fields are permitted in D1.
2. Create a Cloudflare account/project and a dedicated Pages project plus
   Worker/D1 bindings. Record the account ID and production database ID only in
   repository-hosted configuration where appropriate; do not put credentials
   into this repository or this plan.
3. Create separate development and production D1 databases and separate
   GitHub OAuth apps. Configure exact callback URLs, allowed origin(s), and
   the immutable owner numeric ID. Store client secret and session secret with
   `wrangler secret put` or the deployment system’s secret store.
4. Use the provider free hostname (no custom-domain purchase or renewal);
   establish Pages preview policy, branch protection, CI environment
   protection, least-privilege Cloudflare tokens, free-tier quota configuration,
   D1 backup/restore and purge runbooks, and an incident/revocation procedure.
5. Confirm Cloudflare/GitHub terms, data residency/retention expectations, and
   whether the hosted subset is acceptable for the dossier threat model. Verify
   the account/plan and all bindings are free-only; an unknown billing state
   blocks deployment.
6. Deploy only synthetic fixtures first. Promote after OAuth denial, purge,
   migration, restore, headers, quota exhaustion, paid-feature detection, and
   no-submit tests pass in CI and a human has reviewed the final data boundary.

Nothing in this plan claims that any prerequisite, account, secret, database,
or deployment currently exists.

## Independent issues and agent-sized work

Each item is intended to be one small branch/PR. Dependencies are explicit so
the work can be parallelized without merging unrelated concerns.

| ID | Work | Depends on | Acceptance criteria |
| --- | --- | --- | --- |
| CF-01 | Hosted-data boundary and ADR | None | Proposed/superseding ADR names the allowed fields, threat model, retention, export/purge, and why local-only data stays local; no real data is enabled. |
| CF-02 | Cloudflare skeleton and CI | CF-01 | Pages app, Worker entry point, D1 binding, free-only plan/quota configuration, fail-closed paid-feature detection, dev/prod config shape, and CI test commands exist with placeholders only; no credentials or account IDs committed. |
| CF-03 | D1 migrations and repository | CF-01, CF-02 | Numbered migrations create the proposed tables/indexes; repository uses bound parameters, transactions, limits, and conditional versions; migration tests pass. |
| CF-04 | GitHub owner-only OAuth | CF-02 | State/PKCE callback, secure rotated sessions, immutable numeric owner check, logout/revocation, generic denial, and unit tests pass without live credentials. |
| CF-05 | Tracker API and security middleware | CF-03, CF-04 | Authenticated board reads/writes, validation, CSRF, headers, no-store, configurable free-tier ceilings, bounded rate limits, redacted logs, conflict responses, and route-level authorization tests pass. |
| CF-06 | Allowlisted local export/import | CF-03, CF-05 | Versioned manifest, atomic/idempotent import, export, checksum and size limits, rejection of forbidden PII, and round-trip fixtures pass. |
| CF-07 | Mobile tracker UI/PWA | CF-05 | Responsive board, accessible controls, read-only offline snapshot, stale indicator, conflict/error states, and browser smoke tests pass. |
| CF-08 | Hosted retention, export, and purge | CF-03, CF-05, CF-06 | Owner-only export/purge revokes sessions, verifies empty approved tables, documents backup/log deletion, and tests prove no recoverable hosted copy in the defined scope. |
| CF-09 | End-to-end security and deployment gate | CF-04, CF-05, CF-07, CF-08 | Synthetic end-to-end OAuth/denial/sync/purge run, quota-exhaustion and paid-feature fail-closed tests, secret and PII scans, D1 restore drill, preview controls, free-plan verification, and a reviewed no-submit proof pass before production. |

CF-01 is a human decision, not an implementation detail. CF-02–CF-06 can
proceed with synthetic data once that decision is recorded; CF-07 can proceed
against mocked API responses after CF-05; CF-08 and CF-09 must wait until the
actual retention and deployment surfaces are known. The reported test counts
should be reconciled in CF-09 against the checked-out companion, not copied
into project status as fact.
