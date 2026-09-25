#!/bin/bash
# Build the runtime the scheduled `jobagent daily` runs from, and install its plist.
#
# macOS privacy protection (TCC) stops launchd jobs reading ~/Documents, where the
# repo and its .venv live, so the job runs from a copy outside it:
#
#   <runtime>/venv          the repo's .venv, its editable .pth repointed at <runtime>/src
#   <runtime>/src           the repo's src/
#   <runtime>/run-daily.sh  the wrapper, which finds <runtime>/venv beside itself
#
# <runtime> is $JOBAGENT_RUNTIME_DIR, default ~/.local/share/jobagent-runtime.
# Idempotent: run it again (`make schedule`) after every pull to refresh the copy.
# It installs nothing from the network and never loads the job; it prints the
# launchctl commands instead. Written for macOS /bin/bash 3.2.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
RUNTIME_DIR="${JOBAGENT_RUNTIME_DIR:-$HOME/.local/share/jobagent-runtime}"
PLIST_FILE="$HOME/Library/LaunchAgents/com.jobagent.daily.plist"
LOGS_DIR="$HOME/Library/Logs"

if [[ ! -x "$REPO_DIR/.venv/bin/python" ]]; then
    echo "error: no virtual environment at $REPO_DIR/.venv -- run 'make install' first" >&2
    exit 1
fi

echo "repo:    $REPO_DIR"
echo "runtime: $RUNTIME_DIR"
echo "plist:   $PLIST_FILE"
mkdir -p "$RUNTIME_DIR" "$(dirname "$PLIST_FILE")" "$LOGS_DIR"

rsync -a --delete "$REPO_DIR/.venv/" "$RUNTIME_DIR/venv/"
rsync -a --delete "$REPO_DIR/src/" "$RUNTIME_DIR/src/"
cp "$SCRIPT_DIR/run-daily.sh" "$RUNTIME_DIR/run-daily.sh"
chmod 755 "$RUNTIME_DIR/run-daily.sh"

# The editable install's .pth holds the one path jobagent is imported from. The
# rsync above just restored the repo's copy, so this rewrite runs every time.
PTH_FILES=$(find "$RUNTIME_DIR/venv/lib" -path '*/site-packages/__editable__.jobagent-*.pth')
if [[ -z "$PTH_FILES" || $(echo "$PTH_FILES" | wc -l) -ne 1 ]]; then
    echo "error: expected one __editable__.jobagent-*.pth in the venv, found: ${PTH_FILES:-none}" >&2
    echo "the runtime needs an editable install ('make install')" >&2
    exit 1
fi
echo "$RUNTIME_DIR/src" > "$PTH_FILES"

RESOLVED=$("$RUNTIME_DIR/venv/bin/python" -c 'import jobagent; print(jobagent.__file__)')
case "$RESOLVED" in
    "$RUNTIME_DIR/src/"*) echo "jobagent resolves to $RESOLVED" ;;
    *) echo "error: runtime imports jobagent from $RESOLVED, not $RUNTIME_DIR/src" >&2; exit 1 ;;
esac

# Write the plist from the template, carrying over the two keys the owner edits
# (EnvironmentVariables, StartCalendarInterval) from an installed one. plistlib
# rather than PlistBuddy so this path runs, and is tested, off a Mac too.
"$RUNTIME_DIR/venv/bin/python" - "$SCRIPT_DIR/com.jobagent.daily.plist.template" \
    "$PLIST_FILE" "$RUNTIME_DIR/run-daily.sh" "$LOGS_DIR" <<'PY'
import os
import plistlib
import sys

template, target, script, logs = sys.argv[1:]
with open(template, "rb") as f:
    plist = plistlib.load(f)
plist["ProgramArguments"] = [script]
plist["StandardOutPath"] = os.path.join(logs, "jobagent-daily.out.log")
plist["StandardErrorPath"] = os.path.join(logs, "jobagent-daily.err.log")
if os.path.exists(target):
    with open(target, "rb") as f:
        installed = plistlib.load(f)
    for key in ("EnvironmentVariables", "StartCalendarInterval"):
        if key in installed:
            plist[key] = installed[key]
            print(f"kept {key} from the installed plist")
with open(target, "wb") as f:
    plistlib.dump(plist, f)
PY

if command -v plutil >/dev/null 2>&1; then
    plutil -lint "$PLIST_FILE"
else
    echo "plutil not found (not macOS?); skipped plutil -lint"
fi

cat <<EOF

Runtime ready. This script does not load the job. To (re)load it:
  launchctl unload "$PLIST_FILE" 2>/dev/null
  launchctl load "$PLIST_FILE"
launchd's own output goes to $LOGS_DIR/jobagent-daily.{out,err}.log.
Run 'make schedule' again after every pull, or the job keeps running old code.
EOF
