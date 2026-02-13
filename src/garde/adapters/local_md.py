"""Local markdown files adapter.

Indexes markdown files from configured directories for search.

Supports:
- Meeting notes (with date/title extraction from filename)
- General markdown files
- Nested directory structures

Files are indexed by their content directly (no LLM summarization by default).
"""

from pathlib import Path
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterator


@dataclass
class LocalMdSource:
    """A local markdown file."""
    path: Path
    base_path: Path          # The configured root directory
    title: str
    date: datetime
    content: str
    mtime: float             # File modification time (for change detection)

    @property
    def source_id(self) -> str:
        # Use relative path from base for stable identity
        rel_path = self.path.relative_to(self.base_path)
        # Sanitize: replace / with : for ID format
        return f"local_md:{str(rel_path).replace('/', ':')}"

    @property
    def has_presummary(self) -> bool:
        # Local files need summarization (but we'll index content directly for now)
        return False

    @property
    def project_path(self) -> str:
        # Return the base path as "project"
        return str(self.base_path)

    def full_text(self) -> str:
        """Return content for indexing."""
        return self.content

    @classmethod
    def from_file(cls, path: Path, base_path: Path) -> 'LocalMdSource':
        stat = path.stat()
        mtime = stat.st_mtime
        content = path.read_text(errors='replace')

        # Extract title from first H1, or filename
        h1_match = re.match(r'^#\s+(.+)$', content, re.MULTILINE)
        if h1_match:
            title = h1_match.group(1).strip()
        else:
            # Use filename without extension
            title = path.stem
            # Clean up common patterns like "202205261634 tv squared-2022-05-26"
            # Remove leading timestamp
            title = re.sub(r'^\d{12}\s*', '', title)
            # Remove trailing date
            title = re.sub(r'-\d{4}-\d{2}-\d{2}$', '', title)
            title = title.strip(' -')

        # Extract date from filename or file mtime
        # Patterns: "202205261634 ..." or "2022-05-26" in filename
        date_match = re.search(r'(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})', path.stem)
        if date_match:
            # YYYYMMDDHHmm format
            date = datetime(
                int(date_match.group(1)),
                int(date_match.group(2)),
                int(date_match.group(3)),
                int(date_match.group(4)),
                int(date_match.group(5))
            )
        else:
            # Try YYYY-MM-DD format
            date_match = re.search(r'(\d{4})-(\d{2})-(\d{2})', path.stem)
            if date_match:
                date = datetime(
                    int(date_match.group(1)),
                    int(date_match.group(2)),
                    int(date_match.group(3))
                )
            else:
                # Fallback to file mtime (already captured above)
                date = datetime.fromtimestamp(mtime)

        return cls(
            path=path,
            base_path=base_path,
            title=title,
            date=date,
            content=content,
            mtime=mtime,
        )


def discover_local_md(config: dict) -> Iterator[LocalMdSource]:
    """Discover all local markdown files from configured paths."""
    source_config = config.get('sources', {}).get('local_md', {})

    if not source_config:
        return

    # Support multiple named paths
    # local_md:
    #   meeting_notes:
    #     path: ~/Drive/Work/Meeting Notes
    #     pattern: "**/*.md"
    for name, path_config in source_config.items():
        if isinstance(path_config, dict):
            base_path = Path(path_config.get('path', '')).expanduser()
            pattern = path_config.get('pattern', '**/*.md')
        else:
            # Simple format: local_md: path
            base_path = Path(path_config).expanduser()
            pattern = '**/*.md'

        if not base_path.exists():
            # Silent skip — path may not exist on all platforms (e.g., Linux vs macOS)
            continue

        for file in base_path.glob(pattern):
            if file.is_file():
                try:
                    yield LocalMdSource.from_file(file, base_path)
                except Exception as e:
                    print(f"Failed to parse {file}: {e}")
