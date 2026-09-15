# Delivery roadmap

## Product outcome

For a candidate targeting January–April 2027 roles, LookingForWork should answer:

> Which opportunities are worth my time, why do they fit, what should I change before applying, and what happens next?

The agent is successful when a judge can follow one opportunity from source evidence to match explanation, resume suggestion, tracked application, and an approval-gated next action without trusting an opaque model response.

## Scope decisions

### Must ship

- Public repository with a clear README and MIT license decision.
- TypeScript agent using Strands with multiple specialists or a non-trivial graph/workflow.
- AgentCore Runtime deployment or a documented, reproducible deployment path.
- Seeded Gmail-like messages and seeded job postings; live Gmail is optional for the demo.
- Typed persistent records for jobs, matches, resume artifacts, applications, approvals, and timeline events.
- Evidence-backed extraction and matching.
- Dashboard with overview, job/application detail, and timeline.
- One safe action, such as drafting a follow-up email or creating a reminder, behind approval.
- Tests for state transitions, matching, redaction, prompt injection handling, and duplicate ingestion.
- A five-minute demo that works without live credentials.

### Explicitly out of scope for the hackathon

- Unattended application submission.
- Automatic sending of emails.
- Scraping authenticated job boards or bypassing robots.txt, access controls, rate limits, or terms of service.
- Storing job-board passwords or raw OAuth tokens in the application database.
- Claiming skills or experience that are not present in the source resume.
- Production multi-tenancy, billing, or a legal/compliance certification.

## Five-day critical path

| Phase | Target window | Owner focus | Exit criterion |
| --- | --- | --- | --- |
| 0. Foundation | First 4–6 hours | David + tdare514 | Local agent, typed contracts, test command, CI, and seeded mode run |
| 1. Ingestion | Day 1 | Member 3 | Five synthetic jobs/messages become normalized, deduplicated records with evidence |
| 2. Matching and artifacts | Days 1–2 | Member 4 | Candidate profile produces ranked matches, reasons, gaps, and a truthful resume diff |
| 3. Tracker and review UI | Days 2–3 | Member 5 | A user can inspect a job, review an artifact, update application status, and see a timeline |
| 4. Policy and action gate | Day 3 | David + Member 5 | Draft/reminder action is blocked until the user approves a visible proposal |
| 5. Cloud and demo hardening | Days 4–5 | David + tdare514 | AgentCore path works, logs are redacted, end-to-end demo is repeatable |

## Phase 0 — Foundation

Deliver:

- TypeScript workspace with one install/test/lint command.
- Local entrypoint that accepts a seeded run request and returns a typed result.
- Domain schemas and a state-machine module before model calls are added.
- Prompt/model adapters behind interfaces so tests can run with fixtures or a stub model.
- CI on every pull request.
- .env.example, .gitignore, and a rule that secrets and personal data never enter the repository.

Definition of done:

- A new teammate can clone the repo, install dependencies, run tests, and execute the seeded flow without AWS credentials.
- The runtime interface has a health check and an invocation endpoint compatible with the selected AgentCore deployment path.

## Phase 1 — Ingestion and evidence

Deliver:

- Seed adapter for job postings and Gmail-like messages.
- Normalization into a canonical Job record.
- Stable source identifiers and content hashes for idempotency.
- Extraction of title, company, location, work mode, employment type, dates, requirements, preferred qualifications, and source URL.
- Evidence objects that point back to a source and excerpt.
- Rejection or quarantine of malformed, stale, duplicate, or unsupported records.

Definition of done:

- Replaying the same fixture does not create duplicates.
- Every extracted field shown in the UI can be traced to a source excerpt or is marked inferred/unknown.
- The extractor treats content from a job or email as data, never as instructions to call tools.

## Phase 2 — Matching and application artifacts

Deliver:

