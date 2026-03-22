"""Tests for config loading."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from garde.config import (
    load_config, expand_paths, DEFAULT_CONFIG,
    get_db_path, get_data_dir, _migrate_db, PLUGIN_DATA_DIR_NAME,
)


def test_expand_paths_home():
    """Expand ~ in paths."""
    config = {'path': '~/.claude/memory'}
    expanded = expand_paths(config)
    assert expanded['path'] == str(Path.home() / '.claude' / 'memory')


def test_expand_paths_nested():
    """Expand ~ in nested dicts."""
    config = {
        'sources': {
            'claude_ai': {
                'path': '~/.claude/conversations'
            }
        }
    }
    expanded = expand_paths(config)
    assert '~' not in expanded['sources']['claude_ai']['path']


def test_expand_paths_list():
    """Expand ~ in list values."""
    config = {'scan_paths': ['~/.claude', '~/Documents']}
    expanded = expand_paths(config)
    assert all('~' not in p for p in expanded['scan_paths'])


def test_default_config_has_required_keys():
    """Default config has all required sections."""
    assert 'sources' in DEFAULT_CONFIG
    assert 'processing' in DEFAULT_CONFIG
    assert 'search' in DEFAULT_CONFIG
    assert 'claude_ai' in DEFAULT_CONFIG['sources']
    assert 'claude_code' in DEFAULT_CONFIG['sources']


# --- DB path resolution tests ---


@pytest.fixture
def fake_home(tmp_path):
    """Create a fake home with both legacy and plugin data dirs."""
    legacy_dir = tmp_path / '.claude' / 'memory'
    legacy_dir.mkdir(parents=True)
    plugin_dir = tmp_path / '.claude' / 'plugins' / 'data' / PLUGIN_DATA_DIR_NAME
    plugin_dir.mkdir(parents=True)
    backups_dir = legacy_dir / 'backups'
    backups_dir.mkdir()
    return tmp_path


def test_get_db_path_plugin_dir_preferred(fake_home):
    """When DB exists in plugin data dir, return that path."""
    plugin_db = fake_home / '.claude' / 'plugins' / 'data' / PLUGIN_DATA_DIR_NAME / 'memory.db'
    plugin_db.write_text('test')

    with patch('garde.config.Path.home', return_value=fake_home):
        result = get_db_path()
    assert result == plugin_db


def test_get_db_path_legacy_when_no_plugin_dir(fake_home):
    """When only legacy DB exists and no plugin data dir, return legacy."""
    # Remove the plugin data dir
    plugin_dir = fake_home / '.claude' / 'plugins' / 'data' / PLUGIN_DATA_DIR_NAME
    plugin_dir.rmdir()

    legacy_db = fake_home / '.claude' / 'memory' / 'memory.db'
    legacy_db.write_text('test')

    with patch('garde.config.Path.home', return_value=fake_home):
        result = get_db_path()
    assert result == legacy_db


def test_get_db_path_auto_migrates(fake_home):
    """When legacy DB exists and plugin data dir exists, auto-migrate."""
    legacy_db = fake_home / '.claude' / 'memory' / 'memory.db'
    legacy_db.write_text('test-db-content')
    plugin_db = fake_home / '.claude' / 'plugins' / 'data' / PLUGIN_DATA_DIR_NAME / 'memory.db'

    with patch('garde.config.Path.home', return_value=fake_home):
        result = get_db_path()

    # DB moved to plugin dir
    assert result == plugin_db
    assert plugin_db.exists()
    assert plugin_db.read_text() == 'test-db-content'
    # Symlink left at legacy location
    assert legacy_db.is_symlink()
    assert legacy_db.resolve() == plugin_db
    # Backup created
    backups = list((fake_home / '.claude' / 'memory' / 'backups').glob('memory-pre-migration-*.db'))
    assert len(backups) == 1


def test_get_db_path_fresh_install_with_plugin_dir(fake_home):
    """Fresh install: no DB anywhere, plugin data dir exists → return plugin path."""
    with patch('garde.config.Path.home', return_value=fake_home):
        result = get_db_path()
    expected = fake_home / '.claude' / 'plugins' / 'data' / PLUGIN_DATA_DIR_NAME / 'memory.db'
    assert result == expected


def test_get_db_path_fresh_install_no_plugin_dir(fake_home):
    """Fresh install: no DB, no plugin data dir → return legacy path."""
    plugin_dir = fake_home / '.claude' / 'plugins' / 'data' / PLUGIN_DATA_DIR_NAME
    plugin_dir.rmdir()

    with patch('garde.config.Path.home', return_value=fake_home):
        result = get_db_path()
    expected = fake_home / '.claude' / 'memory' / 'memory.db'
    assert result == expected


def test_get_db_path_symlink_not_remigrated(fake_home):
    """If legacy is already a symlink, don't migrate again."""
    plugin_db = fake_home / '.claude' / 'plugins' / 'data' / PLUGIN_DATA_DIR_NAME / 'memory.db'
    plugin_db.write_text('migrated')
    legacy_db = fake_home / '.claude' / 'memory' / 'memory.db'
    legacy_db.symlink_to(plugin_db)

    with patch('garde.config.Path.home', return_value=fake_home):
        result = get_db_path()
    assert result == plugin_db
