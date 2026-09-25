# Scheduled Daily Fetch

This document explains how to run `jobagent daily` on a schedule on macOS using launchd.

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

### 1. Set up the wrapper script

Make the wrapper script executable:

```bash
chmod +x scripts/launchd/run-daily.sh
```

### 2. Create the plist file

Copy the template and fill in the placeholders:

```bash
# Copy the template to ~/Library/LaunchAgents (the standard location for user-owned jobs)
cp scripts/launchd/com.jobagent.daily.plist.template \
   ~/Library/LaunchAgents/com.jobagent.daily.plist
```

Edit `~/Library/LaunchAgents/com.jobagent.daily.plist` and replace:

- `__PATH_TO_WRAPPER_SCRIPT__` with the absolute path to `scripts/launchd/run-daily.sh` in your repository.  
  Example: `/Users/yourname/path/to/job-agent/scripts/launchd/run-daily.sh`

The comment in the template also shows how to set `__PATH_TO_DATA_DIR__` if you uncomment the logging directives (optional).

### 3. Load the job

Tell launchd to load and start the job:

```bash
launchctl load ~/Library/LaunchAgents/com.jobagent.daily.plist
```

The job will run at 10:00 AM every day by default. To change the time, edit the `StartCalendarInterval` section in the plist:

```xml
<key>StartCalendarInterval</key>
<dict>
    <key>Hour</key>
    <integer>10</integer>      <!-- Change this -->
    <key>Minute</key>
    <integer>0</integer>       <!-- Or this -->
</dict>
```

Then reload:

```bash
launchctl unload ~/Library/LaunchAgents/com.jobagent.daily.plist
launchctl load ~/Library/LaunchAgents/com.jobagent.daily.plist
```

## Monitoring

### Check the log

The job appends to `$JOBAGENT_DATA_DIR/jobagent-daily.log` (usually `~/.local/share/jobagent/jobagent-daily.log`).

```bash
# See the last 50 lines
tail -50 ~/.local/share/jobagent/jobagent-daily.log

# Follow the log in real-time (run this before the scheduled time and wait)
tail -f ~/.local/share/jobagent/jobagent-daily.log
```

### Check job status

```bash
# List all loaded jobs for the current user
launchctl list | grep jobagent

# Show the plist details
launchctl print user/$(id -u)/com.jobagent.daily
```

### Enable stdout/stderr logging (optional)

The plist template includes commented-out `StandardOutPath` and `StandardErrorPath` directives. Uncomment them if you want launchd itself to log stdout/stderr in addition to the log file the wrapper script creates:

```xml
<key>StandardErrorPath</key>
<string>~/.local/share/jobagent/jobagent-daily-stderr.log</string>
<key>StandardOutPath</key>
<string>~/.local/share/jobagent/jobagent-daily-stdout.log</string>
```

Then reload the job.

## Uninstalling

To remove the scheduled job:

```bash
launchctl unload ~/Library/LaunchAgents/com.jobagent.daily.plist
rm ~/Library/LaunchAgents/com.jobagent.daily.plist
```

## Troubleshooting

### The job is not running

1. Check that the plist file is installed and has the correct label:

```bash
ls -la ~/Library/LaunchAgents/com.jobagent.daily.plist
```

2. Check that launchd loaded it:

```bash
launchctl list | grep com.jobagent.daily
```

If it is not there, you may need to reload it:

```bash
launchctl load ~/Library/LaunchAgents/com.jobagent.daily.plist
```

### The job ran but produced no output

Check the log file:

```bash
tail ~/.local/share/jobagent/jobagent-daily.log
```

Common issues:

- **Path in plist is wrong:** Verify that `__PATH_TO_WRAPPER_SCRIPT__` is an absolute path and points to an executable file.
- **venv not found:** The wrapper script looks for `.venv/bin/activate` relative to the repository root. If you use a different venv location, edit the script.
- **Source failed with 401/403:** One of the job sources (RBC, BMO, or TD) declined the request. This is normal and `daily` will continue with the other sources and print a summary. Check the log for details.

### Configuring sources

To change which sources are fetched, set the `JOBAGENT_DAILY_SOURCES` environment variable in the plist. This avoids editing a tracked file, which would leave your checkout dirty.

Edit `~/Library/LaunchAgents/com.jobagent.daily.plist` and uncomment the `JOBAGENT_DAILY_SOURCES` line in the `EnvironmentVariables` dict. For example, to fetch from RBC, BMO, and a Greenhouse board:

```xml
<key>EnvironmentVariables</key>
<dict>
    <key>JOBAGENT_DAILY_SOURCES</key>
    <string>workday:rbc workday:bmo greenhouse:stripe</string>
</dict>
```

Source names are space-separated. If `JOBAGENT_DAILY_SOURCES` is unset or empty, the default sources are used: `workday:rbc workday:bmo workday:td`.

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
