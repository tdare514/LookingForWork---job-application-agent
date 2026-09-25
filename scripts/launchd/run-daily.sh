#!/bin/bash
# Wrapper script to run `jobagent daily` on a schedule.
#
# This script activates the project's virtual environment, sets environment
# variables, and runs `jobagent daily` with a fixed source list, logging to
# a file under the data directory.
#
# It is intended to be called by launchd via the plist at com.jobagent.daily.plist.template.

set -e

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

# Build the --source arguments from JOBAGENT_DAILY_SOURCES.
# If unset or empty, default to the standard Workday tenants.
if [[ -n "$JOBAGENT_DAILY_SOURCES" ]]; then
    # Split the space-separated source list into an array, preserving quotes.
    read -ra SOURCES <<<"$JOBAGENT_DAILY_SOURCES"
else
    # Default sources: RBC, BMO, and TD Workday tenants
    SOURCES=("workday:rbc" "workday:bmo" "workday:td")
fi

# Build the --source arguments array
DAILY_ARGS=()
for source in "${SOURCES[@]}"; do
    DAILY_ARGS+=(--source "$source")
done

# Append to the log file with timestamp.
# Redirect both stdout and stderr to the log.
{
    echo "=== jobagent daily run at $(date -u) ==="
    python3 -m jobagent daily "${DAILY_ARGS[@]}"
    echo "=== completed at $(date -u) ==="
} >> "$LOG_FILE" 2>&1

exit 0
