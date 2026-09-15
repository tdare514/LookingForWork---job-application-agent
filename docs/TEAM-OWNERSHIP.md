# Team ownership

The team has five people. Until the other GitHub usernames are known, issues use role-based ownership rather than guessed assignees.

## Ownership map

| Person | Primary ownership | Concrete deliverables | Review partner |
| --- | --- | --- | --- |
| tdare514 | Product/integration lead | Candidate profile, fixture quality, acceptance criteria, cross-package integration, demo script, final QA | David |
| David | AWS/platform and agent lead | Strands orchestration, model adapter, AgentCore Runtime, IAM/deployment, runtime observability | tdare514 |
| Member 3 | Data/ingestion lead | Domain schemas, source adapters, normalization, evidence, dedupe, persistence interface | Member 4 |
| Member 4 | Matching/artifacts lead | Hard filters, explainable scoring, evaluation fixtures, resume diff, truthfulness checks | tdare514 |
| Member 5 | Experience/security lead | Dashboard, tracker/timeline, approval UI, redaction/security tests, demo polish | David |

Replace Member 3–5 with real names and GitHub handles once the team agrees. Do not assign an issue to a guessed GitHub account.

## Work allocation

### David

Own the critical path that can block the entire demo:

- establish the TypeScript workspace and local runtime contract;
- create the Strands specialist workflow;
- define Bedrock model configuration behind an adapter;
- prepare AgentCore Runtime deployment;
- configure least-privilege IAM and observability;
- review action-policy enforcement.

### tdare514

Own product truth and integration:

- define target roles and candidate-profile fields;
- curate synthetic January–April 2027 jobs and inbox messages;
- write acceptance scenarios and expected match explanations;
- integrate the specialists with the dashboard;
- run end-to-end QA and lead the five-minute demo;
- keep the scope cut line visible.

### Member 3

Own reliable data flow:

- define and validate domain records;
- build seeded job/message adapters;
- implement normalization, provenance, dedupe, and repository interfaces;
- provide fixtures for missing fields, stale jobs, duplicates, and malformed sources.

### Member 4

Own match quality:

- implement deterministic hard filters;
- implement the explainable scoring baseline;
- define evaluation cases and expected reasons/gaps;
- build resume-tailoring change sets grounded in source evidence;
- test that unsupported claims are rejected or flagged.

### Member 5

Own user trust and review:

- build the dashboard and application timeline;
- make evidence, score reasons, gaps, and diffs easy to inspect;
- implement approval UX and blocked-action states;
- add PII redaction, prompt-injection, and authorization tests;
- prepare demo screenshots using synthetic data only.

## Collaboration rules

- One issue, one accountable owner, one review partner.
- Branch names: feat/issue-number-short-name, fix/issue-number-short-name, or docs/issue-number-short-name.
- Every pull request links one issue and includes tests or an explicit reason no test applies.
- Keep interfaces small: changes to domain schemas require a short note in the PR and a reviewer from the consuming package.
- Merge only when the seeded end-to-end path still runs.
- Prefer a working vertical slice over isolated infrastructure.
- Use the daily sync to answer: what shipped, what is blocked, and what can be cut without breaking the demo.

## Dependency lanes

After Foundation and Domain are merged, work can proceed in parallel:

- David: AgentCore/runtime lane.
- Member 3: ingestion/persistence lane.
- Member 4: matching/artifacts lane.
- Member 5: web/policy/QA lane.
- tdare514: integration/fixtures/demo lane.

The integration lead should merge the first complete vertical slice before any stretch feature begins.
