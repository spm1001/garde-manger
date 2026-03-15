# Garde-manger — Understanding

Persistent, searchable memory across Claude sessions. FTS5 search over session summaries, LLM-extracted semantic data (builds, learnings, friction, patterns), and human-in-the-loop entity resolution. Part of the kitchen brigade: garde-manger is the cold station — preservation, storage, retrieval.

## The data model

Six tables in SQLite. **Sources** are the index — every session, handoff, bon item, and Amp thread gets a row with a composite `source_id` (e.g., `claude_code:uuid`, `amp:T-uuid`). **Summaries** hold pre-existing summaries (from CC's compaction or /close) plus raw text, backed by an FTS5 virtual table for full-text search. **Extractions** are the LLM-generated semantic layer — summary, arc (narrative structure), builds, learnings, friction, patterns, open threads. A source without an extraction is searchable by title; one with an extraction is searchable by meaning.

The split between summaries and extractions is load-bearing. Summaries are cheap (parsed from the JSONL, no LLM call). Extractions are expensive (`claude -p` Opus 4.6, ~30s each, Max subscription not API). This means scan is fast and free; backfill is slow and should run in background. The cron reflects this: scan every 30 minutes, backfill 200/day at 3am.

## The adapter architecture

Eight source type adapters, each implementing `discover_*()` and a `*Source` dataclass with `from_file()`, `full_text()`, and `source_id`. Claude Code is the most complex — JSONL parsing, metadata extraction (tool calls, files touched, skills used, git commits), subagent detection. The CC adapter's `discover_claude_code()` globs `**/*.jsonl` under `~/.claude/projects/` to find sessions including subagents in nested `subagents/` directories.

The adapter protocol is informal — each adapter follows the pattern but there's no abstract base class. ADAPTER_AUDIT.md tracks the plan to formalize it. The CLI (`cli.py`, ~2100 lines) is a monolith with near-identical scan loops for each source type. Registry pattern refactor is tracked in bon.

## The extraction pipeline

Two paths to extraction, both producing identical JSON:

**Backfill path:** `garde backfill` → finds unextracted sources → `_call_claude()` in `llm.py` → `claude -p --model claude-opus-4-6 --allowedTools "" --no-session-persistence --output-format json` → parse result → store. Each extraction commits immediately, so interrupted backfill is resumable. The `GARDE_SUBAGENT=1` env var guard in `_call_claude()` is critical — without it, the subprocess triggers session-start hooks which spawn more subprocesses recursively.

**In-session path:** The /close skill generates extraction JSON during the live session (when Claude has full context) and stages it to `~/.claude/.pending-extractions/{session_id}.json`. The session-end hook detects this and uses `garde index` + `garde store-extraction` instead of spawning a subprocess. The `model_used` for staged extractions is `claude-code-context`. This path is free (no additional LLM call) and higher quality (Claude has full context, not just the raw text).

## The multi-machine problem (Mar 2026)

Garde's SQLite database is local to each machine. Sessions live in `~/.claude/projects/` which may or may not be synced via git (claude-config repo). The consolidation pattern discovered in March 2026: rsync sessions from all machines to one primary (hezza), then scan + backfill. Extractions can be imported between SQLite databases via SQL dump + INSERT OR IGNORE + FTS rebuild.

This is the strongest argument for migrating to Dolt (bon-forebi). Dolt would give each machine a clone that pushes/pulls structured data with row-level merge — eliminating the rsync + manual merge dance entirely. The FTS5 → MySQL FULLTEXT rewrite is part of that migration (bon-forebi step 3) — fundamentally different APIs, ~50 lines in database.py, contained but real.

## Who actually uses garde search

Data from 4,946 sessions (Nov 2025 – Mar 2026): 452 search commands in 84 non-dev sessions. **86% are Claude-initiated** — Claude searches autonomously during sessions, not because the user asked. The user almost never searches directly; when they want a specific session, they necromance the JSONL with jq. Usage peaked in Jan-Feb 2026 (195-219 searches/month) then dropped to 14 in March — caused by moving to hezza where the DB had only 173 sessions indexed. Not a usage pattern change; a data availability gap.

Garde's primary consumer is future Claudes, not the human. This shapes priorities: extraction quality matters more than search UX.

## The memory landscape

Garde is one of several persistence layers, each serving a different temporal and cognitive function:

- **CLAUDE.md** — instructions (how to behave)
- **understanding.md** — prose portrait (what this project feels like, design values, landmines)
- **MEMORY.md** — narrow gotchas (weakest layer, overlaps with understanding.md)
- **Handoffs** — session-to-session baton
- **Garde extractions** — searchable semantic summaries for future Claudes
- **Bon items** — tactical state
- **Raw JSONL** — ground truth

The risk isn't "too many layers" — it's drift between them. A gotcha in MEMORY.md that contradicts understanding.md, or a handoff referencing an archived bon item.

## Landmines

**`--limit 0` means zero, not unlimited.** In backfill/populate commands, `--limit 0` is SQL `LIMIT 0` (returns nothing). Use `--limit 10000` for "all."

**Fork bomb prevention is non-negotiable.** `_call_claude()` sets `GARDE_SUBAGENT=1`. Session-start hooks must check this and exit early. Removing this guard creates exponential subprocess spawning.

**`uv tool install` caches stale binaries.** After changing adapter code or CLI, the installed `garde` binary won't reflect changes until `uv tool install --reinstall`. The cron uses the installed binary, not `uv run` — so code changes don't take effect in cron until reinstall.

**FTS5 rebuild is manual after bulk imports.** INSERT OR IGNORE into the extractions table doesn't update the FTS index. Must run `INSERT INTO summaries_fts(summaries_fts) VALUES('rebuild')` after importing extraction data from another machine's database.

**Mac and tube have 2,349 duplicate JSONL files.** Same session UUIDs exist under both `-Users-modha-*` and `-home-modha-*` paths due to claude-config syncing. Garde deduplicates by source_id at index time (only 103 Mac-only sessions were genuinely new), but the duplicate files waste ~1.9 GB on disk.

## Current state (Mar 2026)

6,739 sources indexed across all four machines (hezza, tube, kube, Mac). 549 extractions, ~4,500 pending. Backfill running via cron (200/day). Dolt migration spiked and queued (bon-forebi) — schema maps cleanly, FULLTEXT works but with a table-alias limitation, size is favourable (98 MB Dolt vs 279 MB SQLite). The Dolt value proposition is strongest when combined with bon migration — shared infrastructure enabling multi-agent coordination across machines.
