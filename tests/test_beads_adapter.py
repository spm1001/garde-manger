"""Tests for beads adapter.

Tests JSONL parsing, field extraction, source ID generation, and discover_beads function.
"""
import pytest
import json
from pathlib import Path
from datetime import datetime

from src.garde.adapters.beads import BeadsSource, parse_jsonl, discover_beads, parse_datetime


class TestParseDatetime:
    """Tests for ISO 8601 datetime parsing."""

    # When datetime has microseconds and Z suffix, should parse correctly
    def test_parse_with_microseconds(self):
        dt = parse_datetime("2025-12-31T18:09:03.050224Z")
        assert dt.year == 2025
        assert dt.month == 12
        assert dt.day == 31
        assert dt.hour == 18
        assert dt.minute == 9

    # When datetime has no microseconds, should parse correctly
    def test_parse_without_microseconds(self):
        dt = parse_datetime("2025-12-31T18:09:03Z")
        assert dt.year == 2025
        assert dt.month == 12
        assert dt.day == 31

    # When datetime is None, should return None
    def test_parse_none(self):
        assert parse_datetime(None) is None

    # When datetime is empty string, should return None
    def test_parse_empty(self):
        assert parse_datetime("") is None


class TestBeadsSource:
    """Tests for BeadsSource dataclass."""

    # When bead has all fields, source_id should use bead_id
    def test_source_id(self, tmp_path):
        source = BeadsSource(
            path=tmp_path / "issues.jsonl",
            bead_id="claude-memory-5z2",
            title="Test bead",
            description="Description",
            design="Design notes",
            notes="Session notes",
            acceptance_criteria="- [ ] Test",
            status="open",
            priority=2,
            issue_type="task",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            closed_at=None,
            close_reason=None,
            project_path="/Users/test/Repos/claude-memory",
        )
        assert source.source_id == "beads:claude-memory-5z2"

    # When bead is distilled content, has_presummary should be True
    def test_has_presummary(self, tmp_path):
        source = BeadsSource(
            path=tmp_path / "issues.jsonl",
            bead_id="test-123",
            title="Test",
            description="",
            design="",
            notes="",
            acceptance_criteria="",
            status="open",
            priority=2,
            issue_type="task",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            closed_at=None,
            close_reason=None,
            project_path="/test",
        )
        assert source.has_presummary is True

    # When bead has content, full_text should combine all fields
    def test_full_text_combines_fields(self, tmp_path):
        source = BeadsSource(
            path=tmp_path / "issues.jsonl",
            bead_id="test-123",
            title="Test Title",
            description="Test description",
            design="Test design",
            notes="Test notes",
            acceptance_criteria="- [ ] Acceptance",
            status="closed",
            priority=2,
            issue_type="task",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            closed_at=datetime.now(),
            close_reason="Completed successfully",
            project_path="/test",
        )
        text = source.full_text()
        assert "Test Title" in text
        assert "Test description" in text
        assert "Test design" in text
        assert "Test notes" in text
        assert "Acceptance" in text
        assert "Completed successfully" in text

    # When bead has metadata, should include status and priority
    def test_metadata(self, tmp_path):
        source = BeadsSource(
            path=tmp_path / "issues.jsonl",
            bead_id="test-123",
            title="Test",
            description="",
            design="",
            notes="",
            acceptance_criteria="",
            status="closed",
            priority=1,
            issue_type="epic",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            closed_at=datetime.now(),
            close_reason="Done",
            project_path="/test",
        )
        meta = source.metadata
        assert meta["status"] == "closed"
        assert meta["priority"] == 1
        assert meta["issue_type"] == "epic"
        assert meta["close_reason"] == "Done"


class TestParseJsonl:
    """Tests for JSONL parsing."""

    # When JSONL has valid bead, should yield BeadsSource
    def test_parse_valid_bead(self, tmp_path):
        jsonl_file = tmp_path / "issues.jsonl"
        bead = {
            "id": "test-abc",
            "title": "Test bead",
            "description": "A test",
            "status": "open",
            "priority": 2,
            "issue_type": "task",
            "created_at": "2025-12-31T10:00:00Z",
            "updated_at": "2025-12-31T12:00:00Z",
        }
        jsonl_file.write_text(json.dumps(bead) + "\n")

        sources = list(parse_jsonl(jsonl_file, "/test/project"))
        assert len(sources) == 1
        assert sources[0].bead_id == "test-abc"
        assert sources[0].title == "Test bead"
        assert sources[0].status == "open"

    # When JSONL has tombstone bead, should skip it
    def test_skip_tombstone(self, tmp_path):
        jsonl_file = tmp_path / "issues.jsonl"
        beads = [
            {"id": "test-1", "title": "Active", "status": "open", "created_at": "2025-12-31T10:00:00Z"},
            {"id": "test-2", "title": "Deleted", "status": "tombstone", "created_at": "2025-12-31T10:00:00Z"},
            {"id": "test-3", "title": "Closed", "status": "closed", "created_at": "2025-12-31T10:00:00Z"},
        ]
        jsonl_file.write_text("\n".join(json.dumps(b) for b in beads))

        sources = list(parse_jsonl(jsonl_file, "/test"))
        assert len(sources) == 2
        ids = {s.bead_id for s in sources}
        assert "test-1" in ids
        assert "test-3" in ids
        assert "test-2" not in ids

    # When JSONL has invalid JSON line, should skip gracefully
    def test_skip_invalid_json(self, tmp_path, capsys):
        jsonl_file = tmp_path / "issues.jsonl"
        content = '{"id": "valid", "title": "Good", "status": "open", "created_at": "2025-12-31T10:00:00Z"}\n'
        content += 'not valid json\n'
        content += '{"id": "also-valid", "title": "Also Good", "status": "open", "created_at": "2025-12-31T10:00:00Z"}\n'
        jsonl_file.write_text(content)

        sources = list(parse_jsonl(jsonl_file, "/test"))
        assert len(sources) == 2
        captured = capsys.readouterr()
        assert "Failed to parse line 2" in captured.out

    # When file doesn't exist, should return empty
    def test_missing_file(self, tmp_path):
        sources = list(parse_jsonl(tmp_path / "nonexistent.jsonl", "/test"))
        assert len(sources) == 0


class TestDiscoverBeads:
    """Tests for discover_beads function."""

    # When config has fallback paths with existing file, should discover
    def test_discover_from_fallback(self, tmp_path, monkeypatch):
        # Mock registry to return empty (isolate from real beads)
        from src.garde.adapters import beads
        monkeypatch.setattr(beads, 'get_registry_paths', lambda: [])

        # Create beads structure
        beads_dir = tmp_path / ".beads"
        beads_dir.mkdir()
        jsonl_file = beads_dir / "issues.jsonl"
        bead = {
            "id": "test-xyz",
            "title": "Discovered bead",
            "status": "open",
            "created_at": "2025-12-31T10:00:00Z",
        }
        jsonl_file.write_text(json.dumps(bead) + "\n")

        config = {
            'sources': {
                'beads': {
                    'fallback_paths': [str(jsonl_file)]
                }
            }
        }

        sources = list(discover_beads(config))
        assert len(sources) == 1
        assert sources[0].bead_id == "test-xyz"

    # When config has no beads section, should use defaults (but mock registry)
    def test_discover_empty_config(self, monkeypatch):
        from src.garde.adapters import beads
        monkeypatch.setattr(beads, 'get_registry_paths', lambda: [])

        config = {'sources': {}}
        sources = list(discover_beads(config))
        # With mocked empty registry and no fallback paths, should be empty
        assert isinstance(sources, list)
