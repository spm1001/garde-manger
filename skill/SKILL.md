---
name: garde
description: Search and retrieve context from past Claude sessions. Triggers on 'search memory', 'find past sessions', 'what did we learn about', 'have we done this before', 'what did we decide about', 'what did I work on yesterday', 'remind me what we did', or when disoriented about past work ("I'm lost", "where were we?"). (user)
---

## Reference Files Quick Index

**When you need...**
- Full CLI reference → `references/COMMANDS.md`
- Search workflow patterns → `references/WORKFLOWS.md`
- Troubleshooting → `references/TROUBLESHOOTING.md`

Read SKILL.md first, then load specific references as needed.

---

# Memory Primitives

Search and retrieve context from past Claude sessions.

## When to Use

**Automatic triggers:**
- User asks about past work: "What did we decide...", "Have we done this before...", "When did we..."
- Daily recap requests: "What did I work on yesterday?", "Remind me what we did"
- User seems confused about context: "Didn't we already...", "I thought we..."
- Starting work on a topic with likely history

## When NOT to Use

- Simple question-answering (no history needed)
- Work with clear handoff context already loaded
- Greenfield projects with no session history
- Single-session tasks with no prior context

---

## Core Primitives

All commands require `uv run` from `~/Repos/garde-manger`:

### 1. Search

```bash
uv run garde search "query"              # FTS5 full-text search
uv run garde search "query" --type X     # Filter by source type
uv run garde search "query" --project .  # Current project only
uv run garde search "query" -n 20        # More results (default: 10)
```

**Source types:** `claude_code`, `handoff`, `claude_ai`, `cloud_session`

### 2. Drill (Progressive Disclosure)

```bash
uv run garde drill <id>              # Extraction summary (default)
uv run garde drill <id> --outline    # Extraction + numbered turn index
uv run garde drill <id> --turn N     # Specific turn in full
uv run garde drill <id> --full       # All turns (truncated)
```

### 3. Recent

```bash
uv run garde recent              # Current project's recent activity
uv run garde recent --all        # All sources
uv run garde recent --days 14    # Custom timeframe (default: 7)
uv run garde recent --all --by-project  # Group by project with session counts
```

**Daily recap pattern:** `--all --by-project` shows "infra-openwrt (8 sessions)" style summary — useful for "what did I work on yesterday?"

### 4. Status

```bash
uv run garde status              # Database stats and coverage
```

---

## Progressive Disclosure Pattern

**The unfolding label:** Don't load full conversations immediately.

```
Search → Find relevant sources by keyword
   ↓
Triage → Read extraction summaries (arc, learnings, builds)
   ↓
Drill  → Only load full content if extraction isn't enough
```

**Extraction summaries include:**
- **Arc:** Started → Turns → Ended (conversation shape)
- **Builds:** What was created
- **Learnings:** Insights with "why it matters"
- **Patterns:** Reusable approaches discovered
- **Open threads:** Unfinished work

The extraction is decision support for whether to drill deeper—not a replacement for full context when details matter.

---

## Feedback: Filing Issues

When encountering problems with memory search or quality, file a structured bead. This helps improve the system.

### When to File (Without Asking User)

- Search returning wrong/no results for known content
- Extraction missing key learnings or builds
- CLI errors or crashes
- Skill not triggering on expected phrases

### Structured Templates

**Search issues:**
```bash
bd create "memory: search not finding [topic]" \
  --type bug \
  --description "Query '[query]' should find [expected] but returns [actual]" \
  --design "$(cat <<'EOF'
## Query Details
- Query: [exact query string]
- Filters: [--type, --project if used]
- Source ID (if known): [where content exists]

## Expected
[What should be found]

## Actual
[What was returned]
EOF
)"
```

**Extraction quality:**
```bash
bd create "memory: extraction missing [type]" \
  --type bug \
  --description "Source [id] missing [learnings/builds/arc]" \
  --design "$(cat <<'EOF'
## Source
- ID: [source_id]
- Topic: [what the session was about]

## Missing
[What should have been extracted]

## Why It Matters
[Impact on search/discovery]
EOF
)"
```

**CLI bugs:**
```bash
bd create "memory: [brief error]" \
  --type bug \
  --description "[Error message]" \
  --design "$(cat <<'EOF'
## Command
[Exact command run]

## Expected
[What should happen]

## Actual
[Error or unexpected behavior]
EOF
)"
```

**Skill discovery:**
```bash
bd create "memory: skill not triggering on '[phrase]'" \
  --type enhancement \
  --description "Expected memory skill on '[phrase]' but didn't trigger" \
  --design "$(cat <<'EOF'
## Trigger Phrase
[What user said]

## Why It Should Trigger
[Reasoning]

## Suggested Addition
[Phrase to add to description]
EOF
)"
```

---

## Anti-Patterns

| Anti-Pattern | Problem | Fix |
|--------------|---------|-----|
| Loading full content first | Token waste, slow | Use progressive disclosure |
| Searching without type filter | Noisy results | Add `--type` for precision |
| Ignoring extraction summary | Missing the "unfolding label" | Check arc/learnings first |
| Filing vague bug reports | Hard to reproduce | Use structured templates above |
| Searching after handoff loaded | Already have context | Check handoff/beads first |

---

## Integration Points

**Consumed by:**
- `/open` command → can check recent activity

**Depends on:**
- `garde` CLI installed (via `uv run garde` from ~/Repos/garde-manger)
- Database populated (`garde scan` has been run)
- API key for extraction (`~/.claude/memory/env`)

---

## Quick Reference

| Task | Command |
|------|---------|
| Search all sources | `uv run garde search "query"` |
| Search current project | `uv run garde search "query" --project .` |
| Recent activity | `uv run garde recent` |
| Daily recap (by project) | `uv run garde recent --all --by-project --days 1` |
| View extraction | `uv run garde drill <id>` |
| View specific turn | `uv run garde drill <id> --turn N` |
| Check coverage | `uv run garde status` |

**For detailed CLI reference:** See `references/COMMANDS.md`
