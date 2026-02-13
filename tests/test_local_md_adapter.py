"""Tests for local_md adapter.

Tests title extraction, date parsing, and discover_local_md function.
"""
import pytest
from pathlib import Path
from datetime import datetime

from src.garde.adapters.local_md import LocalMdSource, discover_local_md


class TestTitleExtraction:
    """Tests for title extraction from markdown files."""

    # When file has H1 header, it should use that as title
    def test_title_from_h1(self, tmp_path):
        content = """# Meeting with Stefan

Some content here.
"""
        md_file = tmp_path / "test.md"
        md_file.write_text(content)

        source = LocalMdSource.from_file(md_file, tmp_path)
        assert source.title == "Meeting with Stefan"

    # When file has no H1 but has timestamp prefix in filename, should strip it
    def test_title_strips_timestamp_prefix(self, tmp_path):
        content = "No H1 here, just content."
        md_file = tmp_path / "202205261634 quarterly planning.md"
        md_file.write_text(content)

        source = LocalMdSource.from_file(md_file, tmp_path)
        assert source.title == "quarterly planning"

    # When filename has trailing date, should strip it
    def test_title_strips_trailing_date(self, tmp_path):
        content = "No H1 here."
        md_file = tmp_path / "tv squared-2022-05-26.md"
        md_file.write_text(content)

        source = LocalMdSource.from_file(md_file, tmp_path)
        assert source.title == "tv squared"

    # When filename has both timestamp prefix and trailing date, should strip both
    def test_title_strips_both_patterns(self, tmp_path):
        content = "No H1."
        md_file = tmp_path / "202205261634 tv squared-2022-05-26.md"
        md_file.write_text(content)

        source = LocalMdSource.from_file(md_file, tmp_path)
        assert source.title == "tv squared"

    # When file has no special patterns, should use filename stem
    def test_title_plain_filename(self, tmp_path):
        content = "Just content."
        md_file = tmp_path / "simple notes.md"
        md_file.write_text(content)

        source = LocalMdSource.from_file(md_file, tmp_path)
        assert source.title == "simple notes"


class TestDateParsing:
    """Tests for date extraction from filenames."""

    # When filename has YYYYMMDDHHmm format, should parse full datetime
    def test_date_from_timestamp_prefix(self, tmp_path):
        content = "Content"
        md_file = tmp_path / "202205261634 meeting.md"
        md_file.write_text(content)

        source = LocalMdSource.from_file(md_file, tmp_path)
        assert source.date.year == 2022
        assert source.date.month == 5
        assert source.date.day == 26
        assert source.date.hour == 16
        assert source.date.minute == 34

    # When filename has YYYY-MM-DD format, should parse date only
    def test_date_from_iso_format(self, tmp_path):
        content = "Content"
        md_file = tmp_path / "project-2023-11-15.md"
        md_file.write_text(content)

        source = LocalMdSource.from_file(md_file, tmp_path)
        assert source.date.year == 2023
        assert source.date.month == 11
        assert source.date.day == 15
        assert source.date.hour == 0
        assert source.date.minute == 0

    # When filename has no date pattern, should fall back to file mtime
    def test_date_fallback_to_mtime(self, tmp_path):
        content = "Content"
        md_file = tmp_path / "random notes.md"
        md_file.write_text(content)

        source = LocalMdSource.from_file(md_file, tmp_path)
        # Should be close to now (within a few seconds)
        now = datetime.now()
        delta = abs((now - source.date).total_seconds())
        assert delta < 10  # Within 10 seconds


class TestMtimeTracking:
    """Tests for mtime-based change detection."""

    # When file is parsed, mtime should be captured
    def test_mtime_captured(self, tmp_path):
        content = "Content"
        md_file = tmp_path / "test.md"
        md_file.write_text(content)

        source = LocalMdSource.from_file(md_file, tmp_path)
        assert source.mtime > 0
        assert isinstance(source.mtime, float)

    # When file mtime matches stat, should be consistent
    def test_mtime_matches_stat(self, tmp_path):
        content = "Content"
        md_file = tmp_path / "test.md"
        md_file.write_text(content)

        expected_mtime = md_file.stat().st_mtime
        source = LocalMdSource.from_file(md_file, tmp_path)
        assert source.mtime == expected_mtime


class TestSourceId:
    """Tests for source ID generation."""

    # When file is in base path, source_id should use relative path
    def test_source_id_relative(self, tmp_path):
        content = "Content"
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        md_file = subdir / "notes.md"
        md_file.write_text(content)

        source = LocalMdSource.from_file(md_file, tmp_path)
        assert source.source_id == "local_md:subdir:notes.md"

    # When file is at base path root, source_id should be just filename
    def test_source_id_root(self, tmp_path):
        content = "Content"
        md_file = tmp_path / "notes.md"
        md_file.write_text(content)

        source = LocalMdSource.from_file(md_file, tmp_path)
        assert source.source_id == "local_md:notes.md"


class TestDiscoverLocalMd:
    """Tests for discover_local_md function."""

    # When config has local_md paths, should discover files
    def test_discover_files(self, tmp_path):
        # Create test files
        (tmp_path / "note1.md").write_text("Note 1")
        (tmp_path / "note2.md").write_text("Note 2")
        (tmp_path / "not_md.txt").write_text("Not markdown")

        config = {
            'sources': {
                'local_md': {
                    'test': {
                        'path': str(tmp_path),
                        'pattern': '*.md'
                    }
                }
            }
        }

        sources = list(discover_local_md(config))
        assert len(sources) == 2
        titles = {s.title for s in sources}
        assert 'note1' in titles
        assert 'note2' in titles

    # When config has nested pattern, should discover nested files
    def test_discover_nested(self, tmp_path):
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "nested.md").write_text("Nested content")

        config = {
            'sources': {
                'local_md': {
                    'test': {
                        'path': str(tmp_path),
                        'pattern': '**/*.md'
                    }
                }
            }
        }

        sources = list(discover_local_md(config))
        assert len(sources) == 1
        assert sources[0].title == "nested"

    # When config has no local_md, should return empty
    def test_discover_empty_config(self):
        config = {'sources': {}}
        sources = list(discover_local_md(config))
        assert len(sources) == 0

    # When path doesn't exist, should skip gracefully
    def test_discover_missing_path(self, tmp_path, capsys):
        config = {
            'sources': {
                'local_md': {
                    'test': {
                        'path': str(tmp_path / "nonexistent"),
                        'pattern': '*.md'
                    }
                }
            }
        }

        sources = list(discover_local_md(config))
        # Silent skip for missing paths (cross-platform compatibility)
        assert len(sources) == 0
