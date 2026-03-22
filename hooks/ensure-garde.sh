#!/bin/bash
# SessionStart hook: ensure garde CLI is available and version-aligned.
# Silent when everything is fine; helpful when it's not.

# Skip for subagent invocations (fork bomb prevention)
[ -n "${GARDE_SUBAGENT:-}" ] && exit 0
[ -n "${MEM_SUBAGENT:-}" ] && exit 0
[ -n "${CLAUDE_SUBAGENT:-}" ] && exit 0

# Ensure ~/.local/bin is in PATH (where uv tool install puts binaries)
export PATH="$HOME/.local/bin:$PATH"

ISSUES=""

# Check 1: garde CLI available
if ! command -v garde &>/dev/null; then
    PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-}"
    if [ -n "$PLUGIN_ROOT" ] && [ -f "$PLUGIN_ROOT/pyproject.toml" ]; then
        INSTALL_HINT="uv tool install \"$PLUGIN_ROOT\""
    else
        INSTALL_HINT="uv tool install garde-manger"
    fi
    ISSUES="${ISSUES}• garde CLI not found. Install it:\n\n  ${INSTALL_HINT}\n\n  Then ensure ~/.local/bin is in your PATH.\n"
fi

# Check 2: version alignment (only if CLI found)
if [ -z "$ISSUES" ]; then
    PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-}"
    if [ -n "$PLUGIN_ROOT" ] && [ -f "$PLUGIN_ROOT/.claude-plugin/plugin.json" ]; then
        INSTALLED=$(garde --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' || true)
        EXPECTED=$(python3 -c "import json; print(json.load(open('$PLUGIN_ROOT/.claude-plugin/plugin.json'))['version'])" 2>/dev/null || true)
        if [ -n "$INSTALLED" ] && [ -n "$EXPECTED" ] && [ "$INSTALLED" != "$EXPECTED" ]; then
            ISSUES="${ISSUES}• garde CLI is v${INSTALLED} but plugin is v${EXPECTED}. Update:\n\n  uv tool install \"$PLUGIN_ROOT\" --force --reinstall\n"
        fi
    fi
fi

# If no issues, exit silently
[ -z "$ISSUES" ] && exit 0

cat <<EOF
{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "⚠️ garde-manger needs attention:\n\n${ISSUES}\nLogs: ~/.claude/logs/garde.log"}}
EOF
