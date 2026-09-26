# Scheduled Daily Fetch

This document explains how to run `jobagent daily` on a schedule on macOS using launchd.

## Why a separate runtime?

macOS privacy protection (TCC) prevents background jobs from reading protected folders like `~/Documents`, `~/Desktop`, and `~/Downloads`, even if the running user owns those folders. The repository and its Python virtual environment live under `~/Documents`, so a launchd job calling `./scripts/launchd/run-daily.sh` would fail with exit code 126.

The solution is to build a separate runtime outside protected folders at `~/.local/share/jobagent-runtime/` (or a custom location via `JOBAGENT_RUNTIME_DIR`). The runtime contains a copy of the venv and source code. The launchd job runs from there and bypasses the TCC restriction.

This is handled automatically by `make schedule` — you do not need to understand the details. Running `make schedule` after every `git pull` refreshes the runtime to the current code.

## What it does

The launchd job runs `jobagent daily` once per day, which:

1. Fetches postings from configured job sources (Workday tenants for RBC, BMO, and TD)
2. Extracts requirements from posting descriptions
3. Scores each posting against your profile
4. Prints a digest of new postings and score changes to the console (and logs it to a file)

The digest is appended to a log file under your data directory (`~/.local/share/jobagent/jobagent-daily.log` by default), so you can check it later if the background run silently fails.

## What it explicitly does NOT do

- **It never runs `jobagent sync`** or any command that reaches the Cloudflare companion. Syncing to the hosted board is a deliberate, manual act — it stays that way per ADR 0010.
- **It never reaches any host outside the job-board sources** it explicitly fetches from (RBC, BMO, TD Workday tenants).
- **It never submits an application** or sends anything on the owner's behalf. Applying is a handoff to Claude in Chrome.

If you want to sync to a hosted view, run that separately by hand:

```bash
jobagent sync             # dry run: prints what would sync, sends nothing
jobagent sync --yes       # actually send it
```

## Installation

### 1. Install the runtime

From the repository root, run:

```bash
make schedule
```

This will:
- Create the runtime directory at `~/.local/share/jobagent-runtime/` (or `$JOBAGENT_RUNTIME_DIR` if set)
- Copy the Python venv, `src/` and `run-daily.sh` to the runtime, and point the venv's editable install at the copied `src/` (no `pip install`, no network; the repo's `.venv` is left as it is)
- Create the plist file at `~/Library/LaunchAgents/com.jobagent.daily.plist`
- Print the `launchctl` commands to load the job; it never runs them

The command is safe to run multiple times and is idempotent — if you have an existing plist with custom `EnvironmentVariables` or `StartCalendarInterval` settings, they are preserved.

### 2. Load the job

After running `make schedule`, load the job as instructed:

```bash
launchctl load ~/Library/LaunchAgents/com.jobagent.daily.plist
```

The job will run at 10:00 AM every day by default.

### 3. Customize the schedule (optional)

To change the run time, edit the plist:

```bash
# Edit the time in StartCalendarInterval
/usr/libexec/PlistBuddy -c "Set StartCalendarInterval:Hour 14" ~/Library/LaunchAgents/com.jobagent.daily.plist
```

Then reload the job:

```bash
launchctl unload ~/Library/LaunchAgents/com.jobagent.daily.plist
launchctl load ~/Library/LaunchAgents/com.jobagent.daily.plist
```

Or use your favorite plist editor to change the time directly in the file.

### 4. Refresh after updates

After pulling new code, refresh the runtime to pick up changes:

```bash
make schedule
launchctl unload ~/Library/LaunchAgents/com.jobagent.daily.plist
launchctl load ~/Library/LaunchAgents/com.jobagent.daily.plist
```

You must reload the plist after refreshing the runtime so launchd picks up any path changes.

### 5. Wake the Mac before the job (optional)

launchd does not wake a sleeping Mac. A job whose time passes during sleep
runs once when the Mac next wakes, and a Mac that is shut down misses it. To
have the run happen on time, schedule a wake a few minutes before it with
`pmset`, once, by hand. It needs `sudo`, so no script here does it:

```bash
# Every day at 09:55, five minutes before the default 10:00 job.
sudo pmset repeat wakeorpoweron MTWRFSU 09:55:00
pmset -g sched                  # confirm it is scheduled
sudo pmset repeat cancel        # remove it again
```

Match the time to `StartCalendarInterval` if you changed it. `pmset` keeps
one repeating schedule, so this replaces any repeat set earlier. A laptop
needs to be on power to be powered on. It may also go back to sleep before a
long run finishes, so check the log's `completed` line the first few days.

## Notifications

Each time the scheduled job completes, it posts a local notification to your Mac showing:

- **Success:** "N new postings since you last looked" (or "Nothing new since you last looked"). "Since you last looked" means since you last ran `jobagent digest` yourself — the scheduled run reads the digest without marking it seen.
- **Failure:** "Daily run had failures — see jobagent-daily.log" (when `daily` exits non-zero, e.g. a source declined). The job's own exit status is non-zero too.
- **Digest unreadable:** "Daily run finished, but the digest couldn't be read — see jobagent-daily.log"

