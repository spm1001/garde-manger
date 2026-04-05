# Garde-manger — Understanding

The larder. Persistent, searchable memory across Claude sessions. FTS5 search over session summaries, structured extractions (builds, learnings, friction, patterns), and raw conversation text. Part of the kitchen brigade: garde-manger is the cold station — indexing, storage, retrieval. It does not make the stock; it stores what the kitchen produces.

## The data model

Six tables in SQLite. **Sources** are the index — every session, handoff, bon item, and Amp thread gets a row with a composite `source_id` (e.g., `claude_code:uuid`, `amp:T-uuid`). **Summaries** hold pre-existing summaries (from CC's compaction or /close) plus raw text, backed by an FTS5 virtual table for full-text search. **Extractions** are the LLM-generated semantic layer — summary, arc (narrative structure), builds, learnings, friction, patterns, open threads. A source without an extraction is searchable by title; one with an extraction is searchable by meaning.

The split between summaries and extractions is load-bearing. Summaries are cheap (parsed from source files, no LLM call). Extractions come from two paths: handoff section parse (free, high quality — the primary path since Apr 2026) or LLM backfill for sessions without handoffs (expensive, fallback only). Scan is fast and free; backfill is slow and reserved for unclosed sessions.

## The adapter architecture

Eight source type adapters, each implementing `discover_*()` and a `*Source` dataclass with `from_file()`, `full_text()`, and `source_id`. Claude Code is the most complex — JSONL parsing, metadata extraction (tool calls, files touched, skills used, git commits), subagent detection. The CC adapter's `discover_claude_code()` globs `**/*.jsonl` under `~/.claude/projects/` to find sessions including subagents in nested `subagents/` directories.

The adapter protocol is informal — each adapter follows the pattern but there's no abstract base class. ADAPTER_AUDIT.md tracks the plan to formalize it. The CLI (`cli.py`, ~2100 lines) is a monolith with near-identical scan loops for each source type. Registry pattern refactor is tracked in bon.

## The extraction pipeline (Apr 2026)

Three paths to extraction, reflecting garde's role as store rather than producer:

**Handoff section parse (primary):** `garde scan --source handoffs` discovers handoffs in `~/.claude/handoffs/` and `.bon/handoffs/` across repos, calls `HandoffSource.to_extraction()` to map markdown sections to extraction fields (Done→builds, Gotchas→friction, Reflection→learnings, Learned→patterns, Next→open_threads). Free, high quality. `model_used: "handoff-section-parse"`. Both old flat-h2 and new fond-v1 two-zone formats supported. mtime-based skip for efficient re-scans.

**Overnight composting (planned, bds-zowetu):** Bon's `scripts/compost.sh` will read unprocessed handoffs, call garde's handoff adapter, and store extractions. This is the designed path — bon orchestrates, garde stores. Composting also synthesizes Learned sections into understanding.md as a safety net.

**Backfill (fallback):** `garde backfill` → finds unextracted sources → `_call_claude()` in `llm.py` → `claude -p` Opus 4.6 → parse → store. For sessions without handoffs only. Each extraction commits immediately (resumable). The `GARDE_SUBAGENT=1` env var guard is critical for fork bomb prevention.

**Retired (Apr 2026):** The staged extraction pipeline (`/close` → `~/.claude/.pending-extractions/` → `ingest-session`) has been removed. The `store-extraction` CLI command has been removed. Handoff section parse replaces both.

## The multi-machine problem (Mar 2026)

Garde's SQLite database is local to each machine. Sessions live in `~/.claude/projects/` which may or may not be synced via git (claude-config repo). The consolidation pattern discovered in March 2026: rsync sessions from all machines to one primary (hezza), then scan + backfill. Extractions can be imported between SQLite databases via SQL dump + INSERT OR IGNORE + FTS rebuild.

This is the strongest argument for migrating to Dolt (bon-forebi). Dolt would give each machine a clone that pushes/pulls structured data with row-level merge — eliminating the rsync + manual merge dance entirely. The FTS5 → MySQL FULLTEXT rewrite is part of that migration (bon-forebi step 3) — fundamentally different APIs, ~50 lines in database.py, contained but real.

## Who actually uses garde search

Data from 4,946 sessions (Nov 2025 – Mar 2026): 452 search commands in 84 non-dev sessions. **86% are Claude-initiated** — Claude searches autonomously during sessions, not because the user asked. The user almost never searches directly; when they want a specific session, they necromance the JSONL with jq. Usage peaked in Jan-Feb 2026 (195-219 searches/month) then dropped to 14 in March — caused by moving to hezza where the DB had only 173 sessions indexed. Not a usage pattern change; a data availability gap.

Garde's primary consumer is future Claudes, not the human. This shapes priorities: extraction quality matters more than search UX.

## The knowledge pyramid (Apr 2026)

Garde sits in a temporal stack of persistence layers, each serving a different timescale:

| Layer | Timescale | What | Where |
|-------|-----------|------|-------|
| Live context | This session | Full conversation, tools, files | CC context window (lost at /exit) |
| Raw text (L1) | Hours–days | Searchable full conversations | Garde: claude_code source type + FTS5 |
| Handoffs (L2) | Next session | Tactical baton — gotchas, next steps | .bon/handoffs/ (git) |
| understanding.md (L3) | Days–weeks | Project soul, design values | .bon/ (git), synthesized at /open |
| MEMORY.md (L4) | Weeks–months | Typed observations | ~/.claude/ (Anthropic's autoDream) |
| Garde extractions (L5) | Months–forever | Searchable semantic archive | Garde DB — filled by handoff parse + composting |
| Bon items | Cross-session | Work state | .bon/ (orthogonal to knowledge stack) |

Garde's primary role is L1 (raw text search) and L5 (structured extractions). L1 is immediate utility — "find that session." L5 is accumulated wisdom — "what did we learn." Both are consumed primarily by future Claudes (86% of searches are Claude-initiated).

**Known gap (Apr 2026):** L1 quality is poor. The claude_code adapter's `full_text()` is a naive join that doesn't handle compaction boundaries, duplicate message IDs, or system tag stripping. ccconv (in trousse's deglacer skill) handles all of these correctly. Sharing ccconv's parsing quality with garde's adapter is tracked work.

The risk isn't "too many layers" — it's drift between them, and quality gaps within layers.

## Landmines

**`--limit 0` means zero, not unlimited.** In backfill/populate commands, `--limit 0` is SQL `LIMIT 0` (returns nothing). Use `--limit 10000` for "all."

**`ingest-session` is the indexing boundary.** It indexes the source + summary, nothing more. Extraction happens elsewhere: handoff scan (section parse, free) or backfill (LLM, fallback). The staged extraction pipeline was removed in Apr 2026 — don't re-add it.

**Fork bomb prevention is non-negotiable.** `_call_claude()` sets `GARDE_SUBAGENT=1`. Session-start hooks must check this and exit early. Removing this guard creates exponential subprocess spawning.

**`uv tool install` caches stale binaries.** After changing adapter code or CLI, the installed `garde` binary won't reflect changes until `uv tool install --reinstall`. The cron uses the installed binary, not `uv run` — so code changes don't take effect in cron until reinstall.

**FTS5 rebuild is manual after bulk imports.** INSERT OR IGNORE into the extractions table doesn't update the FTS index. Must run `INSERT INTO summaries_fts(summaries_fts) VALUES('rebuild')` after importing extraction data from another machine's database.

**Mac and tube have 2,349 duplicate JSONL files.** Same session UUIDs exist under both `-Users-modha-*` and `-home-modha-*` paths due to claude-config syncing. Garde deduplicates by source_id at index time (only 103 Mac-only sessions were genuinely new), but the duplicate files waste ~1.9 GB on disk.

## Garde's role in the fond architecture (Apr 2026)

Fond is the architecture for how knowledge flows from sessions to durable memory. Bon owns the lifecycle (open/close/compost). Garde is the larder — it stores what the kitchen produces.

- **Bon's composting** (scripts/compost.sh, planned) calls garde's handoff adapter to produce extractions, then stores them in garde's DB
- **Garde's scan** indexes sources across 8 types and runs handoff section parse for extraction
- **Garde's backfill** is the fallback for unclosed sessions — expensive but necessary for coverage
- **Garde's search/MCP** is how future Claudes query across all sessions

The interface between bon and garde is the handoff adapter: `HandoffSource.to_extraction()`. Built in bds-kevapu (Apr 2026).

## Current state (Apr 2026)

8,723 sources on hezza: 5,628 claude_code, 1,663 handoffs, 1,357 bon, 75 amp. 179 handoffs now have free section-parse extractions. Backfill cron handles the rest (200/day). Dolt migration spiked and queued (bon-forebi) — schema maps cleanly, deferred pending fond stabilisation.
