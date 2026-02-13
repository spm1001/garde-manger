"""Handoff files adapter.

Handoff files are structured markdown summaries from Claude Code sessions,
stored in ~/.claude/handoffs/<encoded-path>/*.md

Directory structure (Dec 2025+):
    ~/.claude/handoffs/
      -Users-jane-Repos-claude-memory/
        claude-memory-2025-12-27-1939.md
      -Users-jane-.claude/
        claude-config-2025-12-26-0003.md

The parent directory name encodes the project path (/ replaced with -).

Format:
    # Handoff — {date} ({mood})

    ## Done
    - item 1
    - item 2

    ## Learned
    text...

    ## Next
    text...

Key features:
- Information-dense distilled content
- Pre-structured sections (no LLM summarization needed)
- Project path derived from parent directory name
- Date in filename and header
"""

from pathlib import Path
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterator


def decode_parent_dir(parent_name: str) -> tuple[str, str]:
    """Decode parent directory name to (project_name, project_path).

    Parent dir format: -Users-username-Repos-project-name
    Since / was replaced with -, we use known path patterns as heuristics.

    Returns: (project_name, project_path)
    """
    home = str(Path.home())

    # Known base path patterns (order matters - more specific first)
    patterns = [
        ('-Repos-', f'{home}/Repos/'),
        ('-.claude-', f'{home}/.claude/'),
        ('-.claude', f'{home}/.claude'),  # Exact match for .claude itself
    ]

    for marker, base_path in patterns:
        if marker in parent_name:
            # Split on marker, take everything after as project name
            parts = parent_name.split(marker, 1)
            if len(parts) == 2 and parts[1]:
                project_name = parts[1]
                project_path = base_path + project_name
                return project_name, project_path
            elif marker == '-.claude' and (not parts[1] if len(parts) == 2 else True):
                # Exact match: parent is just "-Users-username-.claude"
                return 'claude-config', f'{home}/.claude'

    # Fallback: try to reconstruct path and extract last segment as project name
    # -Users-foo-Documents-MyProject -> /Users/foo/Documents/MyProject
    if parent_name.startswith('-'):
        # Replace leading - with / to start path reconstruction
        # This is imperfect (can't distinguish path separators from dashes in names)
        # but provides a reasonable guess for simple paths
        reconstructed = '/' + parent_name[1:]  # -Users-foo -> /Users-foo

        # Check if reconstructed path exists on filesystem
        if Path(reconstructed.replace('-', '/')).exists():
            project_path = reconstructed.replace('-', '/')
            project_name = project_path.rstrip('/').split('/')[-1]
            return project_name, project_path

        # If not, at least extract last segment as project name
        # Take everything after last occurrence of known username pattern
        # e.g., -Users-jane-Documents-foo -> foo
        segments = parent_name.lstrip('-').split('-')
        if len(segments) >= 3:
            # Assume pattern is Users-username-rest, take last segment
            project_name = segments[-1]
            return project_name, ''

    return '', ''


@dataclass
class HandoffSource:
    """A handoff file from Claude Code session."""
    path: Path
    project_name: str          # e.g., "claude-config"
    project_path: str          # e.g., "/Users/jane/.claude"
    date: datetime
    mood: str | None           # e.g., "momentum", "closure"
    sections: dict[str, str]   # Done, Learned, Interesting, Next, Reflection

    @property
    def source_id(self) -> str:
        # Use filename stem for stable identity
        return f"handoff:{self.path.stem}"

    @property
    def title(self) -> str:
        """Generate title from project name and date."""
        date_str = self.date.strftime("%Y-%m-%d")
        if self.mood:
            return f"{self.project_name} handoff ({self.mood}) — {date_str}"
        return f"{self.project_name} handoff — {date_str}"

    @property
    def has_presummary(self) -> bool:
        # Handoffs are already distilled summaries
        return True

    def full_text(self) -> str:
        """Combine all sections for indexing."""
        parts = []
        for section, content in self.sections.items():
            if content.strip():
                parts.append(f"## {section}\n{content}")
        return "\n\n".join(parts)

    @classmethod
    def from_file(cls, path: Path) -> 'HandoffSource':
        content = path.read_text()

        # Parse header: # Handoff — 2025-12-26 (momentum)
        header_match = re.match(
            r'^# Handoff — (\d{4}-\d{2}-\d{2})(?: \((\w+)\))?',
            content
        )
        if header_match:
            date = datetime.strptime(header_match.group(1), "%Y-%m-%d")
            mood = header_match.group(2)
        else:
            # Fallback: extract date from filename
            # Format: project-name-2025-12-26-1019.md
            date_match = re.search(r'(\d{4}-\d{2}-\d{2})', path.stem)
            if date_match:
                date = datetime.strptime(date_match.group(1), "%Y-%m-%d")
            else:
                date = datetime.fromtimestamp(path.stat().st_mtime)
            mood = None

        # Extract project info from parent directory (new structure)
        # Parent dir like "-Users-jane-Repos-claude-memory" encodes the path
        parent_name = path.parent.name
        project_name, project_path = decode_parent_dir(parent_name)

        # Fallback: try filename parsing if parent dir decode failed
        if not project_name:
            stem = path.stem
            # Remove date-time suffix: project-name-2025-12-26-1019.md
            project_name = re.sub(r'-\d{4}-\d{2}-\d{2}-\d{4}$', '', stem)
            # If still looks like a bare timestamp, use parent dir name as-is
            if re.match(r'^\d{4}-\d{2}-\d{2}$', project_name):
                project_name = parent_name.lstrip('-').split('-')[-1] or 'unknown'

        # Parse sections
        sections = {}
        section_pattern = re.compile(r'^## (\w+)\s*$', re.MULTILINE)
        matches = list(section_pattern.finditer(content))

        for i, match in enumerate(matches):
            section_name = match.group(1)
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
            section_content = content[start:end].strip()
            sections[section_name] = section_content

        return cls(
            path=path,
            project_name=project_name,
            project_path=project_path,
            date=date,
            mood=mood,
            sections=sections,
        )


def discover_handoffs(config: dict) -> Iterator[HandoffSource]:
    """Discover all handoff files."""
    source_config = config.get('sources', {}).get('handoffs', {})
    path = Path(source_config.get('path', '~/.claude/handoffs')).expanduser()
    pattern = source_config.get('pattern', '**/*.md')

    if not path.exists():
        return

    for file in path.glob(pattern):
        try:
            yield HandoffSource.from_file(file)
        except Exception as e:
            print(f"Failed to parse {file}: {e}")
