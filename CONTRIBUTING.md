# Contributing to garde-manger

Thanks for your interest in contributing! This document covers the basics.

## Development Setup

```bash
# Clone the repo
git clone https://github.com/spm1001/garde-manger.git
cd garde-manger

# Install dependencies (requires uv)
uv sync

# Run tests
uv run pytest
```

## Running Tests

```bash
# All tests
uv run pytest

# With verbose output
uv run pytest -v

# Specific test file
uv run pytest tests/test_database.py
```

Tests use `use_turso=False` fixtures to ensure they work without cloud credentials.

## Code Style

- Python 3.11+
- Type hints where practical
- Docstrings for public functions

## Making Changes

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make your changes
4. Run tests (`uv run pytest`)
5. Commit with a descriptive message
6. Push to your fork
7. Open a pull request

## Adding a New Source Adapter

Source adapters live in `src/garde/adapters/`. To add a new source type:

1. Create `src/garde/adapters/my_source.py`
2. Implement a `MySource` dataclass with:
   - `source_id` property (format: `type:identifier`)
   - `has_presummary` property
   - `full_text()` method
   - `from_file()` classmethod (if file-based)
3. Implement `discover_my_source(config)` generator
4. Add to the scan command in `src/garde/cli.py`
5. Add tests in `tests/test_my_source_adapter.py`

## Questions?

Open an issue for discussion before starting major changes.
