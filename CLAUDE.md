# CLAUDE.md — garde-manger

Instructions for Claude when working in this codebase.

## What This Is

Persistent, searchable memory across Claude sessions. FTS5 search over summaries + human-in-the-loop entity resolution. Part of the kitchen brigade: **garde-manger** is the cold station — preservation, storage, retrieval.

## Key Commands

```bash
uv run garde scan                    # Index sources (free, fast)
uv run garde index <session>         # Index only, no extraction (for staged flow)
uv run garde process <session>       # Index + extract single session
uv run garde backfill --limit 100    # Batch extract (via claude -p)
uv run garde ingest-session --session-id UUID --cwd /path  # Session-end hook entry point
uv run garde search "query"          # FTS5 search
uv run garde drill <source_id>       # Load full content
uv run garde status                  # Index statistics
uv run garde prune --dry-run         # Find sources with invalid paths
uv run garde prune --yes             # Mark stale (preserves extractions)
```

## Architecture

- `src/garde/cli/` — CLI package (Click-based):
  - `__init__.py` — main group, config/glossary loading
  - `scan.py` — source discovery and indexing
  - `ingest.py` — `process`, `index`, and `ingest-session` commands
  - `extract_cmds.py` — `extract`, `backfill`, `extract-prompt`
  - `browse.py` — `search`, `drill`
  - `entities.py` — entity resolution
  - `fts.py` — FTS rebuild, `status`
  - `_helpers.py` — shared utilities
- `src/garde/database.py` — SQLite with FTS5
- `src/garde/llm.py` — LLM calls via `claude -p` (Opus 4.6, Max subscription), semantic chunking
- `src/garde/extraction.py` — Entity extraction orchestration
- `src/garde/config.py` — DB path resolution, config loading
- `src/garde/adapters/*.py` — Source format parsers (8 types). The `claude_code` adapter uses `deglacer` (shared library) for compaction-aware JSONL parsing; metadata extraction (tools, files, skills, commits) stays local.
- `hooks/` — Plugin hooks (SessionStart, SessionEnd)

## Plugin Hooks

garde-manger is a Claude Code plugin. Hooks are declared in `.claude-plugin/plugin.json`.

**SessionStart (`hooks/ensure-garde.sh`):** Checks CLI availability and version alignment with the plugin. Silent when healthy, outputs warning via `hookSpecificOutput` when not.

**SessionEnd (`hooks/session-end.sh`):** Thin wrapper around `garde ingest-session`. Indexes the closing session and consumes any staged extraction. Subagent guards prevent fork bombs.

### Session-End Flow

```
Session ends
  → session-end.sh fires
    → subagent guards (GARDE_SUBAGENT, MEM_SUBAGENT, CLAUDE_SUBAGENT)
    → garde ingest-session --session-id X --cwd Y
      → finds JSONL file at ~/.claude/projects/{encoded_cwd}/{session_id}.jsonl
      → indexes source + summary
      → extraction deferred: handoff scan produces extractions from section parse,
        sessions without handoffs use garde backfill
    → logs to ~/.claude/logs/garde.log
```

## DB Location

The database lives at `~/.claude/plugins/data/garde-manger-batterie-de-savoir/memory.db` (plugin data dir — persists across plugin version updates).

**Auto-migration:** On first run after plugin install, if the DB exists at the legacy location (`~/.claude/memory/memory.db`) and the plugin data dir exists, `get_db_path()` automatically moves the DB and leaves a symlink for backward compatibility.

**Resolution order in `config.py`:**
1. Plugin data dir (preferred)
2. Auto-migrate from legacy if plugin data dir exists
3. Legacy location (pre-plugin installs)
4. Fresh install: plugin data dir if present, else legacy

Config files (`config.yaml`, `glossary.yaml`) stay at `~/.claude/memory/` — they're user config, not plugin data.

## Handoff-Native Extraction

Handoffs are the primary source of extractions. The adapter parses markdown sections
directly into extraction fields — no LLM call needed.

**Section → extraction field mapping:**
- `Done` → `builds` (each bullet becomes `{what, details}`)
- `Gotchas` → `friction` (each bullet becomes `{problem, resolution}`)
- `Risks` → `friction` (prefixed with `[risk]`)
- `Reflection` → `learnings` (paragraphs become `{insight, why_it_matters, context}`)
- `Learned` → `patterns` (full text as single entry)
- `Next` → `open_threads` (each bullet)
- `purpose:` preamble → `summary`

**Both formats supported:**
- Old: flat h2 sections (`## Done`, `## Learned`, `## Next`)
- New (fond-v1): two zones (`## Now` with `### Gotchas/Risks/Next/Commands`, `## Compost` with `### Done/Reflection/Learned`)

**Discovery locations:**
- `~/.claude/handoffs/` (legacy)
- `.bon/handoffs/` across repos under `~/Repos/` (fond-v1)

**Model audit trail:** Extractions from section parse use `model_used: "handoff-section-parse"`.

**Staged extraction pipeline (retired):** The old `/close` → `~/.claude/.pending-extractions/` → `ingest-session` path has been removed. Handoff scan produces extractions directly. Sessions without handoffs are deferred to `garde backfill`.

## LLM Backend

All LLM calls go through `_call_claude()` in `llm.py`, which invokes `claude -p` (pipe mode). This bills against the Max subscription, not API credits. Model is `claude-opus-4-6` for everything.

**Fork bomb prevention:** `_call_claude()` sets `GARDE_SUBAGENT=1` in the subprocess environment. Session hooks must check this and exit early — otherwise `claude -p` triggers hooks that spawn more `claude -p` processes recursively. This guard is critical; do not remove it. Hooks also check `MEM_SUBAGENT` and `CLAUDE_SUBAGENT` for transition compatibility.

**Flags used:** `--allowedTools ""` disables all tools (pure text generation), `--no-session-persistence` avoids phantom sessions, `--output-format json` for parsing the `result` field.

**Model audit trail:** Database `model_used` values:
- `claude-sonnet-4-20250514` — pre-migration extractions (API-based)
- `claude-opus-4-6` — post-migration (CLI-based, Max subscription)
- `claude-code-context` — legacy in-session extraction from /close (no longer produced)
- `handoff-section-parse` — extraction from handoff markdown sections (no LLM, free)
- `skipped:content_too_short` — stub records for sources with <100 chars content

## Known Issues / Tech Debt

Adapter protocol plan is tracked in bon.

**Backfill dedup:** Backfill automatically skips `claude_code` sessions that already have a `handoff-section-parse` extraction. Matching uses `session_id` from handoff metadata (primary) or stem-based UUID prefix (fallback). The skip count is reported in backfill output.

**Backfill resilience:** Each extraction commits immediately, so interrupted backfill is resumable (just rerun). Use `nohup` for large batches — background tasks timeout. No progress counter — use `grep -c "✓" logfile` to monitor.

**`--limit 0` gotcha:** In backfill/populate commands, `--limit 0` means SQL `LIMIT 0` (returns nothing), not "unlimited". Use a large number like `--limit 10000` instead.

**Stale sources:** Sources with invalid paths are marked `status='stale'` (not deleted) to preserve extraction value. Use `garde prune --delete` for hard deletion, but extractions will be lost. Stale sources still appear in search results — filtering coming later.

## Code Review

Use `/titans` for thorough review — three parallel Opus agents (Epimetheus/hindsight, Metis/craft, Prometheus/foresight). Tested Feb 2026, found real bugs.

## Testing

```bash
uv run python -m pytest              # All tests (154)
uv run python -m pytest tests/test_X.py -v   # Specific test
```
