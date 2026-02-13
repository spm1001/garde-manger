"""Knowledge articles adapter.

Indexes curated knowledge articles (like OpenClaw's Moltbot memory files).
These are pre-distilled content that should be indexed directly without
LLM extraction — they're already in the right format.

Use cases:
- Agent self-knowledge (repos/*.md describing tools and patterns)
- Curated documentation
- Hand-written memory entries

Key differences from local_md:
- has_presummary = True: content is already distilled, skip LLM
- source_type = "knowledge": distinct from meeting notes
"""

from pathlib import Path
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterator


@dataclass
class KnowledgeSource:
    """A curated knowledge article."""
    path: Path
    base_path: Path
    title: str
    content: str
    mtime: float

    @property
    def source_id(self) -> str:
        """Stable identifier using relative path."""
        rel_path = self.path.relative_to(self.base_path)
        # Sanitize: replace / with : for ID format
        return f"knowledge:{str(rel_path).replace('/', ':')}"

    @property
    def source_type(self) -> str:
        return "knowledge"

    @property
    def has_presummary(self) -> bool:
        """Knowledge articles are already distilled — skip LLM extraction."""
        return True

    @property
    def project_path(self) -> str:
        """Return base path as "project"."""
        return str(self.base_path)

    @property
    def date(self) -> datetime:
        """Use file modification time as date."""
        return datetime.fromtimestamp(self.mtime)

    def full_text(self) -> str:
        """Return content for indexing.

        Knowledge articles are indexed as-is since they're already
        in the right format (distilled, structured).
        """
        return self.content

    @classmethod
    def from_file(cls, path: Path, base_path: Path) -> 'KnowledgeSource':
        """Create KnowledgeSource from a file."""
        stat = path.stat()
        mtime = stat.st_mtime
        content = path.read_text(errors='replace')

        # Extract title from first H1, or use filename
        h1_match = re.match(r'^#\s+(.+)$', content, re.MULTILINE)
        if h1_match:
            title = h1_match.group(1).strip()
        else:
            # Use filename without extension
            title = path.stem

        return cls(
            path=path,
            base_path=base_path,
            title=title,
            content=content,
            mtime=mtime,
        )


def discover_knowledge(config: dict) -> Iterator[KnowledgeSource]:
    """Discover knowledge articles from configured paths.

    Config format:
        sources:
          knowledge:
            repos:
              path: ~/.claude/memory/knowledge
              pattern: "**/*.md"
            architecture:
              path: ~/.claude/memory/architecture
              pattern: "*.md"
    """
    source_config = config.get('sources', {}).get('knowledge', {})

    if not source_config:
        return

    for name, path_config in source_config.items():
        if isinstance(path_config, dict):
            base_path = Path(path_config.get('path', '')).expanduser()
            pattern = path_config.get('pattern', '**/*.md')
        else:
            # Simple format: knowledge: path
            base_path = Path(path_config).expanduser()
            pattern = '**/*.md'

        if not base_path.exists():
            # Silent skip — path may not exist
            continue

        for file in base_path.glob(pattern):
            if file.is_file():
                try:
                    yield KnowledgeSource.from_file(file, base_path)
                except Exception as e:
                    print(f"Failed to parse knowledge file {file}: {e}")
