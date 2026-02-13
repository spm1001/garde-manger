"""Tests for handoffs adapter.

Tests the decode_parent_dir function and HandoffSource parsing.
"""
import pytest
from pathlib import Path
from unittest.mock import patch

from src.garde.adapters.handoffs import decode_parent_dir, HandoffSource


class TestDecodeParentDir:
    """Tests for decode_parent_dir function."""

    # When parent dir contains -Repos-, it should extract project name and path
    def test_repos_pattern(self):
        name, path = decode_parent_dir('-Users-jane-Repos-claude-memory')
        assert name == 'claude-memory'
        assert path.endswith('/Repos/claude-memory')

    # When parent dir contains -Repos- with hyphenated project name, should preserve hyphens
    def test_repos_hyphenated_name(self):
        name, path = decode_parent_dir('-Users-jane-Repos-skill-session-management')
        assert name == 'skill-session-management'
        assert path.endswith('/Repos/skill-session-management')

    # When parent dir is exactly -.claude, should return claude-config
    def test_claude_config_exact(self):
        name, path = decode_parent_dir('-Users-jane-.claude')
        assert name == 'claude-config'
        assert path.endswith('/.claude')

    # When parent dir contains -.claude- with subdirectory, should extract that
    def test_claude_subdirectory(self):
        name, path = decode_parent_dir('-Users-jane-.claude-memory')
        assert name == 'memory'
        assert '/.claude/memory' in path

    # When path is unknown but reconstructable, should extract last segment as project name
    def test_unknown_path_fallback(self):
        name, path = decode_parent_dir('-Users-jane-Documents-SomeProject')
        assert name == 'SomeProject'
        # Path may be empty if directory doesn't exist, but name should be extracted

    # When path is Linux-style, should still extract project name
    def test_linux_path(self):
        name, path = decode_parent_dir('-home-ubuntu-projects-myapp')
        assert name == 'myapp'

    # When parent dir is empty or invalid, should return empty strings
    def test_invalid_input(self):
        name, path = decode_parent_dir('')
        assert name == ''
        assert path == ''

    # When parent dir doesn't start with dash but contains -Repos-, should still extract
    def test_no_leading_dash_with_pattern(self):
        name, path = decode_parent_dir('Users-jane-Repos-foo')
        assert name == 'foo'  # Pattern matching still works

    # When parent dir has no recognizable pattern, should return empty
    def test_no_pattern_match(self):
        name, path = decode_parent_dir('completely-random-string')
        assert name == ''
        assert path == ''


class TestHandoffSource:
    """Tests for HandoffSource parsing."""

    @pytest.fixture
    def sample_handoff(self, tmp_path):
        """Create a sample handoff file for testing."""
        content = """# Handoff — 2025-12-29 (momentum)

## Done
- Fixed the bug
- Added tests

## Learned
Something interesting about the codebase.

## Next
- Continue with phase 2
"""
        handoff_dir = tmp_path / '-Users-jane-Repos-test-project'
        handoff_dir.mkdir()
        handoff_file = handoff_dir / 'test-project-2025-12-29-1234.md'
        handoff_file.write_text(content)
        return handoff_file

    # When parsing a valid handoff file, should extract all fields
    def test_parse_handoff(self, sample_handoff):
        source = HandoffSource.from_file(sample_handoff)

        assert source.project_name == 'test-project'
        assert source.mood == 'momentum'
        assert source.date.year == 2025
        assert source.date.month == 12
        assert source.date.day == 29
        assert 'Done' in source.sections
        assert 'Fixed the bug' in source.sections['Done']

    # When handoff has no mood in header, mood should be None
    def test_parse_no_mood(self, tmp_path):
        content = """# Handoff — 2025-12-29

## Done
- Something
"""
        handoff_dir = tmp_path / '-Users-jane-Repos-no-mood'
        handoff_dir.mkdir()
        handoff_file = handoff_dir / 'no-mood-2025-12-29-1234.md'
        handoff_file.write_text(content)

        source = HandoffSource.from_file(handoff_file)
        assert source.mood is None

    # When filename is just a timestamp, should get project name from parent dir
    def test_timestamp_only_filename(self, tmp_path):
        content = """# Handoff — 2025-12-29 (momentum)

## Done
- Something
"""
        handoff_dir = tmp_path / '-Users-jane-Repos-my-project'
        handoff_dir.mkdir()
        handoff_file = handoff_dir / '2025-12-29-1234.md'
        handoff_file.write_text(content)

        source = HandoffSource.from_file(handoff_file)
        assert source.project_name == 'my-project'

    # When generating title, should include project name, mood, and date
    def test_title_generation(self, sample_handoff):
        source = HandoffSource.from_file(sample_handoff)
        title = source.title

        assert 'test-project' in title
        assert 'momentum' in title
        assert '2025-12-29' in title

    # When generating full_text, should combine all sections
    def test_full_text(self, sample_handoff):
        source = HandoffSource.from_file(sample_handoff)
        full = source.full_text()

        assert '## Done' in full
        assert '## Learned' in full
        assert 'Fixed the bug' in full
