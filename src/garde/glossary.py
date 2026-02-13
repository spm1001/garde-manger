"""Glossary loading and entity resolution.

The glossary maps alternative names/aliases to canonical entity identifiers.
Used during ingestion to normalize entity references.

Glossary lives at ~/.claude/memory/glossary.yaml
"""

from pathlib import Path
from typing import Any
import yaml

from .config import get_glossary_path


class Glossary:
    """Entity glossary for resolution during ingestion."""

    def __init__(self, data: dict[str, Any]):
        self._data = data
        self._entities = data.get('entities', {})
        self._auto_mappings = data.get('auto_mappings', {})

        # Build reverse lookup: alias -> entity_key
        self._alias_index: dict[str, str] = {}
        for key, entity in self._entities.items():
            # Index canonical name
            name = entity.get('name', '').lower()
            if name:
                self._alias_index[name] = key

            # Index all aliases
            for alias in entity.get('aliases', []):
                self._alias_index[alias.lower()] = key

        # Add auto_mappings to index
        for alias, entity_key in self._auto_mappings.items():
            self._alias_index[alias.lower()] = entity_key

    def resolve(self, mention: str) -> str | None:
        """
        Resolve a mention to its canonical entity key.

        Returns entity key if found, None if unknown.
        """
        return self._alias_index.get(mention.lower())

    def get(self, key: str) -> dict[str, Any] | None:
        """Get entity data by key."""
        return self._entities.get(key)

    def get_name(self, key: str) -> str | None:
        """Get canonical name for entity key."""
        entity = self._entities.get(key)
        return entity.get('name') if entity else None

    def get_parent(self, key: str) -> str | None:
        """Get parent entity key."""
        entity = self._entities.get(key)
        return entity.get('parent') if entity else None

    def get_ancestors(self, key: str) -> list[str]:
        """Get list of ancestor keys from immediate parent to root."""
        ancestors = []
        current = self.get_parent(key)
        while current:
            ancestors.append(current)
            current = self.get_parent(current)
        return ancestors

    def list_by_type(self, entity_type: str) -> list[str]:
        """List all entity keys of a given type."""
        return [
            key for key, entity in self._entities.items()
            if entity.get('type') == entity_type
        ]

    def list_children(self, parent_key: str) -> list[str]:
        """List all entity keys that have this parent."""
        return [
            key for key, entity in self._entities.items()
            if entity.get('parent') == parent_key
        ]

    @property
    def entities(self) -> dict[str, Any]:
        """Access raw entities dict."""
        return self._entities

    @property
    def auto_mappings(self) -> dict[str, str]:
        """Access auto_mappings dict."""
        return self._auto_mappings

    @property
    def raw(self) -> dict[str, Any]:
        """Access raw data dict (for extraction prompts)."""
        return self._data

    def add_auto_mapping(self, alias: str, entity_key: str) -> None:
        """Add a new auto-mapping (for review later)."""
        self._auto_mappings[alias] = entity_key
        self._alias_index[alias.lower()] = entity_key

    def sample_for_prompt(self, max_entities: int = 20) -> str:
        """
        Format a sample of entities for inclusion in extraction prompts.

        Returns a string showing entity names, types, and key aliases.
        """
        lines = []
        count = 0
        for key, entity in self._entities.items():
            if count >= max_entities:
                break
            name = entity.get('name', key)
            etype = entity.get('type', 'unknown')
            aliases = entity.get('aliases', [])
            alias_str = f" (also: {', '.join(aliases[:3])})" if aliases else ""
            lines.append(f"- {name} [{etype}]{alias_str}")
            count += 1

        if len(self._entities) > max_entities:
            lines.append(f"... and {len(self._entities) - max_entities} more entities")

        return '\n'.join(lines)


def load_glossary() -> Glossary:
    """
    Load glossary from ~/.claude/memory/glossary.yaml.

    Returns empty glossary if file doesn't exist.
    """
    glossary_path = get_glossary_path()

    if glossary_path.exists():
        with open(glossary_path) as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {'version': 1, 'entities': {}, 'auto_mappings': {}}

    return Glossary(data)


def save_glossary(glossary: Glossary) -> None:
    """Save glossary back to file (e.g., after adding auto_mappings)."""
    glossary_path = get_glossary_path()
    glossary_path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        'version': glossary._data.get('version', 1),
        'entities': glossary.entities,
        'auto_mappings': glossary.auto_mappings,
    }

    with open(glossary_path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
