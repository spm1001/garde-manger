"""Bon work tracker adapter.

Indexes bon items from .bon/ directories across projects.
Supports both JSONL (items.jsonl) and Dolt (via bon CLI) backends.

Bon is a lightweight work tracker using GTD vocabulary:
- Outcomes: desired results (similar to epics)
- Actions: next actions to achieve outcomes

Discovery uses glob patterns since bon doesn't have a registry.
"""

from pathlib import Path
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Iterator


@dataclass
class BonSource:
    """An item (outcome or action) from the bon tracker."""
    path: Path                    # Path to items.jsonl
    item_id: str                  # e.g., "bon-gasoPe"
    title: str
    item_type: str                # outcome or action
    brief_why: str
    brief_what: str
    brief_done: str
    status: str                   # ready, done, waiting, etc.
    parent_id: str | None         # Parent outcome for actions
    created_at: datetime
    done_at: datetime | None
    project_path: str             # Derived from .bon location

    @property
    def source_id(self) -> str:
        return f"bon:{self.item_id}"

    @property
    def has_presummary(self) -> bool:
        # Bon items have distilled content in brief fields
        return True

    def full_text(self) -> str:
        """Combine all text fields for indexing."""
        parts = [self.title]
        if self.brief_why:
            parts.append(f"Why: {self.brief_why}")
        if self.brief_what:
            parts.append(f"What: {self.brief_what}")
        if self.brief_done:
            parts.append(f"Done when: {self.brief_done}")
        return "\n\n".join(parts)

    @property
    def metadata(self) -> dict:
        """Metadata for database storage."""
        return {
            "item_type": self.item_type,
            "status": self.status,
            "parent_id": self.parent_id,
        }


def parse_datetime(dt_str: str | None) -> datetime | None:
    """Parse ISO 8601 datetime string from bon."""
    if not dt_str:
        return None
    try:
        dt_str = dt_str.rstrip('Z')
        return datetime.fromisoformat(dt_str)
    except (ValueError, TypeError):
        return None


def parse_jsonl(path: Path, project_path: str) -> Iterator[BonSource]:
    """Parse items.jsonl and yield BonSource objects."""
    if not path.exists():
        return

    with open(path, 'r') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)

                # Skip deleted items if that field exists
                if data.get('deleted'):
                    continue

                brief = data.get('brief', {}) or {}
                created_at = parse_datetime(data.get('created_at'))
                done_at = parse_datetime(data.get('done_at'))

                if not created_at:
                    created_at = datetime.now()

                yield BonSource(
                    path=path,
                    item_id=data.get('id', f'unknown-{line_num}'),
                    title=data.get('title', ''),
                    item_type=data.get('type', 'action'),
                    brief_why=brief.get('why', '') or '',
                    brief_what=brief.get('what', '') or '',
                    brief_done=brief.get('done', '') or '',
                    status=data.get('status', 'ready'),
                    parent_id=data.get('parent'),
                    created_at=created_at,
                    done_at=done_at,
                    project_path=project_path,
                )
            except json.JSONDecodeError as e:
                print(f"Failed to parse line {line_num} in {path}: {e}")
            except Exception as e:
                print(f"Error processing bon item at line {line_num} in {path}: {e}")


def _get_backend(bon_dir: Path) -> str:
    """Read .bon/backend to determine storage type. Absent = jsonl."""
    backend_file = bon_dir / "backend"
    if backend_file.exists():
        return backend_file.read_text().strip()
    return "jsonl"


def _load_dolt_items(repo_path: Path) -> Iterator[BonSource]:
    """Load items from a Dolt-backed repo via bon list --jsonl."""
    try:
        result = subprocess.run(
            ["bon", "list", "--jsonl"],
            cwd=repo_path,
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return
        for line in result.stdout.strip().splitlines():
            if not line:
                continue
            try:
                data = json.loads(line)
                if data.get('deleted'):
                    continue
                brief = data.get('brief', {}) or {}
                created_at = parse_datetime(data.get('created_at'))
                if not created_at:
                    created_at = datetime.now()
                yield BonSource(
                    path=repo_path / ".bon",
                    item_id=data.get('id', 'unknown'),
                    title=data.get('title', ''),
                    item_type=data.get('type', 'action'),
                    brief_why=brief.get('why', '') or '',
                    brief_what=brief.get('what', '') or '',
                    brief_done=brief.get('done', '') or '',
                    status=data.get('status', 'ready'),
                    parent_id=data.get('parent'),
                    created_at=created_at,
                    done_at=parse_datetime(data.get('done_at')),
                    project_path=str(repo_path),
                )
            except (json.JSONDecodeError, Exception):
                continue
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return


def discover_bon(config: dict) -> Iterator[BonSource]:
    """Discover all bon items from configured paths.

    Default paths: ~/Repos/*/.bon/items.jsonl
    Also discovers Dolt-backed repos (no items.jsonl, but .bon/backend = dolt).
    """
    source_config = config.get('sources', {}).get('bon', {})

    paths = source_config.get('paths', [
        '~/Repos/*/.bon/items.jsonl',
    ])

    discovered = set()

    for pattern in paths:
        pattern = str(Path(pattern).expanduser())
        if '*' in pattern:
            base = pattern.split('*')[0]
            base_path = Path(base)
            if not base_path.exists():
                continue
            glob_pattern = pattern[len(base):]

            # JSONL repos: glob for items.jsonl as before
            for jsonl_path in base_path.glob(glob_pattern.lstrip('/')):
                project_path = str(jsonl_path.parent.parent)
                if project_path not in discovered:
                    discovered.add(project_path)
                    bon_dir = jsonl_path.parent
                    if _get_backend(bon_dir) == "dolt":
                        # items.jsonl is stale, use CLI
                        yield from _load_dolt_items(Path(project_path))
                    else:
                        yield from parse_jsonl(jsonl_path, project_path)

            # Dolt repos: glob for .bon/backend (no items.jsonl)
            bon_glob = glob_pattern.replace("items.jsonl", "backend")
            for backend_path in base_path.glob(bon_glob.lstrip('/')):
                if backend_path.read_text().strip() != "dolt":
                    continue
                project_path = str(backend_path.parent.parent)
                if project_path not in discovered:
                    discovered.add(project_path)
                    yield from _load_dolt_items(Path(project_path))
        else:
            jsonl_path = Path(pattern)
            project_path = str(jsonl_path.parent.parent)
            if project_path in discovered:
                continue
            discovered.add(project_path)
            bon_dir = jsonl_path.parent
            if _get_backend(bon_dir) == "dolt":
                yield from _load_dolt_items(Path(project_path))
            elif jsonl_path.exists():
                yield from parse_jsonl(jsonl_path, project_path)
