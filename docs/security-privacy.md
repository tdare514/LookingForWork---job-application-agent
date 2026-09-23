# Security and privacy

This system holds a complete dossier on one person: employment history, contact
details, compensation expectations, immigration status, and a record of every
company they approached while employed elsewhere. The last item is the one
people underestimate. A leaked application history is a career event, not an
inconvenience.

The controls below are sized for that, not for a hobby script.

## Threat model

**Assets**
- Identity and contact PII (name, address, phone, email).
- Employment and education history.
- Compensation expectations and current compensation.
- Immigration and work-authorization status.
- Application history — which companies, when, at what stage. Highest
  sensitivity: disclosure can cost the user their current job.
- Credentials: mail access tokens, job-site sessions, model API keys.

**Adversaries and scenarios**
| Threat | Vector | Control |
| --- | --- | --- |
| Device compromise or theft | Local disk read | Full-disk encryption assumed; no plaintext credentials at rest; no secrets in the DB |
| Credential leak | Secret committed to git, or logged | Secrets from keychain/env only; secret scanning in CI; redaction at the log boundary |
| Accidental publication | Application history pushed to a public repo | Data directory outside the repo; `.gitignore` covers artifacts; CI check for PII-shaped content |
| Third-party exposure | PII sent to model or job-site APIs | Minimization at the LLM boundary; per-call purpose logging; no compensation or immigration data in prompts unless the task requires it |
| Supply chain | Malicious dependency reading the data directory | Pinned dependencies with hashes; dependency audit in CI; minimal dependency surface |
| Snapshot exposure | Phone snapshot readable by anyone who finds the Pages URL | Cloudflare Access login in front of the project; allowlisted fields only (ADR 0009); `snapshot.json` gitignored and refused by the pre-commit hook |
| Hosted tracker write path (proposed, ADR 0010) | A forged or stale write to the D1 copy, or a critical field gaining an off-machine copy | Access, then an owner-only GitHub session, then same-origin CSRF on writes; optimistic versions, stale writes refused; field allowlist enforced on write and checked against the registry by `tests/test_cloudflare_contract.py`. Synthetic data only until 0010 is accepted |
| Unauthorized outbound action | Agent submits an application the user never saw | Structural approval gate; audit log; no submission code path without a recorded approval |
| Account lockout or ToS action | Aggressive automation against a job site | Central rate limiting; identifiable user agent; per-source terms compliance |

**Out of scope:** a compromised OS, a malicious keychain, and coercion of the
user. Also out of scope: protecting against the job sites themselves, which
legitimately receive what the user chooses to send.

## Accepted risks

Written down rather than pretended away:
- Model providers receive resume content for tailoring. Minimized, but real.
- Job sites receive the application. That is the purpose of the system.
- A user who disables the approval gate by editing the code can do so. The gate
  defends against agent error, not against its owner.
- Cloudflare receives company names, titles and application status in the phone
  snapshot (ADR 0009). It sits behind an Access login, but Cloudflare can read
  what is stored there, and the login is the only thing between that file and
  anyone else. `jobs.state` was downgraded from critical to permit this; the
  risk was accepted, not reassessed.

## PII inventory

Every stored field is registered with: what it is, why it is needed, where it
may be sent, and how long it is kept. The inventory is a tracked artifact, not
a comment in the schema — it is what makes the retention and purge work
verifiable.

Retention defaults:
| Category | Retention |
| --- | --- |
| Profile and resume source of truth | Until deleted by the user |
| Job postings | 180 days after last sighting |
| Generated drafts, unapproved | 30 days |
| Application records | Until deleted by the user |
| Audit log | 1 year |
| Raw fetched payloads | 30 days |

## Controls

**Secrets.** OS keychain first, environment second, nothing else. No secret in a
config file, the database, or a log line. Redaction happens at the logging
boundary so a new call site cannot leak by omission.

**Data location.** The data directory lives outside the working tree by default.
`.gitignore` covers generated documents and local databases. A CI check
looks for PII-shaped content in tracked files.

**Transport.** TLS with verification everywhere. No option to disable it.

**LLM boundary.** One client, one redaction policy. Prompts carry the minimum
needed for the task. Compensation figures and immigration status are excluded by
default and included only where the task cannot be done without them — with the
inclusion logged.

**Outbound policy.** Per-source allowlist. Central rate limiting. Honest user
agent that identifies the tool. `robots.txt` respected. No automated
circumvention of bot protection, and no login on a site where the user has not
explicitly authorized it. If a source's terms forbid automated access, the
adapter is not written.

**Human-in-the-loop.** The approval gate is architectural. There is no code path
from a drafted package to an outbound submission that does not pass through a
recorded human approval, and there is a test asserting that.

**Supply chain.** Pinned, hash-verified dependencies. Dependency audit and
secret scanning in CI, blocking on findings. New dependencies justified in the
PR that adds them.

**Deletion.** `export` produces a portable archive of everything. `purge`
removes stored PII, including generated documents and raw payloads, and is
verified by a test that asserts nothing recoverable remains.

## Review points

- End of Phase 1: threat model and PII inventory reviewed before real data is
  entered.
- End of Phase 3: review of the LLM boundary and generated-document handling.
- End of Phase 4: full review of the complete surface, with findings resolved or
  accepted in writing.
