#!/bin/bash
# Wrapper script to run `jobagent daily` on a schedule.
#
# This script activates the project's virtual environment, sets environment
# variables, and runs `jobagent daily` with a fixed source list, logging to
# a file under the data directory.
#
# It is intended to be called by launchd via the plist at com.jobagent.daily.plist.template.
#
# After the run completes, it posts a notification to the system showing the
# count of new postings, or a failure message if daily exited non-zero.
# Set JOBAGENT_NOTIFY=0 in the plist to suppress notifications.

# Resolve the repo directory (the script lives at scripts/launchd/run-daily.sh)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"

# Activate the venv if it exists and is not already activated
if [[ -z "$VIRTUAL_ENV" && -f "$REPO_DIR/.venv/bin/activate" ]]; then
    source "$REPO_DIR/.venv/bin/activate"
fi

# Set JOBAGENT_DATA_DIR if not already set.
# If unset, jobagent will use its own default (typically ~/.local/share/jobagent on Linux/macOS).
# Do not override if the user has already set it.
if [[ -z "$JOBAGENT_DATA_DIR" ]]; then
    # Uncomment the line below to set a custom data directory.
    # Otherwise, jobagent's default resolution will be used.
    # export JOBAGENT_DATA_DIR="$HOME/.local/share/jobagent"
    :
fi

# Ensure the data directory exists and is initialized.
# This is a no-op if already initialized.
python3 -m jobagent init 2>&1 || true

# Determine the log file path under the data directory.
# Use the data directory jobagent would use if not overridden.
if [[ -n "$JOBAGENT_DATA_DIR" ]]; then
    DATA_DIR="$JOBAGENT_DATA_DIR"
else
    DATA_DIR="$(python3 -c 'from jobagent.core.paths import default_data_dir; print(default_data_dir())')"
fi

LOG_FILE="$DATA_DIR/jobagent-daily.log"

# Build the --source arguments from JOBAGENT_DAILY_SOURCES, a whitespace-separated
# list of `jobagent fetch` source names. Source names never contain spaces, so a
# plain split is enough. Unset, empty, or only whitespace all mean the defaults:
# a run with no sources would fetch nothing and look like a quiet day.
SOURCES=()
read -ra SOURCES <<<"${JOBAGENT_DAILY_SOURCES:-}"
if [[ ${#SOURCES[@]} -eq 0 ]]; then
    SOURCES=("workday:rbc" "workday:bmo" "workday:td")
fi

# Build the --source arguments array
DAILY_ARGS=()
for source in "${SOURCES[@]}"; do
    DAILY_ARGS+=(--source "$source")
done

# Append to the log file with timestamp.
# Redirect both stdout and stderr to the log.
# The exit code is captured inside the block: a `{ ...; }` group's status is its
# last command's, which would be the "completed" echo and always 0. Braces run in
# this shell, so the variable survives the block.
DAILY_EXIT_CODE=0
{
    echo "=== jobagent daily run at $(date -u) ==="
    python3 -m jobagent daily "${DAILY_ARGS[@]}" || DAILY_EXIT_CODE=$?
    echo "=== completed at $(date -u) with exit code $DAILY_EXIT_CODE ==="
} >> "$LOG_FILE" 2>&1

# Post a notification if enabled (default: on).
# The notification carries counts only, never company names or job titles.
# Lock-screen visibility of employer names is the most sensitive data this tool holds.
if [[ "${JOBAGENT_NOTIFY:-1}" != "0" ]]; then
    if [[ $DAILY_EXIT_CODE -eq 0 ]]; then
        # Count from digest --no-record: --no-record matters, or this read would
        # mark the queue as seen (#98). "New" means since the owner last ran
        # `jobagent digest`, not since today, so the text says that. A digest that
        # can't be read is reported as such rather than as a quiet day.
        NEW_COUNT=$(python3 -m jobagent digest --json --no-record 2>/dev/null | python3 -c "
import sys, json
try:
    print(len(json.load(sys.stdin)['new']))
except Exception:
    print('?')
")

        if [[ "$NEW_COUNT" == "?" || -z "$NEW_COUNT" ]]; then
            NOTIFICATION_TEXT="Daily run finished, but the digest couldn't be read — see jobagent-daily.log"
        elif [[ "$NEW_COUNT" -eq 0 ]]; then
            NOTIFICATION_TEXT="Nothing new since you last looked"
        elif [[ "$NEW_COUNT" -eq 1 ]]; then
            NOTIFICATION_TEXT="1 new posting since you last looked"
        else
            NOTIFICATION_TEXT="$NEW_COUNT new postings since you last looked"
        fi
    else
        # Failure: daily exited with an error.
        NOTIFICATION_TEXT="Daily run had failures — see jobagent-daily.log"
    fi

    # Post the notification using osascript.
    # Pass the message as an argument to avoid quoting issues.
    osascript -e 'on run argv' -e 'display notification (item 1 of argv) with title "jobagent"' -e 'end run' "$NOTIFICATION_TEXT" 2>/dev/null || true
fi

exit $DAILY_EXIT_CODE
