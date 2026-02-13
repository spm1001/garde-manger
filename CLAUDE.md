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
uv run garde search "query"          # FTS5 search
uv run garde drill <source_id>       # Load full content
uv run garde status                  # Index statistics
uv run garde prune --dry-run         # Find sources with invalid paths
uv run garde prune --yes             # Mark stale (preserves extractions)
```

## Architecture

- `src/garde/cli.py` — Main CLI (~2100 lines, needs refactoring)
- `src/garde/database.py` — SQLite with FTS5
- `src/garde/llm.py` — LLM calls via `claude -p` (Opus 4.6, Max subscription), semantic chunking
- `src/garde/extraction.py` — Entity extraction orchestration
- `src/garde/adapters/*.py` — Source format parsers (8 types)

## LLM Backend

All LLM calls go through `_call_claude()` in `llm.py`, which invokes `claude -p` (pipe mode). This bills against the Max subscription, not API credits. Model is `claude-opus-4-6` for everything.

**Fork bomb prevention:** `_call_claude()` sets `GARDE_SUBAGENT=1` in the subprocess environment. Session-start hooks must check this and exit early — otherwise `claude -p` triggers hooks that spawn more `claude -p` processes recursively. This guard is critical; do not remove it. For transition, hooks should check both `GARDE_SUBAGENT` and `MEM_SUBAGENT`.

**Flags used:** `--allowedTools ""` disables all tools (pure text generation), `--no-session-persistence` avoids phantom sessions, `--output-format json` for parsing the `result` field.

**In-session extraction (Feb 2026):** The /close skill generates extraction JSON during the session (when Claude has full context) and stages it to `~/.claude/.pending-extractions/<session_id>.json`. The session-end hook detects this file and uses `garde index` + `garde store-extraction` instead of the expensive `garde process` path. Sessions that exit without /close fall back to `garde process` as before. The `model_used` for staged extractions is `claude-code-context`.

**Model migration (Feb 2026):** Database contains four `model_used` values:
- `claude-sonnet-4-20250514` — pre-migration extractions (API-based)
- `claude-opus-4-6` — post-migration (CLI-based, Max subscription)
- `claude-code-context` — in-session extraction from /close (no subprocess)
- `skipped:content_too_short` — stub records for sources with <100 chars content

## Known Issues / Tech Debt

See `ADAPTER_AUDIT.md` for the adapter protocol plan.

**CLI monolith:** The scan command has ~450 lines of near-identical loops for 8 source types. Refactor to registry pattern is tracked in arc.

**Backfill resilience:** Each extraction commits immediately, so interrupted backfill is resumable (just rerun). Use `nohup` for large batches — background tasks timeout. No progress counter — use `grep -c "✓" logfile` to monitor.

**`--limit 0` gotcha:** In backfill/populate commands, `--limit 0` means SQL `LIMIT 0` (returns nothing), not "unlimited". Use a large number like `--limit 10000` instead.

**Stale sources:** Sources with invalid paths are marked `status='stale'` (not deleted) to preserve extraction value. Use `garde prune --delete` for hard deletion, but extractions will be lost. Stale sources still appear in search results — filtering coming later.

## Code Review

Use `/titans` for thorough review — three parallel Opus agents (Epimetheus/hindsight, Metis/craft, Prometheus/foresight). Tested Feb 2026, found real bugs.

## Testing

```bash
uv run pytest                      # All tests
uv run pytest tests/test_X.py -v   # Specific test
```
