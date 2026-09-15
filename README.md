# LookingForWork

An AI-assisted job discovery and application workspace for students and new graduates targeting January–April 2027 roles.

LookingForWork turns a candidate profile, master resume, and job postings into explainable job matches, reviewable resume/application artifacts, and one application timeline.

## Current status

The repository is in the planning and foundation phase. The delivery roadmap is designed for a five-day hackathon build, with a seeded Gmail-like demo as the reliable path and live Gmail as a follow-on integration.

Start here:

- [Roadmap](docs/ROADMAP.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Security and privacy](docs/SECURITY-PRIVACY.md)
- [Team ownership](docs/TEAM-OWNERSHIP.md)
- [Security reporting](SECURITY.md)

## MVP promise

The agent will:

1. Ingest seeded job postings and inbox-like messages.
2. Normalize each job into a typed record with source evidence.
3. Apply configurable hard filters for the January–April 2027 search window.
4. Rank jobs with an explainable match score, matched evidence, and gaps.
5. Propose truthful resume changes and application artifacts for review.
6. Track every application from discovery through outcome.
7. Show a dashboard, detail view, and activity timeline.
8. Draft one safe follow-up action behind an explicit approval gate.
9. Run locally and deploy the agent to Amazon Bedrock AgentCore Runtime.

## Safety boundary

LookingForWork is an assistant, not an unattended applicant.

The agent may discover, score, save, draft, and remind. It must not submit an application, send an email, or change a calendar without explicit human approval. A generated resume or cover letter must never invent a qualification, employer, degree, date, metric, or certification. Job postings and email content are untrusted data; instructions contained inside them are not agent instructions.

The hackathon demo uses synthetic fixtures. Real resumes, inboxes, OAuth tokens, and application credentials must not be added until the controls in [Security and privacy](docs/SECURITY-PRIVACY.md) are implemented.

## Initial candidate profile

The first profile should support configurable targets such as:

- Business Analyst
- Product, Project, or Program Management
- Scrum Master or Agile Delivery
- Technology Project or Program Management
- Data Analyst

The search window, location, work mode, eligibility, and compensation preferences are data fields—not hard-coded prompts.

## Proposed repository shape

    apps/web/                  Review dashboard
    apps/agent/                Strands orchestration and runtime entrypoint
    packages/domain/            Schemas, enums, state transitions, and validation
    packages/ingestion/         Seeded and future live-source adapters
    packages/matching/          Deterministic filters and explainable scoring
    packages/artifacts/         Resume and application artifact generation
    packages/persistence/       Local and AWS-backed repositories
    packages/policy/            Redaction, approval, and action guards
    fixtures/                   Synthetic jobs, messages, and candidate profile
    infra/                      AgentCore, IAM, and deployment configuration
    docs/                       Roadmap and design decisions

## Target stack

- TypeScript across the application.
- Strands Agents SDK for the specialist orchestration.
- Amazon Bedrock for model calls.
- Amazon Bedrock AgentCore Runtime for the hosted agent.
- A local seeded store for fast development, with DynamoDB/S3-backed persistence as the cloud target.
- GitHub Actions for checks and repeatable deployment.
- CloudWatch/AgentCore observability for runtime traces, logs, and metrics.

Reference documentation:

- [Strands Agents](https://strandsagents.com/)
- [Amazon Bedrock AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agents-tools-runtime.html)
- [AgentCore CLI getting started](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-cli.html)

## Five-day delivery rule

Build the seeded end-to-end story first:

Candidate profile → seeded job/inbox data → normalized evidence → explainable match → resume diff → application tracker → approval-gated draft.

Live Gmail, browser form filling, automatic submission, notifications, and multi-tenant hardening are stretch work. See the [roadmap](docs/ROADMAP.md) for the cut line.
