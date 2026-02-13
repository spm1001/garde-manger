# Memory CLI Reference

Full command reference for `garde` CLI. All commands require `uv run` from `~/Repos/garde-manger`.

---

## garde search

Full-text search across indexed sources using FTS5.

```bash
uv run garde search "query"
```

### Options

| Flag | Description | Example |
|------|-------------|---------|
| `--type TYPE` | Filter by source type | `--type claude_code` |
| `--project PATH` | Filter by project path | `--project .` (current dir) |
| `-n, --limit N` | Max results (default: 10) | `-n 20` |

### Source Types

- `claude_code` — Local Claude Code sessions (JSONL from `~/.claude/projects/`)
- `handoff` — Session handoff files (from `~/.claude/handoffs/`)
- `claude_ai` — Claude.ai conversations (synced via claude-data-sync)
- `cloud_session` — Claude Code web sessions

### Search Syntax

**Basic search:**
```bash
uv run garde search "entity resolution"
```

**Hyphenated terms:** Auto-quoted by CLI
```bash
uv run garde search "claude-memory"  # Works (auto-quoted internally)
```

**Exact phrase:**
```bash
uv run garde search '"extraction pipeline"'  # Explicit quoting
```

**What's indexed:**
- Extraction summaries (arc, learnings, patterns, builds, friction)
- Titles
- Source metadata (project_path, updated_at)

### Examples

```bash
# Search all sources
uv run garde search "JWT authentication"

# Current project only
uv run garde search "deployment" --project .

# Only handoffs
uv run garde search "phase 3" --type handoff

# More results
uv run garde search "MCP server" -n 25
```

---

## garde drill

View source details with progressive disclosure.

```bash
uv run garde drill <source_id>
```

### Modes

| Flag | What it shows |
|------|---------------|
| (none) | Extraction summary only (arc, learnings, builds, patterns) |
| `--outline` | Extraction + numbered turn index |
| `--turn N` | Specific turn in full |
| `--full` | All turns (truncated if large) |

### Progressive Disclosure Pattern

1. **Default:** Read extraction summary first
2. **If not enough:** Use `--outline` to see turn index
3. **If specific context needed:** Use `--turn N` for that turn

### Examples

```bash
# View extraction summary
uv run garde drill claude_code:28478c48-ba93-47ea-9741-e6cf1215e9e0

# See turn structure
uv run garde drill claude_code:28478c48 --outline

# Read turn 5 in full
uv run garde drill claude_code:28478c48 --turn 5

# Full conversation (if really needed)
uv run garde drill claude_code:28478c48 --full
```

---

## garde recent

Show recent activity, optionally filtered to current project.

```bash
uv run garde recent
```

### Options

| Flag | Description | Default |
|------|-------------|---------|
| `--all` | All sources (ignore project detection) | Project-filtered |
| `--days N` | Lookback period | 7 |
| `--type TYPE` | Filter by source type | All types |

### Project Detection

When run from a git repo, `garde recent` auto-detects the project and filters to matching sources. Uses path encoding: `/Users/jane/Repos/foo` → `-Users-jane-Repos-foo`.

Outside a git repo, defaults to all sources.

### Examples

```bash
# Current project's recent activity
uv run garde recent

# All sources, last 2 weeks
uv run garde recent --all --days 14

# Only handoffs from current project
uv run garde recent --type handoff
```

---

## garde status

Show database statistics and extraction coverage.

```bash
uv run garde status
```

### Output

- Total sources by type
- Extraction coverage (% with extractions)
- Last scan timestamp
- Database size

### When to Use

- Before searching, to verify database is populated
- After `garde scan` to confirm indexing worked
- Debugging "no results" issues

---

## garde scan

Index sources into the database. Run periodically to pick up new sessions.

```bash
uv run garde scan
```

### Options

| Flag | Description |
|------|-------------|
| `--source TYPE` | Only scan specific source type |
| `--quiet` | Minimal output |

### Source Types for Scan

- `claude_code` — `~/.claude/projects/**/*.jsonl`
- `handoffs` — `~/.claude/handoffs/**/*.md`
- `claude_ai` — `~/.claude/claude-ai/cache/conversations/`
- `cloud_sessions` — `~/.claude/claude-ai/cache/sessions/`

### Examples

```bash
# Full scan
uv run garde scan

# Just handoffs
uv run garde scan --source handoffs
```

---

## garde backfill

Run LLM extraction on sources without extractions.

```bash
uv run garde backfill
```

### Options

| Flag | Description |
|------|-------------|
| `--source-type TYPE` | Only backfill specific type |
| `--limit N` | Max sources to process |
| `--dry-run` | Show what would be processed |

### Prerequisites

- API key in `~/.claude/memory/env`
- Sources must be scanned first (`garde scan`)

### Examples

```bash
# Backfill all pending
uv run garde backfill

# Only handoffs
uv run garde backfill --source-type handoff

# Preview
uv run garde backfill --dry-run
```

---

## garde sync-fts

Update FTS index with extraction content. Run after backfill to make learnings searchable.

```bash
uv run garde sync-fts
```

### When to Use

After running `garde backfill`, extraction summaries need to be flattened into FTS. This command does that.

**The pipeline:**
```
garde scan → garde backfill → garde sync-fts
```

---

## garde list

List sources with optional filtering.

```bash
uv run garde list
```

### Options

| Flag | Description |
|------|-------------|
| `--type TYPE` | Filter by source type |
| `--limit N` | Max results |
| `--has-extraction` | Only sources with extractions |
| `--no-extraction` | Only sources without extractions |

---

## Common Patterns

### Full refresh
```bash
uv run garde scan && uv run garde backfill && uv run garde sync-fts
```

### Check coverage then search
```bash
uv run garde status
uv run garde search "topic"
```

### Triage → drill workflow
```bash
uv run garde search "authentication"
# Pick a result
uv run garde drill claude_code:abc123
# Need more detail on turn 7
uv run garde drill claude_code:abc123 --turn 7
```
