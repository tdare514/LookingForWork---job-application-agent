# 0002 — Runtime stack

**Status:** Proposed — must be accepted before Phase 1 implementation begins
**Date:** TBD

## Context

Every Phase 1 issue is blocked on this. The workload is: HTTP fetching with rate
limits, text extraction, embedding and LLM calls, an embedded relational
database, document rendering to PDF and DOCX, and a CLI. Single user, local
execution, no server.

## Options

**Python.** Strongest ecosystem for the parts that are hard: document parsing
and rendering, embeddings, LLM SDKs, text processing. Typing is optional and
must be enforced by tooling. Packaging a CLI is workable but not delightful.

**TypeScript on Node.** Types by default; good HTTP and CLI tooling. Weaker for
document rendering and text processing — PDF and DOCX generation would lean on
thinner libraries, which is exactly where Phase 3 lives.

**Go.** Best single-binary distribution and the most predictable runtime.
Weakest ecosystem for the document and ML work, which is most of the actual
difficulty here.

## Decision

TBD. Recommendation is Python: the two genuinely hard problems in this project —
document generation that survives an ATS parser, and text extraction from messy
posting descriptions — are where Python's ecosystem is furthest ahead, and
distribution does not matter for a single-user local tool. Its main weakness,
optional typing, is fixable with strict type checking in CI, which Phase 1
sets up regardless.

## Consequences

To be recorded on acceptance: the toolchain for linting, formatting, type
checking, and testing follows from this, as does the shape of every Phase 1
scaffolding issue.