The notification carries **counts only**, never company names or job titles. This protects the most sensitive data the tool holds — the list of employers you are approaching — from appearing on your lock screen.

To disable notifications, add `JOBAGENT_NOTIFY=0` to the plist environment:

```xml
<key>EnvironmentVariables</key>
<dict>
    <key>JOBAGENT_NOTIFY</key>
    <string>0</string>
</dict>
```

Then reload the job:

```bash
launchctl unload ~/Library/LaunchAgents/com.jobagent.daily.plist
launchctl load ~/Library/LaunchAgents/com.jobagent.daily.plist
```

## Monitoring

### Check the logs

The job appends output to two places:

1. **Application log:** `~/.local/share/jobagent/jobagent-daily.log` — the log file written by the script itself, with timestamps and output from `jobagent daily`.

```bash
# See the last 50 lines
tail -50 ~/.local/share/jobagent/jobagent-daily.log

# Follow the log in real-time (run this before the scheduled time and wait)
tail -f ~/.local/share/jobagent/jobagent-daily.log
```

2. **launchd logs:** `~/Library/Logs/jobagent-daily.out.log` and `jobagent-daily.err.log` — captured by launchd itself. A job that fails before the script's own log opens (a TCC refusal, a missing runtime) only shows up here.

```bash
# See launchd's capture of the job's output
tail ~/Library/Logs/jobagent-daily.out.log
tail ~/Library/Logs/jobagent-daily.err.log
```

### Check job status

```bash
# List all loaded jobs for the current user
launchctl list | grep jobagent

# Show the plist details
launchctl print user/$(id -u)/com.jobagent.daily
```


## Uninstalling

To remove the scheduled job:

```bash
launchctl unload ~/Library/LaunchAgents/com.jobagent.daily.plist
rm ~/Library/LaunchAgents/com.jobagent.daily.plist
```

## Troubleshooting

### The job is not running

1. Check that the plist file is installed:

```bash
ls -la ~/Library/LaunchAgents/com.jobagent.daily.plist
plutil -lint ~/Library/LaunchAgents/com.jobagent.daily.plist
```

2. Check that launchd loaded it:

```bash
launchctl list | grep com.jobagent.daily
```

If it is not there, reload it:

```bash
launchctl load ~/Library/LaunchAgents/com.jobagent.daily.plist
```

3. Check the logs:

```bash
tail ~/.local/share/jobagent/jobagent-daily.log
tail ~/Library/Logs/jobagent-daily.err.log
```

### The job ran but produced no output or failed

Check both log locations:

```bash
tail ~/.local/share/jobagent/jobagent-daily.log        # Application log
tail ~/Library/Logs/jobagent-daily.err.log              # launchd stderr
```

Common issues:

- **Runtime not found:** The runtime at `~/.local/share/jobagent-runtime/` may be stale after a git pull. Re-run `make schedule` and reload the job.
- **Permission denied:** The runtime paths need to be readable by the current user. Check that `~/.local/share/jobagent-runtime/` exists and is owned by you.
- **Source failed with 401/403:** One of the job sources (RBC, BMO, or TD) declined the request. This is normal and `daily` will continue with the other sources and print a summary. Check the log for details.
- **Import error:** If the Python import fails, re-run `make schedule` to refresh the runtime with the current code and plist.

### Configuring sources

To change which sources are fetched, set the `JOBAGENT_DAILY_SOURCES` environment variable in the plist. This avoids editing a tracked file, which would leave your checkout dirty.

Add it to the `EnvironmentVariables` dict in `~/Library/LaunchAgents/com.jobagent.daily.plist` (with a plist editor or `PlistBuddy`); `make schedule` keeps that dict and `StartCalendarInterval` when it rewrites the plist. For example, to fetch from RBC, BMO, and a Greenhouse board:

```xml
<key>EnvironmentVariables</key>
<dict>
    <key>JOBAGENT_DAILY_SOURCES</key>
    <string>workday:rbc workday:bmo greenhouse:stripe</string>
</dict>
```

Source names are space-separated. If `JOBAGENT_DAILY_SOURCES` is unset or empty, the default sources are used: `workday:rbc workday:bmo workday:td`.

`JOBAGENT_DAILY_LIMIT` (default `50`) is passed to `daily` as `--limit`, the postings kept per source.

**Note on Greenhouse sources:** Greenhouse sources are referenced by their board slug (e.g. `greenhouse:stripe` for Stripe's board). Since `jobagent daily` has no `--company` flag, the daily output uses the title-cased slug as the company name (e.g. "Stripe" for `greenhouse:stripe`).

After editing the plist, reload the job:

```bash
launchctl unload ~/Library/LaunchAgents/com.jobagent.daily.plist
launchctl load ~/Library/LaunchAgents/com.jobagent.daily.plist
```

## See also

- `jobagent daily --help` — the command's full help
- `jobagent fetch --help` — understand what sources are available
- [ADR 0010: Hosted tracker companion](./adr/0010-hosted-tracker-companion.md) — why sync is not automated
