"""Beads issue tracker adapter.

Indexes beads from .beads/issues.jsonl files across projects.

Beads are issues from the bd issue tracker, containing:
- Design decisions and architectural notes
- Implementation details and acceptance criteria
- Session handoff notes and field reports

Discovery uses:
1. ~/.beads/registry.json (tracks all active bd daemons)
2. Fallback glob patterns for dormant projects

The JSONL file is the source of truth (git-tracked), not the SQLite database.
"""

from pathlib import Path
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterator


@dataclass
class BeadsSource:
    """A bead (issue) from the bd issue tracker."""
    path: Path                    # Path to issues.jsonl
    bead_id: str                  # e.g., "claude-memory-5z2"
    title: str
    description: str
    design: str
    notes: str
    acceptance_criteria: str
    status: str                   # open, closed, tombstone
    priority: int
    issue_type: str               # task, epic, bug, feature
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None
    close_reason: str | None
    project_path: str             # Derived from workspace path

    @property
    def source_id(self) -> str:
        # Bead IDs are already globally unique (include project prefix)
        return f"beads:{self.bead_id}"

    @property
    def has_presummary(self) -> bool:
        # Beads have distilled content in design/notes fields
        return True

    def full_text(self) -> str:
        """Combine all text fields for indexing."""
        parts = [self.title]
        if self.description:
            parts.append(self.description)
        if self.design:
            parts.append(self.design)
        if self.notes:
            parts.append(self.notes)
        if self.acceptance_criteria:
            parts.append(self.acceptance_criteria)
        if self.close_reason:
            parts.append(f"Close reason: {self.close_reason}")
        return "\n\n".join(parts)

    @property
    def metadata(self) -> dict:
        """Metadata for database storage."""
        return {
            "status": self.status,
            "priority": self.priority,
            "issue_type": self.issue_type,
            "close_reason": self.close_reason,
        }


def parse_datetime(dt_str: str | None) -> datetime | None:
    """Parse ISO 8601 datetime string from beads."""
    if not dt_str:
        return None
    # Handle formats: 2025-12-31T18:09:03.050224Z or 2025-12-31T18:09:03Z
    try:
        # Remove Z suffix and parse
        dt_str = dt_str.rstrip('Z')
        if '.' in dt_str:
            return datetime.fromisoformat(dt_str)
        return datetime.fromisoformat(dt_str)
    except (ValueError, TypeError):
        return None


def parse_jsonl(path: Path, project_path: str) -> Iterator['BeadsSource']:
    """Parse issues.jsonl and yield BeadsSource objects.

    Args:
        path: Path to issues.jsonl file
        project_path: Workspace path this beads file belongs to
    """
    if not path.exists():
        return

    with open(path, 'r') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)

                # Skip tombstoned (deleted) beads
                status = data.get('status', 'open')
                if status == 'tombstone':
                    continue

                created_at = parse_datetime(data.get('created_at'))
                updated_at = parse_datetime(data.get('updated_at'))
                closed_at = parse_datetime(data.get('closed_at'))

                # Use updated_at or created_at for datetime
                if not created_at:
                    created_at = datetime.now()
                if not updated_at:
                    updated_at = created_at

                yield BeadsSource(
                    path=path,
                    bead_id=data.get('id', f'unknown-{line_num}'),
                    title=data.get('title', ''),
                    description=data.get('description', '') or '',
                    design=data.get('design', '') or '',
                    notes=data.get('notes', '') or '',
                    acceptance_criteria=data.get('acceptance_criteria', '') or '',
                    status=status,
                    priority=data.get('priority', 2),
                    issue_type=data.get('issue_type', 'task'),
                    created_at=created_at,
                    updated_at=updated_at,
                    closed_at=closed_at,
                    close_reason=data.get('close_reason', '') or '',
                    project_path=project_path,
                )
            except json.JSONDecodeError as e:
                print(f"Failed to parse line {line_num} in {path}: {e}")
            except Exception as e:
                print(f"Error processing bead at line {line_num} in {path}: {e}")


def get_registry_paths() -> list[tuple[Path, str]]:
    """Get beads paths from ~/.beads/registry.json.

    Returns list of (issues.jsonl path, workspace_path) tuples.
    """
    registry_path = Path.home() / '.beads' / 'registry.json'
    if not registry_path.exists():
        return []

    try:
        with open(registry_path, 'r') as f:
            registry = json.load(f)

        paths = []
        for entry in registry:
            workspace = entry.get('workspace_path', '')
            if workspace:
                jsonl_path = Path(workspace) / '.beads' / 'issues.jsonl'
                if jsonl_path.exists():
                    paths.append((jsonl_path, workspace))
        return paths
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        print(f"Failed to parse beads registry: {e}")
        return []


def discover_beads(config: dict) -> Iterator[BeadsSource]:
    """Discover all beads from registry and fallback paths.

    Discovery order:
    1. ~/.beads/registry.json (tracks active daemon workspaces)
    2. Fallback glob patterns from config
    """
    source_config = config.get('sources', {}).get('beads', {})

    # Track discovered paths to avoid duplicates
    discovered_paths = set()

    # 1. Registry-based discovery
    for jsonl_path, workspace_path in get_registry_paths():
        if str(jsonl_path) not in discovered_paths:
            discovered_paths.add(str(jsonl_path))
            yield from parse_jsonl(jsonl_path, workspace_path)

    # 2. Fallback paths from config
    fallback_paths = source_config.get('fallback_paths', [
        '~/Repos/*/.beads/issues.jsonl',
        '~/.claude/.beads/issues.jsonl',
    ])

    for pattern in fallback_paths:
        pattern = str(Path(pattern).expanduser())
        # Handle glob patterns
        if '*' in pattern:
            base = pattern.split('*')[0]
            base_path = Path(base)
            if base_path.exists():
                glob_pattern = pattern[len(base):]
                for jsonl_path in base_path.glob(glob_pattern.lstrip('/')):
                    if str(jsonl_path) not in discovered_paths:
                        discovered_paths.add(str(jsonl_path))
                        # Extract workspace path (parent of .beads)
                        workspace_path = str(jsonl_path.parent.parent)
                        yield from parse_jsonl(jsonl_path, workspace_path)
        else:
            jsonl_path = Path(pattern)
            if jsonl_path.exists() and str(jsonl_path) not in discovered_paths:
                discovered_paths.add(str(jsonl_path))
                workspace_path = str(jsonl_path.parent.parent)
                yield from parse_jsonl(jsonl_path, workspace_path)
