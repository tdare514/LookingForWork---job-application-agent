# Core architecture

## Design principles

1. Keep deterministic policy and state transitions outside the model.
2. Treat job postings, emails, URLs, and generated text as untrusted until validated.
3. Make every model result typed, evidence-backed, versioned, and reviewable.
4. Keep the local seeded mode feature-complete enough to run the demo without credentials.
5. Put all external side effects behind one policy and approval boundary.
6. Store the minimum data needed to explain a match and maintain an application history.

## System flow

The high-level flow is:

Candidate profile + resume and seeded/live sources
→ ingestion adapters
→ normalization and evidence extraction
→ specialist workflow
→ policy validation and persistence
→ dashboard and approval-gated actions

Suggested implementation topology:

    apps/web
       |
       v
    agent API / invocation adapter
       |
       v
    Strands orchestrator
       |
       +--> source and extraction specialist
       +--> matching specialist
       +--> resume/artifact specialist
       +--> catch-up and next-action specialist
       |
       v
    policy + repositories
       |
       +--> local seeded store
       +--> DynamoDB records / S3 private artifacts
       +--> CloudWatch / AgentCore observability

The specialists may be implemented as Strands agents or typed workflow nodes. They must communicate through schemas defined in packages/domain, not free-form text passed directly to the UI or an action tool.

## Responsibility of each layer

### Web dashboard

- Candidate profile editing.
- Job, match, artifact, and application views.
- Evidence display.
- Status changes and approval UI.
- Never holds AWS long-lived credentials.
- Never decides whether an action is permitted; it requests a policy decision.

### Agent API and orchestrator

- Accepts a request with a user/session identifier and idempotency key.
- Loads only the candidate's authorized context.
- Routes work to specialists.
- Validates every specialist result against a schema.
- Emits trace IDs and structured activity events.
- Returns a concise result plus evidence references, not hidden reasoning.

### Specialists

Use narrow prompts and narrow inputs:

- Ingestion/extraction: source content → canonical Job/Message + evidence.
- Matching: CandidateProfile + Job → score, reasons, gaps, evidence refs.
- Artifact: master resume + Job + approved match → proposed diff and draft.
- Next-action/catch-up: existing records → prioritized tasks and safe draft proposals.

A specialist cannot grant itself a new tool, change its own permissions, or bypass the policy layer.

### Policy and action layer

All writes pass through one module:

- classify the action;
- validate authorization and consent;
- validate destination and payload;
- require evidence where applicable;
- require explicit approval for external send/submit;
- enforce an idempotency key;
- record an audit event;
- execute only the allowlisted adapter.

The first demo action should be a draft follow-up email or reminder. Submission is a separate high-risk action and remains disabled by default.

## Domain model

| Record | Purpose | Sensitive fields |
| --- | --- | --- |
| CandidateProfile | Search preferences and verified background | Contact details, eligibility |
| Resume | Master resume metadata and versioned source artifact | Full resume content |
| Job | Normalized opportunity | Usually low sensitivity; source terms still apply |
| SourceEvidence | Provenance for extracted fields and match reasons | May include quoted source text |
| JobMatch | Score, filters, reasons, gaps, confidence, model version | May reference resume evidence |
| Artifact | Resume diff, cover letter, or draft | Candidate content and PII |
| Application | Status, deadlines, notes, selected artifact | Contact/application details |
| Approval | Exact approved action, actor, expiry, payload hash | Audit/security record |
| TimelineEvent | Append-only history of changes and actions | May contain summaries, never raw secrets |

For cloud mode, keep structured records in a partitioned store such as DynamoDB and private artifact blobs in encrypted S3. Do not place complete resumes or email bodies in logs. Local mode may use a file/SQLite repository, but must use the same interfaces and redaction rules.

## Match calculation

The first implementation should be explainable and configurable:

1. Hard filters: search window, location/work mode, eligibility, job type, closing date, and required constraints.
2. Weighted score for records that pass hard filters:
   - 40% skill and responsibility overlap.
   - 20% target-role alignment.
   - 15% location and work-mode fit.
   - 15% start-window and availability fit.
   - 10% education/experience evidence.
3. Model-generated reasons and gaps are accepted only when linked to source evidence or marked unknown.
4. Missing data lowers confidence; it must not be silently treated as a mismatch.
5. Store the scoring configuration and model/prompt version with every match so results can be reproduced.

The weights are an MVP default, not a claim that the score predicts hiring outcomes.

## Application state and permissions

| Transition | Allowed actor | Required condition |
| --- | --- | --- |
| DISCOVERED → REVIEW | Agent | Valid normalized Job |
| REVIEW → READY_TO_APPLY | User | User reviewed match and evidence |
| READY_TO_APPLY → DRAFTED | Agent | Approved artifact generation request |
| DRAFTED → SUBMITTED | User only | Exact application reviewed and explicitly confirmed |
| SUBMITTED → INTERVIEW/OFFER/REJECTED | User or authorized source adapter | Source event or user update |
| Any active state → WITHDRAWN/CLOSED | User | Confirmation and timeline event |

The agent may recommend a transition, but it may not impersonate the user at the submission boundary.

## Recommended implementation boundaries

    packages/domain
      schemas, enums, state transitions, validation errors

    packages/ingestion
      SourceAdapter, JobNormalizer, EvidenceBuilder, dedupe

    packages/matching
      hardFilters, scoreMatch, reasonCodes, evaluation fixtures

    packages/artifacts
      resume parser, change-set generator, truthfulness checks

    packages/persistence
      CandidateRepository, JobRepository, MatchRepository,
      ArtifactRepository, ApplicationRepository, TimelineRepository

    packages/policy
      action registry, approval verifier, payload hashing, redaction

    apps/agent
      Strands workflow, model adapter, /ping, /invocations

    apps/web
      dashboard and approval experience

    fixtures
      candidate, resume, jobs, inbox, expected outputs

    infra
      AgentCore, IAM, environment configuration, deployment notes

## Failure handling

Every run should return a typed outcome:

- success with result and evidence;
- partial success with failed source/specialist details;
- blocked with a policy/approval reason;
- retryable failure with a trace ID;
- invalid input with field-level errors.

Persist enough metadata to debug a run without retaining raw PII in logs.
