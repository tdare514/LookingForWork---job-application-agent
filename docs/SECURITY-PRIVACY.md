# Security and privacy baseline

This document is an engineering baseline for the hackathon. It is not a legal opinion. Before connecting a real inbox, resume, or application account, complete a privacy review for the jurisdictions and providers involved.

## Non-negotiable rules

- Use synthetic fixtures for the demo.
- Never commit resumes, email exports, phone numbers, addresses, OAuth tokens, API keys, screenshots containing personal data, or provider credentials.
- Never put raw resume text, raw email bodies, access tokens, or authorization headers in logs, traces, prompts used for debugging, or GitHub issues.
- Never let external content instruct the agent to call a tool, reveal secrets, change policy, or submit an application.
- Never submit an application or send an email without an explicit, fresh, exact approval.
- Never invent a qualification, credential, employer, date, metric, or work authorization claim.
- Never use arbitrary URL fetching or browser automation in the MVP.

## Data classification

| Data | Classification | MVP handling | Cloud target |
| --- | --- | --- | --- |
| Synthetic job fixture | Public/demo | Git-tracked | Git-tracked |
| Public job metadata | Low sensitivity | Store normalized fields + provenance | DynamoDB |
| Candidate skills/preferences | Personal | Synthetic only until controls exist | Encrypted partitioned store |
| Master resume/artifacts | Sensitive personal | Local synthetic fixture | Private encrypted S3 object |
| Inbox messages | Sensitive personal | Seeded synthetic messages | Narrow OAuth scope + encrypted storage |
| OAuth/access tokens | Secret | Never stored in app DB or repo | Secrets Manager/token provider |
| Audit events | Sensitive operational | Redacted | CloudWatch + restricted audit store |

## Threats and controls

### Prompt injection in jobs or email

External text must be enclosed and labeled as untrusted data. The extractor may quote it, but must not obey instructions in it. Strip active content where possible, cap input size, reject unexpected tool-call fields, and validate the model output against a schema. No action tool receives raw source content as executable instructions.

### Credential and secret leakage

Use environment variables only for local development and provide .env.example with placeholders. Use AWS Secrets Manager or an approved token service in cloud mode. Grant separate, least-privilege roles for model access, persistence, and provider adapters. Rotate and revoke tokens. Add secret scanning to CI.

### PII exposure

Redact email addresses, phone numbers, street addresses, tokens, authorization headers, and full resume/email bodies before logs or traces. Log record IDs, hashes, field names, and counts instead of content. Review screenshots and demo recordings before publishing them.

### False or unsafe applications

Keep application submission disabled in the MVP. A resume/artifact proposal must show a diff and source references. The UI must display the destination, payload summary, and any unsupported claims before approval. Approval must bind to a payload hash and expire. The action adapter must be idempotent and fail closed.

### SSRF, malicious files, and untrusted URLs

Use an explicit source allowlist and URL parser. Do not fetch arbitrary URLs, follow redirects blindly, execute downloaded files, or enable a browser/shell tool in the MVP. Limit file types and sizes for any future resume upload; scan before parsing.

### Cross-user data leakage

Every record must be scoped by candidate/user ID at the repository boundary. Add authorization tests for reads, writes, artifacts, timeline events, and approvals. Never trust a model-provided user ID. For cloud storage, use partition keys, IAM conditions, and encryption.

### Replay and duplicate actions

Accept an idempotency key for ingestion and actions. Store source hashes and payload hashes. Replayed requests may return the previous result but must not create a second application, email, reminder, or timeline event.

## Privacy lifecycle

1. Collect only the candidate and job information needed for matching and tracking.
2. Explain why each source is connected and what the agent will do with it.
3. Keep raw source content separate from derived records; retain excerpts only when needed for explanation.
4. Provide a delete/export path before live use.
5. Make retention configurable and document the default before collecting real data.
6. On disconnect or deletion, revoke provider tokens and remove stored source/artifact data according to the documented retention policy.
7. Keep an append-only audit trail of security-relevant actions, with redacted payload summaries.

## Provider permissions

Start with no live provider access. When live Gmail is added:

- request the narrowest read/draft scopes possible;
- display the account and scopes before consent;
- store tokens outside the application database;
- allow disconnect/revoke;
- do not send mail by default.

For job sources, use approved public APIs, feeds, or pages where permitted. Respect provider terms, robots directives, rate limits, and deletion requests. Do not build credentialed job-board automation for the hackathon.

## CI and repository checks

The security issue should add:

- secret scanning;
- dependency audit;
- .env* and credential-path checks;
- PII redaction unit tests;
- prompt-injection fixtures;
- authorization/state-transition tests;
- a check that demo fixtures are synthetic;
- a documented incident/reporting path in [SECURITY.md](../SECURITY.md).

## Launch gate for real data

Do not connect real data until all of the following are true:

- authenticated access and candidate scoping are implemented;
- secrets are in a managed secret store;
- logs and traces are demonstrably redacted;
- delete/export and disconnect behavior are tested;
- approval-gated actions are enforced server-side;
- source terms and provider scopes are reviewed;
- a privacy notice and retention decision are documented;
- end-to-end tests cover duplicate, replay, prompt injection, and unauthorized access.
