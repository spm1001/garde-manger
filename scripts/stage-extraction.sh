#!/usr/bin/env bash
# stage-extraction.sh — place extraction JSON in pending-extractions with the correct filename
#
# Usage:
#   cat extraction.json | stage-extraction.sh
#   stage-extraction.sh < extraction.json
#
# Always uses pwd -P as the project directory. /close pre-flight guarantees
# Claude is in the session's home directory before this script runs.
#
# The filename must match what session-end.sh expects: the full UUID from
# the session's .jsonl file. This script computes that — the caller never
# needs to know it.

set -euo pipefail

PROJECT_DIR=$(pwd -P)
ENCODED=$(echo "$PROJECT_DIR" | sed 's/[^a-zA-Z0-9-]/-/g')
SESSIONS_DIR="$HOME/.claude/projects/$ENCODED"
PENDING_DIR="$HOME/.claude/.pending-extractions"

# Find most recent non-agent session for this project
SESSION_ID=$(ls -t "$SESSIONS_DIR"/*.jsonl 2>/dev/null \
    | grep -v agent \
    | head -1 \
    | xargs -I{} basename {} .jsonl 2>/dev/null \
    || true)

if [ -z "$SESSION_ID" ]; then
    echo "stage-extraction: no session found in $SESSIONS_DIR" >&2
    exit 1
fi

mkdir -p "$PENDING_DIR"
DEST="$PENDING_DIR/${SESSION_ID}.json"

cat > "$DEST"
echo "Staged extraction → $DEST" >&2
