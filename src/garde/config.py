"""Configuration loading for conversation memory system.

Config lives at ~/.claude/memory/config.yaml alongside other Claude Code config.
Glossary lives at ~/.claude/memory/glossary.yaml.
Database lives at ~/.claude/plugins/data/garde-manger-batterie-de-savoir/memory.db
(plugin data dir, persists across plugin version updates) with auto-migration
from the legacy ~/.claude/memory/memory.db location.

If config doesn't exist, creates from template with sensible defaults.
"""

import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any
import yaml

log = logging.getLogger(__name__)

PLUGIN_DATA_DIR_NAME = 'garde-manger-batterie-de-savoir'


def encode_cwd(cwd: str) -> str:
    """Encode a directory path the way Claude Code does for project dirs.

    Replaces all non-alphanumeric, non-hyphen characters with hyphens.
    Must match the pattern in scripts/stage-extraction.sh:
        echo "$DIR" | sed 's/[^a-zA-Z0-9-]/-/g'
    """
    import re
    return re.sub(r'[^a-zA-Z0-9-]', '-', cwd)


def get_data_dir() -> Path:
    """Get the plugin data directory (persists across plugin version updates).

    Returns ~/.claude/plugins/data/garde-manger-batterie-de-savoir/.
    Does NOT create the directory — it's created by Claude Code on plugin install.
    """
    return Path.home() / '.claude' / 'plugins' / 'data' / PLUGIN_DATA_DIR_NAME


def get_memory_dir() -> Path:
    """Get the legacy memory directory (~/.claude/memory/).

    Still used for config.yaml, glossary.yaml, and backups.
    """
    return Path.home() / '.claude' / 'memory'


def get_config_path() -> Path:
    """Get the config file path."""
    return get_memory_dir() / 'config.yaml'


def get_glossary_path() -> Path:
    """Get the glossary file path."""
    return get_memory_dir() / 'glossary.yaml'


def _migrate_db(legacy_db: Path, plugin_db: Path) -> None:
    """Move DB from legacy location to plugin data dir, leave symlink behind."""
    backup_dir = get_memory_dir() / 'backups'
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    backup_path = backup_dir / f'memory-pre-migration-{timestamp}.db'

    log.info("Migrating DB: %s → %s", legacy_db, plugin_db)

    # Backup first
    shutil.copy2(legacy_db, backup_path)
    log.info("Backup created: %s", backup_path)

    # Move (shutil.move handles cross-filesystem; same-fs is still instant)
    shutil.move(str(legacy_db), str(plugin_db))

    # Symlink at legacy location for backward compat
    legacy_db.symlink_to(plugin_db)
    log.info("Migration complete, symlink at %s", legacy_db)


def get_db_path() -> Path:
    """Get the SQLite database path.

    Resolution order:
    1. Plugin data dir (preferred — persists across plugin updates)
    2. Auto-migrate from legacy if plugin data dir exists
    3. Legacy location (~/.claude/memory/memory.db)
    4. Fresh install: plugin data dir if it exists, else legacy
    """
    plugin_db = get_data_dir() / 'memory.db'
    legacy_db = get_memory_dir() / 'memory.db'

    # Already at plugin data dir (or symlink resolves there)
    if plugin_db.exists():
        return plugin_db

    # Auto-migrate: legacy DB exists + plugin data dir exists → move + symlink
    if legacy_db.exists() and not legacy_db.is_symlink() and get_data_dir().is_dir():
        try:
            _migrate_db(legacy_db, plugin_db)
            return plugin_db
        except OSError as e:
            log.warning("DB migration failed, using legacy path: %s", e)
            return legacy_db

    # Legacy location (existing install, plugin not yet registered)
    if legacy_db.exists():
        return legacy_db

    # Fresh install: prefer plugin data dir if it exists
    if get_data_dir().is_dir():
        return plugin_db

    # Fallback: legacy location
    return legacy_db


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


