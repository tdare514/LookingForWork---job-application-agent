# Job matching workflow

## The problem this solves

Job boards optimize for volume. A human reading 200 postings a week to find six
worth applying to is the actual bottleneck in a job search, and it is the part
that degrades fastest under fatigue — by Thursday the filter is worse than it
was on Monday. The matching pipeline is there to make that filter consistent and
explainable, not to apply on the user's behalf.

## Pipeline

```
sources ──▶ fetch ──▶ normalize ──▶ dedupe ──▶ extract ──▶ filter ──▶ score ──▶ rank ──▶ digest
```

### 1. Fetch

Each source has an adapter declaring its rate limit and terms constraints. The
framework enforces the limit; the adapter cannot opt out. Raw payloads are
stored for 30 days so a mapping bug can be fixed without re-fetching.

### 2. Normalize

Every source maps to one canonical schema:

| Field | Notes |
| --- | --- |
| `source`, `source_id`, `url` | Provenance |
| `title`, `company`, `description` | As published |
| `location`, `work_arrangement` | Onsite, hybrid, remote; remote scoped to a region |
| `compensation_min`, `compensation_max`, `currency` | Null when undisclosed — common, and not a disqualifier |
| `seniority` | Normalized ladder, not the source's title inflation |
| `posted_at`, `first_seen_at`, `last_seen_at` | Drives staleness and repost detection |
| `raw` | Original payload reference |

### 3. De-duplicate

The same role appears on three boards and is reposted monthly. Matching on
`(normalized company, normalized title, location)` with fuzzy title comparison
collapses these into one job with many sightings.

Keeping sighting history matters: a role reposted repeatedly over two months is
either a hard req to fill or a phantom posting. Both are worth knowing before
spending an evening on a cover letter.

### 4. Extract

Structured requirements out of free text: required and preferred skills, years
of experience, compensation when stated in the body rather than a field, visa
sponsorship language, the closing date, and work arrangement when it contradicts
the structured field (it often does).

**Rule-based, not a model call.** ADR 0008 records why: the budget constraint
rules out a metered API in the core loop, so the LLM boundary this step was
originally specified against does not exist. Each extraction is stamped with a
ruleset version, which does the job the prompt version was meant to do — a
quality change has to be traceable to a rule change.

The section classifier is the part that matters. A posting's requirement bullets
and its *benefit* bullets are both bulleted lists, adjacent and identically
formatted; reading "Leaders who support your development" as a requirement would
poison every score downstream. Headings are classified explicitly and anything
unrecognised contributes nothing.

Extraction is evaluated against a hand-labeled fixture set of real postings, with
per-field precision and recall enforced in CI. Without that, a rule change that
silently degrades every downstream score looks exactly like one that does not.

### 5. Hard filters

Boolean, cheap, run first:
- Location or work arrangement incompatible with the profile.
- Compensation band entirely below the profile floor, when disclosed.
- Visa sponsorship required and not offered.
- Explicit deal-breakers from the profile (company blocklist, industries,
  clearance requirements).
- Seniority more than one rung outside the target.

Filtered jobs are stored with the reason, not discarded. A filter that is
cutting too aggressively should be discoverable.

### 6. Score

Decomposed, weighted, and stored component by component:

| Component | Weight | Basis |
| --- | --- | --- |
| Skill overlap | 0.30 | Required and preferred skills against profile skills, required weighted higher |
| Seniority fit | 0.15 | Distance on the normalized ladder |
| Domain relevance | 0.20 | Industry and problem-domain overlap with history |
| Semantic fit | 0.25 | Embedding similarity, description against profile narrative |
| Freshness | 0.10 | Decay from `posted_at`; week-old postings are already crowded |

Weights are profile configuration, not constants. Someone changing domains wants
domain relevance near zero, and the system should not fight that.

The stored decomposition is what makes a score arguable. "Ranked 7th because
skill overlap is 0.9 but domain relevance is 0.2" is actionable; a bare 0.63 is
not.

### 7. Rank and digest

Daily digest: new matches above threshold, roles whose score moved, reposts of
previously-seen roles, and what the hard filters removed in aggregate. Each entry
carries its score decomposition and a link.

The digest is a reading queue. Selecting from it is the handoff into Phase 3.

## Calibration

Scoring is regression-tested against a fixture set of labeled postings — roles
the user would clearly pursue, clearly skip, and genuinely find borderline. A
scoring change that flips a clear case fails CI.

Feedback from outcomes closes the loop: applications that reached a screen
versus those that went nowhere are the real label set. By Phase 4 the funnel
report should be able to say whether score correlates with response at all. If
it does not, the weights are wrong and that is worth knowing in March rather
than assuming in April.
