#!/bin/bash
# SessionEnd hook: index the closing session and consume any staged extraction.
#
# All logic lives in `garde ingest-session` (Python). This script is a thin
# wrapper: subagent guards, CLI check, stdin parsing, then one command.
#
# Fast path (from /close): index + store staged extraction (no LLM, seconds)
# Safety-net path: index only (extraction deferred to `garde backfill`)

# Subagent guards (critical — fork bomb prevention)
# garde's LLM pipeline sets GARDE_SUBAGENT=1 in subprocess env.
# Without this guard, claude -p → hook → claude -p → hook → ...
[ -n "${GARDE_SUBAGENT:-}" ] && exit 0
[ -n "${MEM_SUBAGENT:-}" ] && exit 0
[ -n "${CLAUDE_SUBAGENT:-}" ] && exit 0

# Ensure CLI is in PATH
export PATH="$HOME/.local/bin:$PATH"
command -v garde &>/dev/null || exit 0

# Read hook input (JSON with session_id, cwd)
HOOK_INPUT=$(cat)

SESSION_ID=$(python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('session_id',''))" <<< "$HOOK_INPUT" 2>/dev/null || true)
HOOK_CWD=$(python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('cwd',''))" <<< "$HOOK_INPUT" 2>/dev/null || true)
[ -z "$HOOK_CWD" ] && HOOK_CWD="$(pwd -P)"

# Need session ID to proceed
[ -z "$SESSION_ID" ] && exit 0

# Log to file (not /dev/null — future Claudes need debugging)
LOGFILE="$HOME/.claude/logs/garde.log"
mkdir -p "$(dirname "$LOGFILE")"

# Single command does everything: find file, index, consume staged extraction
garde ingest-session --session-id "$SESSION_ID" --cwd "$HOOK_CWD" \
    >> "$LOGFILE" 2>&1 || true

exit 0
