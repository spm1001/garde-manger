"""Tests for the drill CLI command."""

import tempfile
import json
from pathlib import Path
from datetime import datetime

import pytest
from click.testing import CliRunner

from mem.cli import main
from mem.database import Database
from mem.glossary import Glossary


@pytest.fixture
def temp_memory_dir(monkeypatch):
    """Create a temporary memory directory with database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        memory_dir = Path(tmpdir) / 'memory'
        memory_dir.mkdir()

        # Create minimal config
        config_path = memory_dir / 'config.yaml'
        config_path.write_text("""
sources:
  claude_ai:
    path: ~/.claude/claude-ai/cache/conversations
  handoffs:
    path: ~/.claude/handoffs
""")

        # Create database
        db_path = memory_dir / 'memory.db'
        db = Database(db_path)
        with db:
            yield {
                'dir': memory_dir,
                'db': db,
                'db_path': db_path,
                'tmpdir': tmpdir,
            }


@pytest.fixture
def runner():
    return CliRunner()


# When drilling a handoff source with --full, it should display the markdown content
def test_drill_handoff_shows_markdown(temp_memory_dir, runner, monkeypatch):
    """Drill on handoff source displays raw markdown."""
    tmpdir = temp_memory_dir['tmpdir']
    db = temp_memory_dir['db']

    # Create a handoff file
    handoff_path = Path(tmpdir) / 'test-handoff.md'
    handoff_content = """# Handoff — 2025-12-28 (momentum)

project_path: /test/project

## Done
- Fixed the bug
- Added tests

## Learned
Something important about testing.
"""
    handoff_path.write_text(handoff_content)

    # Index it
    db.upsert_source(
        source_id='handoff:test-handoff',
        source_type='handoff',
        title='test-handoff handoff — 2025-12-28',
        path=str(handoff_path),
        created_at=datetime.now(),
    )

    # Patch to use our temp database
    monkeypatch.setattr('mem.cli.get_database', lambda: Database(temp_memory_dir['db_path']))

    result = runner.invoke(main, ['drill', 'handoff:test-handoff', '--full'])

    assert result.exit_code == 0
    assert '# Handoff — 2025-12-28 (momentum)' in result.output
    assert '## Done' in result.output
    assert 'Fixed the bug' in result.output


# When drilling a claude_ai source with --full, it should display messages
def test_drill_claude_ai_shows_messages(temp_memory_dir, runner, monkeypatch):
    """Drill on claude_ai source displays conversation messages."""
    tmpdir = temp_memory_dir['tmpdir']
    db = temp_memory_dir['db']

    # Create a claude_ai conversation file
    conv_dir = Path(tmpdir) / 'conversations'
    conv_dir.mkdir()
    conv_path = conv_dir / 'test-uuid.json'
    conv_data = {
        'uuid': 'test-uuid',
        'name': 'Test Conversation',
        'summary': 'A test summary',
        'model': 'claude-3',
        'created_at': '2025-12-28T10:00:00Z',
        'updated_at': '2025-12-28T10:00:00Z',
        'chat_messages': [
            {'sender': 'human', 'text': 'Hello Claude'},
            {'sender': 'assistant', 'text': 'Hello! How can I help?'},
        ]
    }
    conv_path.write_text(json.dumps(conv_data))

    # Index it with path pointing to actual file location
    db.upsert_source(
        source_id='claude_ai:test-uuid',
        source_type='claude_ai',
        title='Test Conversation',
        path=str(conv_path),  # Use actual path for test
        created_at=datetime.now(),
    )

    monkeypatch.setattr('mem.cli.get_database', lambda: Database(temp_memory_dir['db_path']))

    result = runner.invoke(main, ['drill', 'claude_ai:test-uuid', '--full'])

    assert result.exit_code == 0
    assert '[HUMAN]' in result.output
    assert 'Hello Claude' in result.output
    assert '[ASSISTANT]' in result.output
    assert 'How can I help?' in result.output


# When drilling a cloud_session source with --full, it should display messages
def test_drill_cloud_session_shows_messages(temp_memory_dir, runner, monkeypatch):
    """Drill on cloud_session source displays session messages."""
    tmpdir = temp_memory_dir['tmpdir']
    db = temp_memory_dir['db']

    # Create a cloud session file
    session_path = Path(tmpdir) / 'session_test123.json'
    session_data = {
        'loglines': [
            {
                'type': 'user',
                'timestamp': '2025-12-28T10:00:00Z',
                'message': {'role': 'user', 'content': 'Run the tests'}
            },
            {
                'type': 'assistant',
                'timestamp': '2025-12-28T10:00:01Z',
                'message': {'role': 'assistant', 'content': 'I will run the tests now.'}
            },
        ]
    }
    session_path.write_text(json.dumps(session_data))

    db.upsert_source(
        source_id='cloud_session:session_test123',
        source_type='cloud_session',
        title='Test Session',
        path=str(session_path),
        created_at=datetime.now(),
    )

    monkeypatch.setattr('mem.cli.get_database', lambda: Database(temp_memory_dir['db_path']))

    result = runner.invoke(main, ['drill', 'cloud_session:session_test123', '--full'])

    assert result.exit_code == 0
    assert '[USER]' in result.output
    assert 'Run the tests' in result.output
    assert '[ASSISTANT]' in result.output
    assert 'run the tests now' in result.output


# When drilling an unknown source type, it should show an error
def test_drill_unknown_source_type(temp_memory_dir, runner, monkeypatch):
    """Drill on unknown source type shows error."""
    tmpdir = temp_memory_dir['tmpdir']
    db = temp_memory_dir['db']

    # Create a file for the unknown source
    file_path = Path(tmpdir) / 'unknown.txt'
    file_path.write_text('some content')

    db.upsert_source(
        source_id='unknown:test',
        source_type='unknown',
        title='Unknown Source',
        path=str(file_path),
        created_at=datetime.now(),
    )

    monkeypatch.setattr('mem.cli.get_database', lambda: Database(temp_memory_dir['db_path']))

    result = runner.invoke(main, ['drill', 'unknown:test', '--full'])

    assert result.exit_code == 0
    assert 'Unknown source type: unknown' in result.output


# When drilling a source that doesn't exist, it should show an error
def test_drill_nonexistent_source(temp_memory_dir, runner, monkeypatch):
    """Drill on nonexistent source shows error."""
    monkeypatch.setattr('mem.cli.get_database', lambda: Database(temp_memory_dir['db_path']))

    result = runner.invoke(main, ['drill', 'fake:source'])

    assert result.exit_code == 0
    assert 'Source not found' in result.output


# Hyphenated terms are auto-quoted so search just works
def test_search_hyphenated_auto_quoted(temp_memory_dir, runner, monkeypatch):
    """Search with hyphenated terms auto-quotes and finds results."""
    db = temp_memory_dir['db']

    # Add a source with summary
    db.upsert_source(
        source_id='test:1',
        source_type='test',
        title='Test',
        created_at=datetime.now(),
    )
    db.upsert_summary(source_id='test:1', summary_text='Testing the draw-down pattern')

    monkeypatch.setattr('mem.cli.get_database', lambda: Database(temp_memory_dir['db_path']))
    monkeypatch.setattr('mem.cli.load_config', lambda: {})
    monkeypatch.setattr('mem.cli.load_glossary', lambda: Glossary({'entities': {}}))

    result = runner.invoke(main, ['search', 'draw-down'])

    # Should succeed and find the result (auto-quoting handles the hyphen)
    assert result.exit_code == 0
    assert 'draw-down' in result.output
    assert '1 results' in result.output
