"""Arc issue tracker adapter.

Indexes arc items from .arc/items.jsonl files across projects.

Arc is a lightweight work tracker using GTD vocabulary:
- Outcomes: desired results (similar to epics)
- Actions: next actions to achieve outcomes

Discovery uses glob patterns since arc doesn't have a registry.
"""

from pathlib import Path
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Iterator


@dataclass
class ArcSource:
    """An item (outcome or action) from the arc tracker."""
    path: Path                    # Path to items.jsonl
    item_id: str                  # e.g., "arc-gasoPe"
    title: str
    item_type: str                # outcome or action
    brief_why: str
    brief_what: str
    brief_done: str
    status: str                   # ready, done, waiting, etc.
    parent_id: str | None         # Parent outcome for actions
    created_at: datetime
    done_at: datetime | None
    project_path: str             # Derived from .arc location

    @property
    def source_id(self) -> str:
        return f"arc:{self.item_id}"

    @property
    def has_presummary(self) -> bool:
        # Arc items have distilled content in brief fields
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
    """Parse ISO 8601 datetime string from arc."""
    if not dt_str:
        return None
    try:
        dt_str = dt_str.rstrip('Z')
        return datetime.fromisoformat(dt_str)
    except (ValueError, TypeError):
        return None


def parse_jsonl(path: Path, project_path: str) -> Iterator[ArcSource]:
    """Parse items.jsonl and yield ArcSource objects."""
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

                yield ArcSource(
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
                print(f"Error processing arc item at line {line_num} in {path}: {e}")


def discover_arc(config: dict) -> Iterator[ArcSource]:
    """Discover all arc items from configured paths.

    Default paths: ~/Repos/*/.arc/items.jsonl
    """
    source_config = config.get('sources', {}).get('arc', {})

    paths = source_config.get('paths', [
        '~/Repos/*/.arc/items.jsonl',
    ])

    discovered = set()

    for pattern in paths:
        pattern = str(Path(pattern).expanduser())
        if '*' in pattern:
            base = pattern.split('*')[0]
            base_path = Path(base)
            if base_path.exists():
                glob_pattern = pattern[len(base):]
                for jsonl_path in base_path.glob(glob_pattern.lstrip('/')):
                    if str(jsonl_path) not in discovered:
                        discovered.add(str(jsonl_path))
                        # Project path is parent of .arc
                        project_path = str(jsonl_path.parent.parent)
                        yield from parse_jsonl(jsonl_path, project_path)
        else:
            jsonl_path = Path(pattern)
            if jsonl_path.exists() and str(jsonl_path) not in discovered:
                discovered.add(str(jsonl_path))
                project_path = str(jsonl_path.parent.parent)
                yield from parse_jsonl(jsonl_path, project_path)
