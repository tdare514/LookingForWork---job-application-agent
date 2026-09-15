# 0008 — Fetching works; the crawler stays optional anyway

**Status:** Proposed
**Date:** 2026-09-15
**Supersedes:** [0005](0005-board-first-claude-in-chrome.md)

## Context

ADR 0005 inverted the architecture — board first, crawler optional, applying by
handoff — and rested that on two facts. One of them is false.

> **Workday's public job API is in maintenance as of September 2026.** RBC, BMO,
> Scotiabank and TD all run Workday. The crawler — the largest block of work in
> the plan — cannot reliably reach the only employers that actually matter here.

It is not in maintenance. Verified from a real machine on 2026-09-15 (#57, #58):
RBC, BMO and TD each answer 200 on the public CXS endpoint with the documented
shape, returning 156, 1039 and 1756 postings respectively. The constructed
posting URLs resolve. `jobagent fetch workday:rbc` pulls real Winter 2027 co-op
rows today.

The claim came from a search snippet about third-party scrapers and was written
down as fact without being tested. The 403 later recorded in `STATUS.md` as
corroboration was the build container's own proxy, not a tenant. Two pieces of
evidence, neither of which was evidence.

Scotiabank is wrong in that sentence for a different reason: it does not run
Workday at all. `jobs.scotiabank.com` is SAP SuccessFactors.

## Decision

**The decision in 0005 stands. Only its reasoning changes.**

The board is still the product, applying is still a handoff, and scoring is
still rule-based. None of that depended on the maintenance claim. It depended on
the *other* premise — a Claude subscription carries no API credit — which is
untouched and is the one doing the real work.

What changes is why the crawler is optional:

- **0005 said it was optional because it could not reliably work.** That was
  wrong.
- **It is optional because it is not the bottleneck.** Fetching produces rows.
  Rows are cheap. The scarce thing in this project is the hour spent writing a
  company paragraph before a Friday deadline, and no volume of fetched postings
  reduces that.

So `jobagent fetch` keeps its current shape — a command run deliberately, for a
named source, with a limit — rather than growing into a scheduled crawler. Not
because it cannot, but because more rows is not the win.

Two boundaries from 0005 are re-affirmed explicitly, because a working fetch
makes them easier to erode:

1. **A 401/403 is a refusal, not a puzzle.** No varied user agents, no proxy
   rotation, no routing around bot protection. The adapter stops and the handoff
   takes over.
2. **Reachability is not permission.** A live 200 says the endpoint answered. It
   says nothing about whether the terms allow automated access, so
   `terms.allows_automated_access` stays `unverified` until someone reads them.
   The fetch working is not consent.

## Consequences

The dead-weight verdict in 0005 needs qualifying. The adapter framework, the
rate limiter and the host allowlist were built anyway and are now load-bearing,
so "a large share of the original issue list is dead weight" reads as
over-broad in hindsight. What actually died was the *LLM boundary with spend
tracking*, which the budget constraint kills independently.

Issue #30 inherits this. It specifies extraction "through the LLM boundary from
#25", and that boundary does not exist and will not — so extraction is
rule-based or it does not ship.

The wider lesson is cheaper to state than it was to learn: **a claim about the
outside world does not go into an ADR until something has been run against it.**
0005 would have been correct on its first premise and wrong on nothing if one
`curl` had been attempted before writing it down.

## Alternatives considered

**Leave 0005 alone.** Defensible — the decision holds on its other premise, and
an ADR is a record of reasoning as it stood, not a live document. Rejected
because 0005 does not read as a historical snapshot; it reads as a current
statement of fact that a future session would take at face value and use to
justify not bothering to fetch.

**Reverse 0005 and build the crawler.** Rejected. Fetching working does not make
the crawler worth building, and the budget and handoff constraints are unchanged.
