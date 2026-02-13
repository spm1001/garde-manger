# garde-manger

[![Tests](https://github.com/spm1001/garde-manger/actions/workflows/test.yml/badge.svg)](https://github.com/spm1001/garde-manger/actions/workflows/test.yml)

Persistent, searchable memory across Claude sessions. The cold station of the kitchen brigade — preservation, storage, retrieval.

## The Problem

You've had hundreds of conversations with Claude. Solved problems, made decisions, learned things together. But each new session starts blank — Claude remembers nothing.

"Didn't we figure out the auth pattern last month?" *Gone.*
"What was that workaround for the API rate limit?" *Lost.*

This tool gives Claude (and you) access to that history.

## The Kitchen

garde-manger is part of a tool suite built around Claude Code, following a professional kitchen [brigade](https://en.wikipedia.org/wiki/Brigade_de_cuisine) metaphor:

| Tool | Brigade role | What it does |
|------|-------------|--------------|
| [**mise-en-space**](https://github.com/spm1001/mise-en-space) | Mise en place | Content from Google Workspace and the web, prepped and ready |
| [**passe**](https://github.com/spm1001/passe) | The pass | Fast browser automation — the inspection window between kitchen and floor |
| [**garde-manger**](https://github.com/spm1001/garde-manger) | Cold station | Persistent, searchable memory across Claude sessions |
| [**trousse**](https://github.com/spm1001/trousse) | Knife roll | Skills and behavioural extensions for Claude Code |

Together they address the session-to-session continuity problem from different angles: [arc](https://github.com/spm1001/arc) tracks *what needs doing*, handoffs pass *context between sessions*, and garde-manger provides *searchable ancestral memory*.

## What It Does

1. **Search across past conversations** — Find that discussion about authentication patterns
2. **Consistent terminology** — Your glossary maps aliases to canonical terms
3. **Token efficiency** — Search summaries first, drill into full content only when needed
4. **Cross-platform** — Works with Claude Code, Claude.ai, handoffs, beads, arc, cloud sessions, and local markdown

## Quick Start

Requires [uv](https://docs.astral.sh/uv/) (fast Python package manager). If you don't have it: `curl -LsSf https://astral.sh/uv/install.sh | sh`

```bash
# Clone and install
git clone https://github.com/spm1001/garde-manger.git
cd garde-manger
uv sync

# Scan for sources and index them
uv run garde scan

# Search your memory
uv run garde search "authentication"

# Drill into a specific result
uv run garde drill claude_code:abc123
```

### API Key (for extraction)

LLM extraction enriches sources with summaries, builds, and learnings. It requires an Anthropic API key:

```bash
# Create the config directory
mkdir -p ~/.claude/memory

# Add your API key
echo 'export ANTHROPIC_API_KEY=sk-ant-...' > ~/.claude/memory/env
```

## How It Works

![garde-manger Architecture](docs/architecture.png)

**Key insight:** Text search over summaries + human-in-the-loop entity resolution outperforms vector embeddings for this use case.

## CLI Commands

```bash
# Discovery and indexing
garde scan                     # Discover sources and add metadata to index
garde process                  # Run LLM extraction on pending sources (costs API calls)
garde status                   # Show index statistics

# Search
garde search "query"           # FTS5 search over summaries
garde search "query" -s claude_code  # Filter by source type
garde drill <source_id>        # Load full source content
garde drill <source_id> --outline    # Show conversation structure

# Maintenance
garde resolve                  # Interactive entity resolution
garde rebuild                  # Rebuild FTS5 index
```

**scan vs process:** `garde scan` discovers sources and indexes metadata (free, fast). `garde process` runs LLM extraction to enrich with summaries and learnings (costs API calls, slower).

### Example Output

```
$ uv run garde status

Memory dir: /Users/you/.claude/memory
Glossary: 85 entities

Database:
  Sources: 6247
    beads: 1526
    claude_ai: 102
    claude_code: 2000
    handoff: 213
    local_md: 2368
  Summaries indexed: 6237
```

```
$ uv run garde search "OAuth"

3 results:

1. [claude_code] Implementing OAuth flow for Google APIs
   Added OAuth 2.0 authentication with refresh token handling. Debugging
   redirect URI mismatch errors.
   [2 builds, 3 learnings]
   3 days ago · ID: claude_code:a1b2c3d4

2. [handoff] Auth refactoring session
   Moved from API keys to OAuth. Key decision: use PKCE flow for CLI apps.
   [1 build, 2 learnings]
   2 weeks ago · ID: handoff:e5f6g7h8

3. [local_md] OAuth security notes
   Notes on token storage best practices and refresh strategies.
   Jan 2026 · ID: local_md:notes/oauth.md
```

## CLI vs Skill

- **CLI (`uv run garde`)** — Run from terminal, works anywhere
- **Skill (`/garde`)** — Invoked within Claude Code sessions, provides in-context search

Use the CLI for maintenance (scan, status, rebuild). The skill is for in-session retrieval when you're working with Claude.

See the `skill/` directory for the Claude Code skill.

## Configuration

Config lives at `~/.claude/memory/config.yaml`. Created with defaults on first run.

```yaml
# Example: add local markdown sources
sources:
  local_md:
    meeting_notes:
      path: ~/Documents/Meeting Notes
      pattern: "**/*.md"
```

### Source Types

| Source | Description | Auto-discovered |
|--------|-------------|-----------------|
| `claude_code` | Claude Code sessions | Yes (`~/.claude/projects/`) |
| `claude_ai` | Claude.ai exports | Yes (via [claude-data-sync](https://github.com/anthropics/claude-data-sync)) |
| `handoff` | Session handoff files | Yes (`~/.claude/handoffs/`) |
| `local_md` | Local markdown files | Configure paths in config.yaml |
| `arc` | Arc work tracker | Yes (from `.arc/` directories) |

## Glossary

The glossary at `~/.claude/memory/glossary.yaml` maps alternative names to canonical terms:

```yaml
entities:
  oauth:
    name: OAuth
    type: concept
    aliases:
      - oauth2
      - "OAuth 2.0"
```

When you search for "oauth2", it finds content mentioning "OAuth".

### Building a Glossary

Add entries when:
- A concept has multiple names (OAuth, oauth2, "OAuth 2.0")
- Acronyms are ambiguous (CS&P vs CSP)
- Project codenames exist (GeoX = Region:Lift)

Start small. Add entries as you encounter confusion in search results.

## Privacy & Data

- **Local only** — All data stays in `~/.claude/memory/memory.db`
- **LLM extraction** — `garde process` sends conversation text to Anthropic API for summarization
- **No telemetry** — This tool doesn't phone home

## Architecture

- **Adapters** (`src/garde/adapters/`) — Parse each source format
- **Database** (`src/garde/database.py`) — SQLite with FTS5
- **CLI** (`src/garde/cli.py`) — Click-based command interface
- **Extraction** (`src/garde/extraction.py`) — Entity and summary extraction

## Troubleshooting

**Search fails with "invalid fts5 file format":**
```bash
uv run garde rebuild
```

**No results for content you know exists:**
- Check `garde status` to verify sources are indexed
- Try broader search terms (FTS5 uses token matching, not substring)

## Development

```bash
# Install with dev dependencies
uv sync

# Run tests
uv run pytest

# Run a specific test
uv run pytest tests/test_database.py -v
```

## Files in This Repo

| File | Purpose |
|------|---------|
| `AGENTS.md` | Instructions for Claude Code agents contributing to this repo |
| `CLAUDE.md.example` | Template for your project's CLAUDE.md (copy and customize) |
| `glossary.yaml.example` | Example glossary structure |
| `config.yaml.template` | Example configuration |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

MIT License. See [LICENSE](LICENSE) for details.
