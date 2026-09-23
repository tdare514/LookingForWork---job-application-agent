# Architecture decision records

Short records of decisions that are expensive to reverse. One file per decision,
numbered, never edited after acceptance — a decision that changes gets a new ADR
that supersedes the old one.

| # | Decision | Status |
| --- | --- | --- |
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted |
| [0002](0002-runtime-stack.md) | Runtime stack (Python) | Accepted |
| [0003](0003-local-first-storage.md) | Local-first storage | Accepted |
| [0004](0004-human-approval-gate.md) | Human approval gate is structural | Accepted |
| [0005](0005-board-first-claude-in-chrome.md) | Board first, Claude in Chrome for applying | Accepted |
| [0006](0006-repository-as-project-memory.md) | The repository is the project memory | Accepted |
| [0007](0007-document-rendering-stack.md) | Document rendering stack | Accepted |
| [0008](0008-fetching-is-viable-crawler-still-optional.md) | Fetching works; the crawler stays optional anyway | Proposed — supersedes 0005 |
| [0009](0009-phone-snapshot.md) | A read-only phone snapshot, behind Cloudflare Access | Accepted — extends 0003 |
| [0010](0010-hosted-tracker-companion.md) | A hosted tracker companion with owner-only writes | Proposed — amends 0009 |
