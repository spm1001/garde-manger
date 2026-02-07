# CLAUDE.md — claude-mem

Instructions for Claude when working in this codebase.

## What This Is

Persistent, searchable memory across Claude sessions. FTS5 search over summaries + human-in-the-loop entity resolution.

## Key Commands

```bash
uv run mem scan                    # Index sources (free, fast)
uv run mem process <session>       # Extract single session
uv run mem backfill --limit 100    # Batch extract (via claude -p)
uv run mem search "query"          # FTS5 search
uv run mem drill <source_id>       # Load full content
uv run mem status                  # Index statistics
uv run mem prune --dry-run         # Find sources with invalid paths
uv run mem prune --yes             # Mark stale (preserves extractions)
```

## Architecture

- `src/mem/cli.py` — Main CLI (~2100 lines, needs refactoring)
- `src/mem/database.py` — SQLite with FTS5
- `src/mem/llm.py` — LLM calls via `claude -p` (Opus 4.6, Max subscription), semantic chunking
- `src/mem/extraction.py` — Entity extraction orchestration
- `src/mem/adapters/*.py` — Source format parsers (8 types)

## Known Issues / Tech Debt

See `ADAPTER_AUDIT.md` for the adapter protocol plan.

**CLI monolith:** The scan command has ~450 lines of near-identical loops for 8 source types. Refactor to registry pattern is tracked in arc.

**Backfill resilience:** Each extraction commits immediately, so interrupted backfill is resumable (just rerun). But no progress counter — use `grep -c "✓" logfile` to monitor.

**`--limit 0` gotcha:** In backfill/populate commands, `--limit 0` means SQL `LIMIT 0` (returns nothing), not "unlimited". Use a large number like `--limit 10000` instead.

**Stale sources:** Sources with invalid paths are marked `status='stale'` (not deleted) to preserve extraction value. Use `mem prune --delete` for hard deletion, but extractions will be lost. Stale sources still appear in search results — filtering coming later.

## Code Review

Use `/titans` for thorough review — three parallel Opus agents (Epimetheus/hindsight, Metis/craft, Prometheus/foresight). Tested Feb 2026, found real bugs.

## Testing

```bash
uv run pytest                      # All tests
uv run pytest tests/test_X.py -v   # Specific test
```
