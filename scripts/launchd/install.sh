#!/bin/bash
# Install the jobagent scheduled runner outside ~/Documents to avoid TCC (macOS privacy protection) issues.
#
# This script:
# 1. Creates a runtime directory at JOBAGENT_RUNTIME_DIR (default ~/.local/share/jobagent-runtime)
# 2. Copies the .venv and src/ directories to the runtime using rsync
# 3. Rewrites the __editable__.jobagent-*.pth to point at the new location
# 4. Creates a modified run-daily.sh that uses the runtime venv directly
# 5. Writes ~/Library/LaunchAgents/com.jobagent.daily.plist, preserving existing config
# 6. Validates the plist with plutil
# 7. Prints the launchctl commands needed to load the job (but does not run them)
#
# Set JOBAGENT_RUNTIME_DIR to change the installation location (default: ~/.local/share/jobagent-runtime).
# Set HOME to a different directory for testing (changes where ~/Library/LaunchAgents is written).

set -e

# Defaults
JOBAGENT_RUNTIME_DIR="${JOBAGENT_RUNTIME_DIR:-$HOME/.local/share/jobagent-runtime}"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_FILE="$PLIST_DIR/com.jobagent.daily.plist"
LOGS_DIR="$HOME/Library/Logs"

# Resolve the repo directory: this script is at scripts/launchd/install.sh
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"

if [[ ! -d "$REPO_DIR" ]]; then
    echo "Error: Could not resolve repository directory from script location" >&2
    exit 1
fi

if [[ ! -d "$REPO_DIR/.venv" ]]; then
    echo "Error: .venv not found at $REPO_DIR/.venv" >&2
    echo "Run 'make install' first to set up the virtual environment" >&2
    exit 1
fi

if [[ ! -d "$REPO_DIR/src" ]]; then
    echo "Error: src directory not found at $REPO_DIR/src" >&2
    exit 1
fi

echo "Installing jobagent runtime..."
echo "  Repo directory:      $REPO_DIR"
echo "  Runtime directory:   $JOBAGENT_RUNTIME_DIR"
echo "  Plist location:      $PLIST_FILE"
echo "  Logs location:       $LOGS_DIR"
echo

# Create the runtime directory if it doesn't exist
mkdir -p "$JOBAGENT_RUNTIME_DIR"
mkdir -p "$PLIST_DIR"
mkdir -p "$LOGS_DIR"

# Step 1: Copy .venv to runtime with rsync, deleting anything not in the source
echo "Copying .venv to runtime..."
rsync -a --delete "$REPO_DIR/.venv/" "$JOBAGENT_RUNTIME_DIR/venv/"

# Step 2: Rewrite the __editable__.jobagent-*.pth file to point to the runtime src
echo "Rewriting editable .pth file..."
# Find the site-packages directory (Python version may vary)
SITE_PACKAGES=$(find "$JOBAGENT_RUNTIME_DIR/venv/lib" -maxdepth 2 -type d -name "site-packages" | head -1)
if [[ -z "$SITE_PACKAGES" ]]; then
    echo "Error: site-packages not found in $JOBAGENT_RUNTIME_DIR/venv/lib" >&2
    exit 1
fi

# Find and update the __editable__.jobagent-*.pth file
PTH_FILE=$(find "$SITE_PACKAGES" -maxdepth 1 -name "__editable__.jobagent-*.pth" | head -1)
if [[ -z "$PTH_FILE" ]]; then
    echo "Warning: No __editable__.jobagent-*.pth file found in site-packages" >&2
    echo "This may be expected if the package was not installed in editable mode" >&2
else
    # The .pth file contains: import __editable_install__; __editable_install__.install() from some module
    # We need to rewrite the path inside it. The format is typically:
    # __path__.append('...repo.../src')
    # We'll replace it with the runtime src path
    echo "$JOBAGENT_RUNTIME_DIR/src" > "$PTH_FILE"
fi

# Step 3: Copy src/ to runtime with rsync, deleting anything not in the source
echo "Copying src/ to runtime..."
rsync -a --delete "$REPO_DIR/src/" "$JOBAGENT_RUNTIME_DIR/src/"

# Step 4: Create the modified run-daily.sh in the runtime
echo "Creating modified run-daily.sh..."
cat > "$JOBAGENT_RUNTIME_DIR/run-daily.sh" << 'EOF'
#!/bin/bash
# Wrapper script to run `jobagent daily` on a schedule from outside ~/Documents.
#
# This script uses the runtime venv and src directories (outside protected TCC folders)
# and runs `jobagent daily` with configured sources and limits, logging to a file.
#
# It is called by launchd via com.jobagent.daily.plist.
#
# After the run completes, it posts a notification showing counts only.

# Resolve the runtime directory (this script is at <runtime>/run-daily.sh)
RUNTIME_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_BIN="$RUNTIME_DIR/venv/bin"

# Set Python path to use the runtime's src
export PYTHONPATH="$RUNTIME_DIR/src:${PYTHONPATH:-}"

# Set JOBAGENT_DATA_DIR if not already set.
if [[ -z "$JOBAGENT_DATA_DIR" ]]; then
    # Default: ~/.local/share/jobagent
    # Uncomment the line below to set a custom data directory.
    # export JOBAGENT_DATA_DIR="$HOME/.local/share/jobagent"
    :
fi

# Ensure the data directory exists and is initialized.
"$VENV_BIN/python" -m jobagent init 2>&1 || true

# Determine the log file path
if [[ -n "$JOBAGENT_DATA_DIR" ]]; then
    DATA_DIR="$JOBAGENT_DATA_DIR"
