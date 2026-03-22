# Changelog

All notable changes to this project will be documented in this file.

## About This Repository

This repo was created on 2026-01-20 with a single "Initial commit" containing all code. The history was intentionally squashed when open-sourcing from a private development repo to remove personal data from git history.

The features below were developed over several weeks (Dec 2025 - Jan 2026) before the public release.

## [0.3.0] - 2026-03-22

### Added

- **SessionEnd hook** — Automatically indexes sessions on exit. Staged extractions from `/close` are consumed immediately (fast path, no LLM); sessions without `/close` are indexed and deferred to `garde backfill`.
- **SessionStart hook** — Checks CLI availability and version alignment with the plugin. Silent when healthy; warns via `hookSpecificOutput` when not.
- **`garde ingest-session` command** — Single CLI entry point for the session-end hook. Finds the JSONL, indexes it, and consumes any staged extraction — all in Python, no shell orchestration.
- **Auto-migrating DB path** — `get_db_path()` detects legacy DB at `~/.claude/memory/memory.db` and plugin data dir at `~/.claude/plugins/data/garde-manger-batterie-de-savoir/`, auto-migrates on first access (move + symlink + backup).
- **`get_data_dir()` helper** — Returns the plugin data directory path.
- **Staged extraction contract** documented in CLAUDE.md — JSON schema, path convention, CWD encoding shared between bon's `/close` and garde's session-end hook.

### Changed

- **DB location** — Primary location is now `~/.claude/plugins/data/garde-manger-batterie-de-savoir/memory.db` (persists across plugin version updates). Legacy path still works via symlink.
- **CLAUDE.md** — Rewritten to reflect CLI package structure, hooks architecture, and extraction contract.
- **Version** bumped to 0.3.0 (hooks = minor version).

## [0.1.0] - 2026-01-20

Initial public release.

### Features

- **Multi-source indexing** — Adapters for Claude Code, Claude.ai exports, handoffs, local markdown, bon, and cloud sessions
- **FTS5 search** — Full-text search over summaries with SQLite FTS5
- **LLM extraction** — Summarization and entity extraction using Anthropic API
- **Glossary system** — Map aliases to canonical terms for consistent search
- **CLI interface** — `scan`, `search`, `drill`, `status`, `process`, `resolve`, and more
- **Skill integration** — `/garde` skill for in-session search within Claude Code

### Fixed

- Unified FTS5 schema to standalone mode (was causing index corruption with external content mode)

### Migration

If upgrading from an earlier version, rebuild your FTS index:

```bash
uv run garde rebuild-fts
```

### Changed

- Local SQLite is now the recommended path; Turso cloud sync marked as experimental due to FTS5 issues
