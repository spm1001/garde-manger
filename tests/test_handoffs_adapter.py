"""Tests for handoffs adapter.

Tests the decode_parent_dir function, HandoffSource parsing,
two-zone format support, and section-to-extraction mapping.
"""
import pytest
from pathlib import Path
from unittest.mock import patch

from src.garde.adapters.handoffs import (
    decode_parent_dir, HandoffSource, _parse_sections, _parse_preamble,
)


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


class TestTwoZoneFormat:
    """Tests for fond-v1 two-zone handoff format."""

    @pytest.fixture
    def two_zone_handoff(self, tmp_path):
        """Create a two-zone handoff file."""
        content = """# Handoff — 2026-04-04

session_id: abc123-def456
purpose: Redesigned the extraction pipeline

## Now

### Gotchas
- The staged extraction path is gone — don't look for pending-extractions
- ccconv is replaced by deglacer

### Risks
- Handoff format not yet stable across all repos

### Next
- Build overnight composting process
- Test with real handoffs on hezza

### Commands
```bash
garde scan --source handoffs
```

## Compost

### Done
- b5ab093 Updated handoff adapter to parse two-zone format
- e386ed2 Wired extraction into scan flow
- Removed staged extraction from ingest-session

### Reflection
**Claude observed:** The section parsing approach is elegant — no LLM needed, just markdown structure. The extraction quality depends on handoff quality, which is already high because /close writes with full context.

**User noted:** This is the architectural win we were after — free extraction from pre-structured content.

### Learned
Garde's extraction pipeline can be dramatically simplified when the source artifact is pre-structured. The handoff IS the extraction in prose form — parsing markdown sections into garde's schema fields is trivial and produces higher-quality results than cold-JSONL backfill because the writing Claude had full session context.
"""
        handoff_dir = tmp_path / '-home-modha-Repos-batterie-garde-manger'
        handoff_dir.mkdir()
        handoff_file = handoff_dir / '2026-04-04-abc123.md'
        handoff_file.write_text(content)
        return handoff_file

    def test_parse_two_zone_sections(self, two_zone_handoff):
        source = HandoffSource.from_file(two_zone_handoff)
        assert 'Gotchas' in source.sections
        assert 'Risks' in source.sections
        assert 'Next' in source.sections
        assert 'Done' in source.sections
        assert 'Reflection' in source.sections
        assert 'Learned' in source.sections
        # Zone names should NOT appear as sections
        assert 'Now' not in source.sections
        assert 'Compost' not in source.sections

    def test_parse_preamble(self, two_zone_handoff):
        source = HandoffSource.from_file(two_zone_handoff)
        assert source.session_id == 'abc123-def456'
        assert source.purpose == 'Redesigned the extraction pipeline'

    def test_is_two_zone(self, two_zone_handoff):
        source = HandoffSource.from_file(two_zone_handoff)
        assert source.is_two_zone

    def test_old_format_not_two_zone(self, tmp_path):
        content = """# Handoff — 2025-12-29

## Done
- Something

## Learned
A thing
"""
        handoff_dir = tmp_path / '-home-modha-Repos-test'
        handoff_dir.mkdir()
        f = handoff_dir / 'test-2025-12-29-1234.md'
        f.write_text(content)
        source = HandoffSource.from_file(f)
        assert not source.is_two_zone

    def test_title_uses_purpose(self, two_zone_handoff):
        source = HandoffSource.from_file(two_zone_handoff)
        assert 'Redesigned the extraction pipeline' in source.title

    def test_section_content_correct(self, two_zone_handoff):
        source = HandoffSource.from_file(two_zone_handoff)
        assert 'staged extraction path is gone' in source.sections['Gotchas']
        assert 'Updated handoff adapter' in source.sections['Done']
        assert 'dramatically simplified' in source.sections['Learned']


