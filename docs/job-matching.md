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

With a profile stored, `fetch` runs two of the hard filters below — location
and seniority — before anything is written, so a clear miss never reaches the
board. Both pass what they cannot judge. A Greenhouse board arrives whole, so
it is filtered before `--limit`. Workday keeps its existing list-fetch limit,
then filters that batch before fetching details; it does not fetch more pages
to replace dropped postings. The dropped counts per rule are printed and are
the only record. `--no-prefilter` turns it off.

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
cutting too aggressively should be discoverable — `jobagent score --filtered`
is the query.

**Absence is never a refusal.** A posting that does not state compensation has
not offered a low one; one silent on sponsorship has not declined to sponsor; a
title with no level marker is not a senior role. Every rule passes on missing
data, because a filter that cuts too much produces an empty board, and an empty
board is indistinguishable from a quiet week.

Two consequences worth stating, both learned from real postings:

- The seniority rule cuts only on a level the posting actually stated. Roughly
  half of bank postings carry no level marker, and the ladder's `mid` fallback is
  an assumption this tool made, not something an employer wrote. Unmarked
  postings pass the filter and take a middling seniority score instead.
- A compensation band in a different currency is not compared numerically. No
  conversion rate belongs in an offline tool, so the filter declines to judge
  rather than judging wrongly.

### 6. Score

Decomposed, weighted, and stored component by component. These are the shipped
defaults in `jobagent.core.profile.Weights`:

| Component | Weight | Basis |
| --- | --- | --- |
| Skill overlap | 0.40 | Posting skills against profile skills, required weighted three times preferred |
| Seniority fit | 0.20 | Distance on the normalized ladder |
| Domain relevance | 0.27 | Title vocabulary against the profile's target titles |
| Freshness | 0.13 | Decay from `posted_at`, 14-day half-life |
| Semantic fit | 0.00 | **No backend.** See below |

Weights are profile configuration, not constants. Someone changing domains wants
domain relevance near zero, and the system should not fight that. They are
relative importance rather than fractions: the profile's numbers are normalized
on read, so they need not sum to one.

**Semantic fit does not ship.** It needs an embedding model. A metered
embeddings API is out of scope under the budget constraint in `AGENTS.md`, and
no local backend has been chosen. The component stays in the schema and in every
stored decomposition, recorded as explicitly unavailable — but the profile
*refuses* a non-zero weight for it rather than accepting one and quietly
ignoring it. A weight that does nothing is worse than one that is absent,
because the score it produces looks complete.

Two components are narrower than this section originally claimed, and the stored
`basis` string for each says so rather than letting the name imply more. Domain
relevance compares title vocabulary, not industry history — there is no industry
field on the profile to read. Skill overlap is measured as the share of what the
*posting* asks for that the profile covers, so a long profile is not punished for
listing skills a given posting does not want.

### A component with no basis is dropped, not zeroed

Most rows carry no description until `fetch --details` has run, and Workday's
list endpoint publishes no `posted_at` at all. Scoring those absences as zero
would rank a posting last for a fetch that has not happened yet, and running the
fetch later would reshuffle the board for reasons that have nothing to do with
the jobs. So an unmeasurable component is dropped and the remaining weights
rescale over what was actually measured.

The distinction that has to be kept sharp is between *nothing to read* and *read
it, found nothing*. A posting with no stored description genuinely cannot be
judged on skills. A 12,000-character description naming none of the profile's
skills has been judged, and its score is zero. Conflating the two was a real bug:
it let a contact centre posting outrank a risk internship by virtue of the
extractor finding nothing in it. Knowing less about a job must never flatter it.

The cost is that totals are strictly comparable only between postings scored on
the same components, so every stored score records which ones those were and
`jobagent score` prints the count.

The stored decomposition is what makes a score arguable. "Ranked 7th because
skill overlap is 0.9 but domain relevance is 0.2" is actionable; a bare 0.63 is
not.

### 7. Rank and digest

`jobagent shortlist` is the ranked list; `jobagent digest` is the reading queue
on top of it. Both take `--json`. `jobagent daily` runs the whole pipeline
unattended — fetch, extract, score, digest — and is safe for cron.

