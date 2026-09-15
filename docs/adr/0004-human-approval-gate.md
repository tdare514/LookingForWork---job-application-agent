# 0004 — The human approval gate is structural

**Status:** Proposed
**Date:** TBD

## Context

An agent that can submit applications unattended is attractive for about a week,
until it applies to the user's current employer, or sends a resume with a
hallucinated credential, or trips a job site's automation defenses and gets the
account banned. These are not hypothetical failure modes; they are the expected
ones.

A configuration setting defending against this is not a defense. Settings get
flipped at 1am in week eleven.

## Decision

No code path exists from a drafted application package to an outbound submission
that does not pass through a recorded human approval. This is enforced by the
architecture and asserted by a test, not by a default value.

Related: mail-derived status updates suggest state transitions and never apply
them.

## Consequences

Throughput is capped by the user's review time. That is the intended trade: the
bottleneck this project attacks is finding roles worth applying to, not the
typing.

A user who edits the code to remove the gate can do so. The gate defends against
agent error, not against its owner.