- CandidateProfile with target roles, skills, education, location/work-mode preferences, eligibility, and January–April 2027 availability.
- Deterministic hard filters before semantic scoring.
- Explainable score with reason codes, matched evidence, gaps, confidence, model version, and timestamp.
- Reviewable resume variant or change set grounded in the master resume.
- Optional cover-letter/follow-up draft grounded in the job and candidate evidence.
- Prompt/evaluation fixtures for strong fit, partial fit, hard-filter failure, missing data, and adversarial instructions.

Definition of done:

- A low score can be explained without displaying hidden chain-of-thought.
- The system distinguishes “not found in source” from “candidate does not have this.”
- Generated artifacts show a diff and require human review before they can be associated with a ready-to-submit application.

## Phase 3 — Tracking and review experience

Deliver:

- Application status state machine:
  DISCOVERED → REVIEW → READY_TO_APPLY → DRAFTED → SUBMITTED → INTERVIEW → OFFER
  with REJECTED, WITHDRAWN, and CLOSED terminal paths.
- List views for recommended jobs, saved jobs, active applications, deadlines, and follow-ups.
- Job/application detail page with score reasons, evidence, artifact versions, notes, and next action.
- Timeline events for ingestion, score changes, artifact generation, user approvals, status changes, and outcomes.
- Search/filter by role, company, status, deadline, score, and work mode.

Definition of done:

- A user can move an opportunity from discovery to submitted only through an explicit UI approval at the submission boundary.
- Repeated agent runs append or update idempotently rather than duplicating timeline events.
- Every external-looking action has actor, timestamp, target, payload summary, and approval record.

## Phase 4 — Policy and safe actions

Deliver:

- Central policy module used by every action tool.
- Risk classes: read-only, draft, reversible write, external send/submit.
- Approval record with exact action preview, destination, expiry, approver, and idempotency key.
- Safe demo action: create a draft follow-up email or a reminder; do not send it automatically.
- Fail-closed behavior when approval, destination, consent, or required evidence is missing.
- Redacted audit logs.

Definition of done:

- Direct calls to the action function without an approval token fail.
- Approval is bound to the exact destination and payload hash, not just a general conversation.
- Replaying an approved request cannot create duplicate actions.

## Phase 5 — Cloud, observability, and demo

Deliver:

- AgentCore Runtime deployment configuration and a recorded deployment/invocation procedure.
- Least-privilege IAM for model calls, persistence, and secrets.
- CloudWatch/AgentCore traces and structured logs with PII redaction.
- Synthetic demo data and a reset command.
- End-to-end smoke test and a five-minute demo script.
- Failure states in the UI: source unavailable, model timeout, low confidence, approval expired, and duplicate request.

Demo sequence:

1. Load the candidate profile and master resume fixture.
2. Ingest five job postings and one recruiter-style message.
3. Show the ranked results and open one match.
4. Trace the score to evidence and identify one gap.
5. Generate a resume diff and review the truthfulness warnings.
6. Save the opportunity and show the application timeline.
7. Ask for a follow-up reminder/draft.
8. Show the blocked action, approve it, and show the audit event.
9. Show the AgentCore trace/log view and the security boundary.

## Post-hackathon stretch

Prioritize only after the seeded flow is stable:

- Live Gmail with narrow read-only scopes and explicit consent.
- Approved public job-source adapters with rate limits and provenance.
- Calendar reminders and email drafts through connected providers.
- Browser-assisted form filling with per-application review; never unattended submission.
- Notifications, semantic memory, user accounts, deletion/export workflows, and multi-tenant isolation.
- Evaluation dashboard for precision@k, evidence coverage, artifact edit rate, duplicate rate, and approval bypass tests.

## Issue order

Open and work these in order, while parallelizing the independent tracks after Foundation:

1. Scaffold TypeScript workspace, CI, and runtime contract.
2. Define domain schemas and application state machine.
3. Build seeded job and inbox ingestion adapter.
4. Implement explainable matching specialist.
5. Implement reviewable resume tailoring.
6. Build application tracker and timeline dashboard.
7. Add security/privacy baseline and redaction tests.
8. Add approval-gated action layer.
9. Deploy and observe the agent on AgentCore Runtime.
10. Integrate the end-to-end demo and QA checklist.
