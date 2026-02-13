"""Configuration loading for conversation memory system.

Config lives at ~/.claude/memory/config.yaml alongside other Claude Code config.
Glossary lives at ~/.claude/memory/glossary.yaml.

If config doesn't exist, creates from template with sensible defaults.
"""

from pathlib import Path
from typing import Any
import yaml


def get_memory_dir() -> Path:
    """Get the memory system directory (~/.claude/memory/)."""
    return Path.home() / '.claude' / 'memory'


def get_config_path() -> Path:
    """Get the config file path."""
    return get_memory_dir() / 'config.yaml'


def get_glossary_path() -> Path:
    """Get the glossary file path."""
    return get_memory_dir() / 'glossary.yaml'


def get_db_path() -> Path:
    """Get the SQLite database path."""
    return get_memory_dir() / 'memory.db'


DEFAULT_CONFIG = {
    'sources': {
        'claude_ai': {
            'path': '~/.claude/claude-ai/cache/conversations',
            'pattern': '*.json',
        },
        'claude_code': {
            'path': '~/.claude/projects',
            'pattern': '**/*.jsonl',
            'min_lines': 10,
            'include_subagents': True,
        },
        'cloud_sessions': {
            'path': '~/.claude/claude-ai/cache/sessions',
            'pattern': 'session_*.json',
        },
        'claude_desktop': {
            'enabled': False,
            'path': '~/Library/Application Support/Claude',
            'pattern': '**/*.json',
        },
        'local_md': {},
        'knowledge': {},  # Curated knowledge articles (already distilled, skip LLM)
        'google': {
            'enabled': False,
            'credentials_path': '~/.claude/memory/google_credentials.json',
        },
    },
    'processing': {
        'batch_size': 20,
        'summary_target_words': 200,
        'max_context_tokens': 100000,
        'skip_tool_results': True,
        'max_content_chars': 80000,  # threshold for triggering chunking
        'chunk_size': 140000,        # chars, for fixed-size chunking (fallback)
        'chunk_overlap': 5000,       # overlap between chunks (fixed-size)
        # Semantic chunking settings (topic-boundary-aware)
        'semantic_chunk_min': 15000,    # min chunk size - merge smaller with neighbors
        'semantic_chunk_max': 80000,    # max chunk size - split larger at paragraph breaks
        'semantic_chunk_target': 40000,  # target chunk size for single-topic chunks
    },
    'search': {
        'default_results': 5,
        'snippet_chars': 200,
        'exclude_subagents': False,
    },
}


def expand_paths(config: dict[str, Any]) -> dict[str, Any]:
    """Recursively expand ~ in path values."""
    result = {}
    for key, value in config.items():
        if isinstance(value, dict):
            result[key] = expand_paths(value)
        elif isinstance(value, list):
            result[key] = [
                str(Path(v).expanduser()) if isinstance(v, str) and '~' in v else v
                for v in value
            ]
        elif isinstance(value, str) and '~' in value:
            result[key] = str(Path(value).expanduser())
        else:
            result[key] = value
    return result


def load_config() -> dict[str, Any]:
    """
    Load configuration from ~/.claude/memory/config.yaml.

    Creates config directory and file from defaults if they don't exist.
    Expands ~ in all path values.
    """
    config_path = get_config_path()

    # Ensure directory exists
    config_path.parent.mkdir(parents=True, exist_ok=True)

    if config_path.exists():
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
    else:
        # Create from defaults
        config = DEFAULT_CONFIG.copy()
        with open(config_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    # Merge with defaults (in case config is missing keys)
    merged = _deep_merge(DEFAULT_CONFIG, config)

    # Expand paths
    return expand_paths(merged)


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge override into base, preferring override values."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


