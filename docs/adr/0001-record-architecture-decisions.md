# 0001 — Record architecture decisions

**Status:** Accepted
**Date:** 2027-01-04

## Context

This project has a four-month budget and one contributor. The failure mode for
a project like this is not bad decisions, it is re-litigating settled ones in
March because nobody wrote down why February went the way it did.

## Decision

Decisions that are expensive to reverse get an ADR: context, decision,
consequences. Numbered, immutable once accepted, superseded rather than edited.

Cheap and reversible decisions do not get an ADR. A file naming convention is
not an architecture decision.

## Consequences

Small ongoing cost per significant decision. In exchange, the reasoning survives
the moment it was made, which matters most at the end of the project when the
context has faded and the pressure is highest.
