# claude-suite

**Location:** `~/Repos/claude-suite`

## What It Does

claude-suite (now **trousse**) is a collection of behavioral skills that enhance Claude Code's capabilities. It provides session lifecycle management (startup context, handoffs between sessions), quality tools (multi-lens code review), and utility skills (diagrams, screenshots, filing). Skills are installed via the plugin system and configured hooks provide automatic session management.

## Key Files & Structure

```
trousse/
├── .claude-plugin/     # Plugin manifest and configuration
├── skills/
│   ├── session-start/  # Shows time, handoffs, ready work on startup
│   ├── session-close/  # Creates handoff for next session (/close)
│   ├── titans/         # Three-lens code review (/titans, /review)
│   ├── diagram/        # Iterative diagram creation (/diagram)
│   ├── screenshot/     # Screen capture verification (/screenshot)
│   ├── filing/         # PARA-method file organization (/filing)
│   ├── picture/        # AI image generation (/picture)
│   ├── server-checkup/ # Linux server management
│   ├── github-cleanup/ # Stale fork auditing
│   ├── sprite/         # Sprites.dev VM management
│   └── beads/          # Issue tracking integration
├── hooks/              # Hook scripts for session lifecycle
└── references/         # Supporting documentation
```

## How It's Used

```bash
# Install via plugin system
claude plugin install spm1001/trousse
# Or via marketplace
/plugin marketplace add spm1001/batterie-de-savoir
```

**Commands after install:**
- `/open` — Resume context from previous session
- `/close` — Create handoff for next session
- `/titans` or `/review` — Three-lens code review (hindsight, craft, foresight)
- `/diagram` — Create diagrams with iterative render-and-check

**Updating:** Plugin updates are managed through the plugin system.

## Notable Patterns

1. **Plugin architecture:** Skills are installed via plugins, enabling easy updates through the plugin system
2. **Session continuity:** Startup/close hooks solve Claude's "fresh session" problem by persisting context
3. **Three-lens review:** `/titans` applies hindsight (what went wrong before), craft (code quality), and foresight (future risks)
4. **Optional tools:** External plugins (todoist-gtd, garde-manger) integrate as additional skills