Four sections, because four questions are worth asking each morning:

| Section | Answers |
|---|---|
| New | What appeared since I last looked, above the threshold |
| Moved | What changed its mind, and **which component** changed it |
| Reposts | What I have seen before, with the sighting count |
| Filtered | What the hard filters removed, aggregated **by rule** |

Each entry carries its score decomposition and a link.

Every section is capped. #32 states the failure mode it is designed against —
*a digest that gets skipped is the whole phase wasted* — so `shortlist.max_entries`
from the profile bounds the section that matters and constants bound the rest.
Four uncapped sections is a report, not a digest.

**"Since when" is derived, not stored.** The audit log already records that a
digest ran, and that is the same fact a run-marker table would hold. When there
is no previous run — a fresh install, or after `purge` clears the log — it falls
back to a window and *says which it used*: "new since yesterday" and "new since
you last looked" are different claims, and the digest should not make the
stronger one by accident.

Three rules about what does **not** appear, each of which was a bug first:

- **A repost is never counted as new.** A role seen repeatedly is either a hard
  requisition to fill or a phantom posting (#28) — worth knowing before an
  evening on a cover letter, not after.
- **A row you decided on does not come back.** Skipped, rejected, or already
  applied to. Skipping has to actually stop it returning or the queue stops
  being one. `jobagent snooze` is the softer form: it hides a row until a date
  and it returns on its own, deliberately not a state, because "not now" is not
  a decision and should not have to be undone by hand.
- **A role that fell below the threshold is still reported**, flagged as having
  dropped off. Building the moved section only from rows currently on the list
  meant the most actionable movement there is — this is no longer worth your
  evening — vanished silently.

Skips carry a reason (`jobagent skip <id> -r "..."`), stored on the row and
aggregated by `jobagent report`. Skips with no reason are counted separately
rather than dropped: the board's `s` key does not ask for one, so "I did not
say" is the common case and worth seeing next to the ones that did.

Selecting from the digest is the handoff into Phase 3.

## Calibration

Scoring is regression-tested against a fixture set of labeled postings — roles
the user would clearly pursue, clearly skip, and genuinely find borderline. A
scoring change that flips a clear case fails CI. The corpus is twelve real RBC,
BMO and TD postings in `tests/fixtures/`, labelled by hand in
`ranking_labels.json` and exercised by `tests/test_ranking.py`.

**Growing the corpus needs a machine with network access.** A build container
cannot do it: its proxy refuses `rbc.wd3.myworkdayjobs.com` and every other job
board at the CONNECT stage, before a request is made, so the failure is not a
tenant declining and no adapter change helps. On a machine that can reach them:

```
export JOBAGENT_DATA_DIR=/tmp/corpus-capture   # not the real board
jobagent init
jobagent fetch workday:rbc --details --limit 50
python3 scripts/capture_postings.py --new-only
```

That prints fixture-shaped JSON to stdout and writes nothing. It emits only
employer-published fields — never notes, state, skip reasons or URLs — and the
allowlist enforcing that lives in `BoardRepo.FIXTURE_FIELDS`, beside the query
rather than in the script, because a script can be bypassed. These fixtures go
into a public repository; `tests/test_capture.py` is what keeps the path narrow.

Labels are still written by hand afterwards, by reading the posting text. That
is not a step to automate: a label copied from the extractor's output measures
the extractor against itself.

No absolute score is asserted. Pinning "the credit risk intern scores 0.53"
would fail on every honest change to the weights and teach whoever is on call to
update the number rather than read it. What is pinned is the relationships:
every clear pursue outranks every clear skip, each expected cut names the rule
that made it, and a borderline row beats the clear skips without being pinned
against the pursues — which side of a borderline case a change lands on is the
thing that is genuinely uncertain.

Feedback from outcomes closes the loop: applications that reached a screen
versus those that went nowhere are the real label set. By Phase 4 the funnel
report should be able to say whether score correlates with response at all. If
it does not, the weights are wrong and that is worth knowing in March rather
than assuming in April.
