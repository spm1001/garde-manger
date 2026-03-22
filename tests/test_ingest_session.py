"""Tests for the ingest-session CLI command."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from garde.cli import main
from garde.config import encode_cwd
from garde.database import Database


@pytest.fixture
def env(tmp_path):
    """Create an isolated environment with DB, projects dir, and pending-extractions."""
    memory_dir = tmp_path / '.claude' / 'memory'
    memory_dir.mkdir(parents=True)
    (memory_dir / 'backups').mkdir()

    config_path = memory_dir / 'config.yaml'
    config_path.write_text("sources:\n  claude_code:\n    path: ~/.claude/projects\n")

    db_path = memory_dir / 'memory.db'
    db = Database(db_path)

    projects_dir = tmp_path / '.claude' / 'projects'
    pending_dir = tmp_path / '.claude' / '.pending-extractions'
    pending_dir.mkdir(parents=True)

    with db:
        yield {
            'home': tmp_path,
            'db': db,
            'db_path': db_path,
            'projects_dir': projects_dir,
            'pending_dir': pending_dir,
        }


@pytest.fixture
def runner():
    return CliRunner()


def _create_session(env, cwd, session_id, messages=None):
    """Create a JSONL session file in the right project directory."""
    encoded = encode_cwd(cwd)
    session_dir = env['projects_dir'] / encoded
    session_dir.mkdir(parents=True, exist_ok=True)
    path = session_dir / f'{session_id}.jsonl'

    if messages is None:
        messages = [
            {"type": "user", "timestamp": "2026-03-22T10:00:00Z",
             "sessionId": session_id,
             "message": {"role": "user", "content": "Help me fix this bug in the auth module"}},
            {"type": "assistant", "timestamp": "2026-03-22T10:01:00Z",
             "sessionId": session_id,
             "message": {"role": "assistant", "content": "I'll look at the auth module. Let me read the relevant files."}},
        ]

    with path.open('w') as f:
        for msg in messages:
            f.write(json.dumps(msg) + '\n')
    return path


def _stage_extraction(env, session_id):
    """Create a staged extraction file."""
    data = {
        "summary": "Fixed auth module bug",
        "arc": {"started_with": "auth bug", "key_turns": ["found root cause"], "ended_at": "fixed"},
        "builds": [{"what": "auth fix", "details": "patched token refresh"}],
        "learnings": [{"insight": "tokens expire silently", "why_it_matters": "hard to debug", "context": "auth module"}],
        "friction": [],
        "patterns": ["debug-then-fix"],
        "open_threads": [],
    }
    staged = env['pending_dir'] / f'{session_id}.json'
    staged.write_text(json.dumps(data))
    return staged


def test_ingest_session_indexes_without_staged(runner, env):
    """Safety-net path: indexes session, defers extraction to backfill."""
    session_id = "aaaa-bbbb-cccc-dddd"
    cwd = "/home/user/project"
    _create_session(env, cwd, session_id)

    with patch('garde.config.Path.home', return_value=env['home']):
        result = runner.invoke(main, [
            'ingest-session', '--session-id', session_id, '--cwd', cwd,
        ])

    assert result.exit_code == 0
    assert "Indexed" in result.stderr or "Indexed" in result.output
    # Source exists in DB
    source = env['db'].get_source(f'claude_code:{session_id}')
    assert source is not None


def test_ingest_session_consumes_staged_extraction(runner, env):
    """Fast path: indexes + stores staged extraction + deletes staged file."""
    session_id = "eeee-ffff-0000-1111"
    cwd = "/home/user/project"
    _create_session(env, cwd, session_id)
    staged = _stage_extraction(env, session_id)

    with patch('garde.config.Path.home', return_value=env['home']):
        result = runner.invoke(main, [
            'ingest-session', '--session-id', session_id, '--cwd', cwd,
        ])

    assert result.exit_code == 0
    # Source indexed
    source = env['db'].get_source(f'claude_code:{session_id}')
    assert source is not None
    # Extraction stored
    extraction = env['db'].connect().execute(
        "SELECT * FROM extractions WHERE source_id = ?",
        (f'claude_code:{session_id}',)
    ).fetchone()
    assert extraction is not None
    assert extraction['model_used'] == 'claude-code-context'
    # Staged file consumed
    assert not staged.exists()


def test_ingest_session_missing_file(runner, env):
    """Missing JSONL file: logs error, exits cleanly."""
    with patch('garde.config.Path.home', return_value=env['home']):
        result = runner.invoke(main, [
            'ingest-session', '--session-id', 'nonexistent-id', '--cwd', '/fake/path',
        ])

    assert result.exit_code == 0  # exits cleanly, doesn't crash
    assert "not found" in (result.stderr or result.output).lower()


def test_ingest_session_skips_warmup(runner, env):
    """Warmup/empty sessions are skipped."""
    session_id = "warm-up-session-id"
    cwd = "/home/user/project"
    _create_session(env, cwd, session_id, messages=[
        {"type": "user", "timestamp": "2026-03-22T10:00:00Z",
         "sessionId": session_id,
         "message": {"role": "user", "content": "warmup"}},
    ])

    with patch('garde.config.Path.home', return_value=env['home']):
        result = runner.invoke(main, [
            'ingest-session', '--session-id', session_id, '--cwd', cwd,
        ])

    assert result.exit_code == 0
    source = env['db'].get_source(f'claude_code:{session_id}')
    assert source is None  # not indexed


def test_ingest_session_bad_staged_json_keeps_file(runner, env):
    """Corrupt staged extraction: logged, file preserved for retry."""
    session_id = "bad-json-session"
    cwd = "/home/user/project"
    _create_session(env, cwd, session_id)
    staged = env['pending_dir'] / f'{session_id}.json'
    staged.write_text("not valid json {{{")

    with patch('garde.config.Path.home', return_value=env['home']):
        result = runner.invoke(main, [
            'ingest-session', '--session-id', session_id, '--cwd', cwd,
        ])

    assert result.exit_code == 0
    # Source still indexed despite bad extraction
    source = env['db'].get_source(f'claude_code:{session_id}')
    assert source is not None
    # Staged file preserved (not deleted on error)
    assert staged.exists()


def test_encode_cwd_matches_bash():
    """encode_cwd produces same output as sed 's/[^a-zA-Z0-9-]/-/g'."""
    assert encode_cwd("/home/modha/Repos/batterie/garde-manger") == "-home-modha-Repos-batterie-garde-manger"
    assert encode_cwd("/Users/jane/Documents/my project") == "-Users-jane-Documents-my-project"
    assert encode_cwd("already-safe") == "already-safe"
