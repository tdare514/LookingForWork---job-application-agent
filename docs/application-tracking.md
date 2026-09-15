# Resume management and application tracking

## Resume as a source of truth

One structured document holds every claim the agent is allowed to make: roles,
dates, employers, accomplishments with metrics, skills with evidence, education,
certifications, and links.

This is not a formatting document. It is the fact base. Tailored resumes are
derived from it; it is never derived from them.

```
resume.yaml (source of truth)
     │
     ├── tailoring ──▶ variant for job #1234 ──▶ validation ──▶ render ──▶ PDF/DOCX
     │
     └── answer library ──▶ prefilled application questions
```

Each accomplishment carries the raw material tailoring needs to make a choice:
what was done, measured impact, technologies involved, and which role and dates
it belongs to.

## Tailoring

Given a posting and its extracted requirements, tailoring:
1. Selects the accomplishments most relevant to the requirements.
2. Orders sections and bullets by relevance to this role.
3. Rephrases toward the posting's vocabulary — "distributed systems" or
   "backend infrastructure" depending on which the posting uses.
4. Trims to a target length.

What it must not do is invent. Rephrasing "reduced p99 latency 40%" as
"led latency reduction initiatives across the platform" has quietly added a
scope claim that is not in the source. The validation pass exists because this
failure mode is subtle, plausible-sounding, and a liability in an interview.

**Validation.** Every generated claim is checked back against the source of
truth. Unsupported claims fail the package. This has test coverage asserting a
fabricated claim is caught — the test is the guarantee, the prompt is not.

**Diff.** Review shows what changed from the source: what was selected, dropped,
and rephrased, so the approval is informed rather than a rubber stamp.

## Cover letters and the answer library

Cover letters draw from the same fact base with tone and length controls.

Applications repeat the same questions — why this company, salary expectations,
notice period, sponsorship status, accessibility needs. The answer library keeps
canonical answers, reused verbatim where the question is generic and tailored
only where the company is named. Regenerating a sponsorship answer on every
application is both wasteful and a chance to get it wrong.

## Rendering

PDF and DOCX from one structured variant. Layout rules are set by what parses:
single column, standard section headings, no tables, no text in graphics, no
icon fonts. A visually sophisticated resume that an ATS reads as gibberish has
failed at its only job.

## Approval gate

Nothing reaches a company without passing here. The gate presents the package,
the diff against the source of truth, and the validation result. The user
approves or rejects with a reason.

Rejection reasons are stored and fed back into tailoring — the tenth rejection
for "too long" should change the default target length, not be re-learned each
time.

## Application state machine

```
drafted ──▶ approved ──▶ submitted ──▶ acknowledged ──▶ screening ──▶ interviewing ──▶ offer
   │            │            │              │               │              │
   └──▶ discarded            └──────────────┴───────────────┴──────────────┴──▶ rejected
                             │
                             └──▶ withdrawn      (any state, on timeout) ──▶ stale
```

Every transition is timestamped. That single property makes both follow-up
scheduling and funnel analysis queries instead of guesswork.

`stale` is its own state rather than an absence. Most applications end in
silence, and a pipeline that cannot distinguish "no reply yet" from "no reply,
ever" slowly fills with corpses.

## Status ingestion

Read-only mail access classifies incoming messages as acknowledgement,
rejection, interview invitation, or offer, and matches them to applications by
company and thread.

Ingestion **suggests** transitions. It never applies them silently. A
misclassified rejection that quietly closes a live application is worse than no
automation, and classifiers on recruiter email are not reliable enough to earn
that trust.

## Follow-ups

Driven by time in state:
- Submitted, no acknowledgement after 10 days → follow-up suggested.
- Screening, no movement after 7 days → check in.
- Post-interview, no response after 5 days → follow-up.
- Any state untouched for 30 days → mark stale.

Thresholds are configuration. The scheduler produces suggestions in the digest;
sending is the user's action.

## Funnel analytics

The Phase 4 report answers questions that change what the user does in the
remaining weeks:

- Conversion at each stage: submitted → acknowledged → screening → interview →
  offer.
- Cut by source: which boards produce applications that convert, rather than
  which produce the most postings.
- Cut by match score: does the score predict response? If not, the weights are
  wrong.
- Cut by role type and seniority: where is the market actually open.
- Time in stage: where applications die, and how long "alive" really means.

By late April this should be able to say something specific — that a source
generating a third of the applications produced no screens, for instance. That
is the payoff of the whole pipeline, and it is why tracking is a phase rather
than a spreadsheet.

## Export and purge

`export` writes a portable archive: profile, resume, jobs, applications,
documents, audit log. `purge` removes stored PII and is verified by a test
asserting nothing recoverable remains. A job search ends; the dossier should be
able to end with it.
