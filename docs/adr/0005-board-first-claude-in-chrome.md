# 0005 — Board first, Claude in Chrome for applying

**Status:** Accepted
**Date:** 2026-09-15

## Context

Two facts landed after the original plan and between them they invalidate its
centre of gravity.

**A Claude subscription includes no API credit.** Subscription and API billing
are separate; Opus 5 on the API is $5/$25 per million tokens. The budget for this
project is "nothing beyond the subscription I already pay for", so any design
whose core loop calls the Anthropic API with a key is out.

**Workday's public job API is in maintenance as of September 2026.** RBC, BMO,
Scotiabank and TD all run Workday. The crawler — the largest block of work in the
plan — cannot reliably reach the only employers that actually matter here.
Greenhouse and Lever remain free and open, but those are mostly startups, not the
Canadian bank co-op postings this tool exists to chase.

## Decision

Invert the architecture. **The board is the product; the crawler is optional.**

- Opportunities enter the board by hand (`jobagent add`) or, later, from the free
  Greenhouse/Lever endpoints where a target happens to use them.
- State lives on the job row with a traffic light: green for sent, red for dead,
  yellow for anything wanting attention today.
- Applying is a **handoff**, not automation. The board opens the posting and puts
  a prepared prompt on the clipboard; Claude in Chrome fills the form in the
  user's own browser, in their own session, with them watching.
- Scoring, when it arrives, is rule-based. No model call in the core loop.

## Consequences

Cost is zero beyond the subscription. No API key, no rate limiter, no adapter
framework, no LLM boundary with spend tracking — a large share of the original
issue list is now dead weight and should be closed rather than carried.

It also sidesteps the hardest technical problem in the original design.
Automating submission against Workday means fighting bot protection, which this
project's own boundaries forbid. Claude in Chrome is a human-operated browser, so
the question never arises.

The approval gate from #24 becomes structural for free: the handoff prompt
instructs Claude not to submit, and a human is physically present at the browser.
The gate is no longer code we maintain — it is the shape of the workflow.

The cost is no unattended overnight run. For a single-user job search measured in
dozens of applications, that was never worth what it would take to build.
