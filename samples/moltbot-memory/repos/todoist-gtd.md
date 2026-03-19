# todoist-gtd

**Location:** `~/Repos/todoist-gtd`

## What It Does

todoist-gtd is a Python CLI for Todoist that understands GTD semantics — outcomes vs actions, team priorities, waiting-fors, weekly reviews. It's designed as both a standalone CLI and a Claude Code skill, teaching Claude the vocabulary and structure needed to work with Todoist effectively. Uses OAuth for authentication with tokens stored securely in macOS Keychain.

## Key Files & Structure

```
todoist-gtd/
├── SKILL.md              # Claude Code skill definition
├── scripts/
│   ├── todoist.py        # Main CLI (26KB) - all commands
│   ├── todoist_auth.py   # OAuth flow implementation
│   ├── todoist_secrets.py # Keychain integration
│   ├── install.sh        # Creates wrapper, installs deps
│   └── client_credentials.json.template
├── references/
│   ├── TERMINOLOGY.md    # GTD vocabulary
│   ├── PATTERNS.md       # Query patterns
│   └── COACHING.md       # Outcome quality examples
└── requirements.txt
```

## How It's Used

```bash
# Install
cd ~/Repos/todoist-gtd
scripts/install.sh
todoist auth      # OAuth flow (opens browser)

# CLI commands
todoist projects                    # List projects
todoist tasks --project "@Work"     # Tasks in project
todoist filter "today"              # Todoist filter syntax
todoist add "Review proposal" --project "@Work" --section "Now"
todoist done <task-id>
todoist doctor                      # Diagnose setup issues
```

**As Claude skill:** Install via batterie-de-savoir plugin marketplace

**Triggers:** "check my @Claude inbox", "what's waiting for?", "weekly review"

## Notable Patterns

1. **GTD-native:** Maps GTD concepts to Todoist — outcomes as sections, waiting-fors with labels, 3-tier priority ontology
2. **Outcome coaching:** Skill teaches Claude difference between activity language ("Review proposal") and achievement language ("Decision made on proposal")
3. **Secure auth:** OAuth tokens in Keychain (not files), client credentials gitignored, supports `--manual` for headless servers
4. **Reference docs:** Separate files for terminology, patterns, coaching — keeps SKILL.md focused while providing depth
5. **Doctor command:** Self-diagnosing CLI that checks auth, connectivity, and config issues