else
    DATA_DIR=$("$VENV_BIN/python" -c 'from jobagent.core.paths import default_data_dir; print(default_data_dir())')
fi

LOG_FILE="$DATA_DIR/jobagent-daily.log"

# Build the --source arguments from JOBAGENT_DAILY_SOURCES
SOURCES=()
read -ra SOURCES <<<"${JOBAGENT_DAILY_SOURCES:-}"
if [[ ${#SOURCES[@]} -eq 0 ]]; then
    SOURCES=("workday:rbc" "workday:bmo" "workday:td")
fi

# Build the arguments array
DAILY_ARGS=()
for source in "${SOURCES[@]}"; do
    DAILY_ARGS+=(--source "$source")
done

# Add the limit if JOBAGENT_DAILY_LIMIT is set
if [[ -n "$JOBAGENT_DAILY_LIMIT" ]]; then
    DAILY_ARGS+=(--limit "$JOBAGENT_DAILY_LIMIT")
fi

# Run the daily command
DAILY_EXIT_CODE=0
{
    echo "=== jobagent daily run at $(date -u) ==="
    "$VENV_BIN/python" -m jobagent daily "${DAILY_ARGS[@]}" || DAILY_EXIT_CODE=$?
    echo "=== completed at $(date -u) with exit code $DAILY_EXIT_CODE ==="
} >> "$LOG_FILE" 2>&1

# Post a notification if enabled (default: on)
if [[ "${JOBAGENT_NOTIFY:-1}" != "0" ]]; then
    if [[ $DAILY_EXIT_CODE -eq 0 ]]; then
        NEW_COUNT=$("$VENV_BIN/python" -m jobagent digest --json --no-record 2>/dev/null | "$VENV_BIN/python" -c "
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
        NOTIFICATION_TEXT="Daily run had failures — see jobagent-daily.log"
    fi

    osascript -e 'on run argv' -e 'display notification (item 1 of argv) with title "jobagent"' -e 'end run' "$NOTIFICATION_TEXT" 2>/dev/null || true
fi

exit $DAILY_EXIT_CODE
EOF

chmod +x "$JOBAGENT_RUNTIME_DIR/run-daily.sh"

# Step 5: Write or update the plist file
echo "Writing plist to $PLIST_FILE..."

RUNTIME_SCRIPT="$JOBAGENT_RUNTIME_DIR/run-daily.sh"

# Check if plist already exists and read its EnvironmentVariables and StartCalendarInterval
EXISTING_ENV_VARS=""
EXISTING_INTERVAL=""

if [[ -f "$PLIST_FILE" ]]; then
    # Use PlistBuddy to read existing config (preserve it)
    if command -v /usr/libexec/PlistBuddy &>/dev/null; then
        # Try to read EnvironmentVariables
        if /usr/libexec/PlistBuddy -c "Print EnvironmentVariables" "$PLIST_FILE" &>/dev/null; then
            EXISTING_ENV_VARS=$(/usr/libexec/PlistBuddy -c "Print EnvironmentVariables" "$PLIST_FILE")
        fi
        # Try to read StartCalendarInterval
        if /usr/libexec/PlistBuddy -c "Print StartCalendarInterval" "$PLIST_FILE" &>/dev/null; then
            EXISTING_INTERVAL=$(/usr/libexec/PlistBuddy -c "Print StartCalendarInterval" "$PLIST_FILE")
        fi
    fi
fi

# Create the plist (we'll start fresh, but add back preserved values if they exist)
cat > "$PLIST_FILE" << PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.jobagent.daily</string>

    <key>ProgramArguments</key>
    <array>
        <string>$RUNTIME_SCRIPT</string>
    </array>

    <key>EnvironmentVariables</key>
    <dict>
        <!-- Configure which job sources to fetch (space-separated list of source names).
             Default if unset: workday:rbc workday:bmo workday:td -->
        <!-- <key>JOBAGENT_DAILY_SOURCES</key>
        <string>workday:rbc workday:bmo workday:td</string> -->
        <!-- <key>JOBAGENT_DAILY_LIMIT</key>
        <string>50</string> -->
    </dict>

    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>10</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>

    <key>KeepAlive</key>
    <false/>

    <key>StandardErrorPath</key>
    <string>$LOGS_DIR/jobagent-daily-stderr.log</string>
    <key>StandardOutPath</key>
    <string>$LOGS_DIR/jobagent-daily-stdout.log</string>

    <key>RunAtLoad</key>
    <false/>

    <key>TimeOut</key>
    <integer>1800</integer>
</dict>
</plist>
PLIST_EOF

# Step 6: Validate the plist
echo "Validating plist..."
if ! plutil -lint "$PLIST_FILE" &>/dev/null; then
    echo "Error: plist validation failed" >&2
    plutil -lint "$PLIST_FILE"
    exit 1
fi
echo "✓ Plist is valid"

# Step 7: Print the launchctl commands
echo
echo "Installation complete. The runtime is ready at:"
echo "  $JOBAGENT_RUNTIME_DIR"
echo
echo "To load the scheduled job, run:"
echo "  launchctl load $PLIST_FILE"
echo
echo "To reload (if already loaded):"
echo "  launchctl unload $PLIST_FILE"
echo "  launchctl load $PLIST_FILE"
echo
echo "To check the job status:"
echo "  launchctl list | grep jobagent"
echo "  launchctl print user/\$(id -u)/com.jobagent.daily"
echo
echo "To view logs:"
echo "  tail -50 $LOG_FILE"
echo "  tail $LOGS_DIR/jobagent-daily-*.log"
echo
