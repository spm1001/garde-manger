"""Tests for config loading."""

import tempfile
from pathlib import Path

import pytest

from garde.config import load_config, expand_paths, DEFAULT_CONFIG


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