class TestToExtraction:
    """Tests for section-to-extraction mapping."""

    @pytest.fixture
    def two_zone_source(self, tmp_path):
        content = """# Handoff — 2026-04-04

session_id: test-session
purpose: Built the handoff adapter

## Now

### Gotchas
- The old staged path no longer works
- Must run scan to get extractions

### Risks
- Format may change before stabilising

### Next
- Build composting process
- Deploy to hezza

## Compost

### Done
- b5ab093 Updated handoff adapter
- e386ed2 Wired extraction into scan
- Removed staged extraction

### Reflection
**Claude observed:** Section parsing is clean and fast.

**User noted:** This was the right architecture call.

### Learned
Handoffs are the richest single-session artifact. Parsing them replaces expensive LLM calls.
"""
        d = tmp_path / '-home-modha-Repos-test'
        d.mkdir()
        f = d / 'test-2026-04-04-1234.md'
        f.write_text(content)
        return HandoffSource.from_file(f)

    def test_extraction_has_all_fields(self, two_zone_source):
        ext = two_zone_source.to_extraction()
        assert ext is not None
        assert ext['summary'] == 'Built the handoff adapter'
        assert 'arc' in ext
        assert 'builds' in ext
        assert 'learnings' in ext
        assert 'friction' in ext
        assert 'patterns' in ext
        assert 'open_threads' in ext

    def test_done_to_builds(self, two_zone_source):
        ext = two_zone_source.to_extraction()
        builds = ext['builds']
        assert len(builds) == 3
        # Commit-prefixed items should have commit in details
        assert builds[0]['what'] == 'Updated handoff adapter'
        assert 'b5ab093' in builds[0]['details']
        # Non-commit items
        assert builds[2]['what'] == 'Removed staged extraction'
        assert builds[2]['details'] == ''

    def test_gotchas_to_friction(self, two_zone_source):
        ext = two_zone_source.to_extraction()
        friction = ext['friction']
        # 2 gotchas + 1 risk
        assert len(friction) == 3
        assert 'staged path' in friction[0]['problem']
        assert friction[2]['problem'].startswith('[risk]')

    def test_reflection_to_learnings(self, two_zone_source):
        ext = two_zone_source.to_extraction()
        learnings = ext['learnings']
        assert len(learnings) == 2
        assert 'Section parsing' in learnings[0]['insight']
        assert learnings[0]['context'] == 'Claude observed'
        assert 'architecture call' in learnings[1]['insight']
        assert learnings[1]['context'] == 'User noted'

    def test_learned_to_patterns(self, two_zone_source):
        ext = two_zone_source.to_extraction()
        patterns = ext['patterns']
        assert len(patterns) == 1
        assert 'richest single-session artifact' in patterns[0]

    def test_next_to_open_threads(self, two_zone_source):
        ext = two_zone_source.to_extraction()
        threads = ext['open_threads']
        assert len(threads) == 2
        assert 'composting process' in threads[0]
        assert 'hezza' in threads[1]

    def test_arc_structure(self, two_zone_source):
        ext = two_zone_source.to_extraction()
        arc = ext['arc']
        assert arc['started_with'] == 'Built the handoff adapter'
        assert len(arc['key_turns']) > 0
        assert arc['ended_at'] == 'Build composting process'

    def test_old_format_extraction(self, tmp_path):
        """Old-format handoffs should also produce extractions."""
        content = """# Handoff — 2025-12-29

## Done
- Fixed the rendering bug
- Added three tests

## Learned
The CSS grid layout has subtle differences across Safari and Chrome.

## Next
- Continue with phase 2
"""
        d = tmp_path / '-home-modha-Repos-test'
        d.mkdir()
        f = d / 'test-2025-12-29-1234.md'
        f.write_text(content)
        source = HandoffSource.from_file(f)
        ext = source.to_extraction()

        assert ext is not None
        assert len(ext['builds']) == 2
        assert 'rendering bug' in ext['builds'][0]['what']
        assert len(ext['patterns']) == 1
        assert 'CSS grid' in ext['patterns'][0]
        assert len(ext['open_threads']) == 1

    def test_empty_handoff_returns_none(self, tmp_path):
        """Handoff with no meaningful content returns None."""
        content = """# Handoff — 2025-12-29
"""
        d = tmp_path / '-home-modha-Repos-test'
        d.mkdir()
        f = d / 'test-2025-12-29-1234.md'
        f.write_text(content)
        source = HandoffSource.from_file(f)
        assert source.to_extraction() is None


class TestParseSections:
    """Tests for _parse_sections helper."""

    def test_old_format(self):
        content = """# Handoff — 2025-12-29

## Done
- Item 1

## Learned
Some text
"""
        sections = _parse_sections(content)
        assert 'Done' in sections
        assert 'Learned' in sections
        assert 'Item 1' in sections['Done']

    def test_two_zone_format(self):
        content = """# Handoff — 2026-04-04

## Now

### Gotchas
- Watch out

### Next
- Do more

## Compost

### Done
- Did something

### Learned
Architecture insight
"""
        sections = _parse_sections(content)
        assert 'Gotchas' in sections
        assert 'Next' in sections
        assert 'Done' in sections
        assert 'Learned' in sections
        assert 'Now' not in sections
        assert 'Compost' not in sections

    def test_multi_word_section_header(self):
        content = """# Handoff — 2025-12-29

## Open Questions
- Why?
"""
        sections = _parse_sections(content)
        assert 'Open Questions' in sections


class TestParsePreamble:
    """Tests for _parse_preamble helper."""

    def test_with_preamble(self):
        content = """# Handoff — 2026-04-04

session_id: abc-123
purpose: Did a thing

## Now
"""
        preamble = _parse_preamble(content)
        assert preamble['session_id'] == 'abc-123'
        assert preamble['purpose'] == 'Did a thing'

    def test_without_preamble(self):
        content = """# Handoff — 2025-12-29

## Done
- stuff
"""
        preamble = _parse_preamble(content)
        assert 'session_id' not in preamble
        assert 'purpose' not in preamble
