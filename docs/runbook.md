# Runbook

How to run this on a fresh machine and use it for a real application. Ten
minutes for setup; about fifteen minutes per application after that.

## First run

```bash
git clone https://github.com/tdare514/LookingForWork---job-application-agent
cd LookingForWork---job-application-agent
python3 -m venv .venv && source .venv/bin/activate
make install
make hooks          # pre-commit hook: blocks databases, PDFs and credentials
jobagent init       # creates ~/.local/share/jobagent at 0o700
```

## Put your real resume in place

**Not in the repository.** The repo is public; the data directory is not.

```bash
cp resume.example.yaml ~/.local/share/jobagent/resume.yaml
$EDITOR ~/.local/share/jobagent/resume.yaml   # real contact details, real accomplishments
jobagent resume validate
```

Two fields decide whether tailoring is honest, so get them right:

- **`metric`** — the measurement, exactly as it happened. Leave it out if there
  wasn't one. Nothing will invent a number for you.
- **`scope`** — `contributed`, `owned`, or `led`. What you actually held. This is
  what stops a bullet quietly promoting you when a posting asks for leadership.

The `standing` block holds the answers every portal asks for — work
authorization, availability, term length, notice, pay, commute. Written once,
reused verbatim.

## Applying, start to finish

```bash
jobagent add -c "RBC" -t "Business Systems Analyst (Winter 2027)" \
             -u "https://..." -d 2026-09-20 --ready
jobagent board
```

On the board:

| Key | Does |
| --- | --- |
| `d` | Drafts the package: tailored resume (PDF + DOCX), cover letter, answers |
| `c` | Opens the posting and copies the Claude in Chrome prompt |
| `a` | Marks it applied — **press this only after you actually submit** |
| `w` `n` `r` `i` `s` | Waiting, needs-you, rejected, interview, skip |
| `h` | Hide or show closed rows |

Then, off the board:

1. Open `~/.local/share/jobagent/packages/<id>/cover-letter.txt` and **write the
   bracketed paragraph**. Two or three sentences on why this company. It is the
   only part a reviewer can tell was written for them, and it is deliberately
   not generated.
2. Answer the flagged "why this company" entry in `answers.json`.
3. Paste the prompt into Claude in Chrome on the posting page. It fills the form
   and stops — it is instructed not to submit.
4. Read the filled form. Submit it yourself.
5. Back on the board, press `a`.

## Keeping the pipeline alive

```bash
jobagent followups     # what is overdue, most overdue first
```

Fires at 10 days submitted with no acknowledgement, 5 days after an interview,
and marks anything untouched for 30 days as stale. The board shows a count too,
so a reminder you have to remember to run is not the only reminder.

## When something is wrong

**`No resume at …`** — the data directory has no `resume.yaml`. Copy the example.

**`Refused: N unsupported claim(s)`** — the truthfulness check rejected a
tailored variant, and nothing was written. It means a bullet claims a number,
scope or breadth the resume does not support. Fix the resume if the claim is
true, or leave it — do not weaken the check.

**`No clipboard tool`** — the prompt is written to `claude-prompt.txt` beside the
package instead. Install `xclip`, `wl-clipboard`, or use macOS `pbcopy`.

**Board won't start** — run `jobagent init` first.

## Your data

```bash
jobagent pii       # every field stored, why, and for how long
jobagent audit     # append-only record of what the agent did
```

Everything lives in `~/.local/share/jobagent`, mode `0o700`, outside any
repository. Back it up by copying that directory; delete it to delete
everything.

## Rotating credentials

There are none. The tool holds no API key and no mail token — that is the point
of the board-first design ([ADR 0005](adr/0005-board-first-claude-in-chrome.md)).
If that ever changes, secrets come from the OS keychain or the environment, and
never from a file.
