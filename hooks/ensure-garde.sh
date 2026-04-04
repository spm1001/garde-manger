#!/bin/bash
# SessionStart hook: ensure garde CLI is available and version-aligned.
# Auto-fixes drift; reports what it did. Silent when everything is fine.

# Skip for subagent invocations (fork bomb prevention)
[ -n "${GARDE_SUBAGENT:-}" ] && exit 0
[ -n "${MEM_SUBAGENT:-}" ] && exit 0
[ -n "${CLAUDE_SUBAGENT:-}" ] && exit 0

export PATH="$HOME/.local/bin:$PATH"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-}"
FIXED=""
ISSUES=""

# Resolve install source
if [ -n "$PLUGIN_ROOT" ] && [ -f "$PLUGIN_ROOT/pyproject.toml" ]; then
    INSTALL_SRC="$PLUGIN_ROOT"
else
    INSTALL_SRC="garde-manger"
fi

# Check 1: CLI missing → auto-install
if ! command -v garde &>/dev/null; then
    if uv tool install "$INSTALL_SRC" --force --reinstall >/dev/null 2>&1; then
        FIXED="${FIXED}• garde CLI installed\n"
    else
        ISSUES="${ISSUES}• garde CLI not found and auto-install failed. Run manually:\n\n  uv tool install \"$INSTALL_SRC\"\n"
    fi
fi

# Check 2: version drift → auto-update
if [ -z "$ISSUES" ] && command -v garde &>/dev/null; then
    if [ -n "$PLUGIN_ROOT" ] && [ -f "$PLUGIN_ROOT/.claude-plugin/plugin.json" ]; then
        INSTALLED=$(garde --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' || true)
        EXPECTED=$(python3 -c "import json; print(json.load(open('$PLUGIN_ROOT/.claude-plugin/plugin.json'))['version'])" 2>/dev/null || true)
        if [ -n "$INSTALLED" ] && [ -n "$EXPECTED" ] && [ "$INSTALLED" != "$EXPECTED" ]; then
            CLI_BEHIND=$(python3 -c "print(tuple(int(x) for x in '$INSTALLED'.split('.')) < tuple(int(x) for x in '$EXPECTED'.split('.')))" 2>/dev/null || true)
            if [ "$CLI_BEHIND" = "True" ]; then
                if uv tool install "$INSTALL_SRC" --force --reinstall >/dev/null 2>&1; then
                    FIXED="${FIXED}• garde CLI updated: v${INSTALLED} → v${EXPECTED}\n"
                else
                    ISSUES="${ISSUES}• garde CLI is v${INSTALLED} but plugin is v${EXPECTED}. Auto-update failed.\n"
                fi
            fi
        fi
    fi
fi

# Silent exit if nothing happened
[ -z "$FIXED" ] && [ -z "$ISSUES" ] && exit 0

# Report
MSG=""
[ -n "$FIXED" ] && MSG="${MSG}✓ garde auto-fixed:\n\n${FIXED}"
[ -n "$ISSUES" ] && MSG="${MSG}⚠️ garde-manger needs attention:\n\n${ISSUES}"

cat <<EOF
{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "${MSG}"}}
EOF
