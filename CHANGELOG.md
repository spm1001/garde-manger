# Changelog

All notable changes to this project will be documented in this file.

## About This Repository

This repo was created on 2026-01-20 with a single "Initial commit" containing all code. The history was intentionally squashed when open-sourcing from a private development repo to remove personal data from git history.

The features below were developed over several weeks (Dec 2025 - Jan 2026) before the public release.

## [0.1.0] - 2026-01-20

Initial public release.

### Features

- **Multi-source indexing** — Adapters for Claude Code, Claude.ai exports, handoffs, local markdown, beads, and cloud sessions
- **FTS5 search** — Full-text search over summaries with SQLite FTS5
- **LLM extraction** — Summarization and entity extraction using Anthropic API
- **Glossary system** — Map aliases to canonical terms for consistent search
- **CLI interface** — `scan`, `search`, `drill`, `status`, `process`, `resolve`, and more
- **Skill integration** — `/mem` skill for in-session search within Claude Code

### Fixed

- Unified FTS5 schema to standalone mode (was causing index corruption with external content mode)

### Migration

If upgrading from an earlier version, rebuild your FTS index:

```bash
uv run mem rebuild-fts
```

### Changed

- Local SQLite is now the recommended path; Turso cloud sync marked as experimental due to FTS5 issues
