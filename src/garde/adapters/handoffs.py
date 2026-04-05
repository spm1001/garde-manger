"""Handoff files adapter.

Handoff files are structured markdown summaries from Claude Code sessions,
stored in ~/.claude/handoffs/<encoded-path>/*.md or .bon/handoffs/*.md

Two formats supported:

Old format (flat h2 sections):
    # Handoff — {date} ({mood})
    ## Done
    ## Learned
    ## Next

New two-zone format (fond-v1):
    # Handoff — {date}
    session_id: ...
    purpose: ...
    ## Now
    ### Gotchas
    ### Risks
    ### Next
    ### Commands
    ## Compost
    ### Done
    ### Reflection
    ### Learned

Key features:
- Information-dense distilled content
- Pre-structured sections (no LLM summarization needed)
- Project path derived from parent directory name
- Date in filename and header
- Two-zone handoffs produce garde extractions from section parse (no LLM)
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


def _parse_sections(content: str) -> dict[str, str]:
    """Parse markdown sections from handoff content.

    Handles both formats:
    - Old: flat h2 sections (## Done, ## Learned, ## Next)
    - New (fond-v1): h2 zones (## Now, ## Compost) with h3 subsections

    For two-zone format, returns the h3 subsections as top-level keys
    (e.g., "Done", "Gotchas") — the zone names (Now, Compost) are structural,
    not content-bearing.
    """
    # Detect two-zone format by looking for ## Now or ## Compost
    has_zones = bool(re.search(r'^## (?:Now|Compost)\b', content, re.MULTILINE))

    if has_zones:
        # Parse h3 subsections as the meaningful sections
        sections = {}
        pattern = re.compile(r'^### (.+?)\s*$', re.MULTILINE)
        matches = list(pattern.finditer(content))
        for i, match in enumerate(matches):
            name = match.group(1).strip()
            start = match.end()
            # End at next h2 or h3, whichever comes first
            end = len(content)
            for j in range(i + 1, len(matches)):
                end = matches[j].start()
                break
            # Also check for h2 boundaries within the range
            next_h2 = re.search(r'^## ', content[start:end], re.MULTILINE)
            if next_h2:
                end = start + next_h2.start()
            sections[name] = content[start:end].strip()
        return sections
    else:
        # Old format: flat h2 sections
        sections = {}
        pattern = re.compile(r'^## (.+?)\s*$', re.MULTILINE)
        matches = list(pattern.finditer(content))
        for i, match in enumerate(matches):
            name = match.group(1).strip()
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
            sections[name] = content[start:end].strip()
        return sections


def _parse_preamble(content: str) -> dict[str, str]:
    """Extract session_id and purpose from preamble lines before the first h2 section."""
    preamble = {}
    first_h2 = re.search(r'^## ', content, re.MULTILINE)
    text = content[:first_h2.start()] if first_h2 else content
    for line in text.splitlines():
        if line.startswith('session_id:'):
            preamble['session_id'] = line.split(':', 1)[1].strip()
        elif line.startswith('purpose:'):
            preamble['purpose'] = line.split(':', 1)[1].strip()
    return preamble


@dataclass
class HandoffSource:
    """A handoff file from Claude Code session."""
    path: Path
    project_name: str          # e.g., "claude-config"
    project_path: str          # e.g., "/Users/jane/.claude"
    date: datetime
    mood: str | None           # e.g., "momentum", "closure"
    sections: dict[str, str]   # Done, Learned, Gotchas, Next, Reflection, etc.
    purpose: str | None = None # From preamble "purpose:" line
    session_id: str | None = None  # From preamble "session_id:" line
    mtime: float = 0.0             # File modification time for change detection

    @property
    def source_id(self) -> str:
        # Use filename stem for stable identity
        return f"handoff:{self.path.stem}"

    @property
    def title(self) -> str:
        """Generate title from purpose or project name and date."""
        date_str = self.date.strftime("%Y-%m-%d")
        if self.purpose:
            return f"{self.project_name}: {self.purpose} — {date_str}"
        if self.mood:
            return f"{self.project_name} handoff ({self.mood}) — {date_str}"
        return f"{self.project_name} handoff — {date_str}"

    @property
    def has_presummary(self) -> bool:
        # Handoffs are already distilled summaries
        return True

    @property
    def is_two_zone(self) -> bool:
        """Whether this handoff uses the fond-v1 two-zone format."""
        return any(k in ('Gotchas', 'Risks', 'Commands')
                   for k in self.sections) or self.purpose is not None

    def full_text(self) -> str:
        """Combine all sections for indexing."""
        parts = []
        for section, content in self.sections.items():
            if content.strip():
                parts.append(f"## {section}\n{content}")
        return "\n\n".join(parts)

    def to_extraction(self) -> dict | None:
        """Map handoff sections to garde extraction fields.

        Returns a dict matching the extraction schema, or None if the handoff
        has no meaningful content to extract.

        Mapping:
            Done → builds [{what, details}]
            Gotchas → friction [{problem, resolution}]
            Reflection → learnings [{insight, why_it_matters, context}]
            Learned → patterns [string]
            Next → open_threads [string]
            purpose → summary
        """
        s = self.sections

        # Build summary from purpose or first available content
        summary = self.purpose
        if not summary:
            # Fall back to first sentence of Done or Reflection
            for key in ('Done', 'Reflection', 'Learned'):
                if s.get(key):
                    summary = s[key][:200].split('\n')[0]
                    break

        if not summary:
            return None

        # Done → builds
        builds = []
        if s.get('Done'):
            for line in s['Done'].splitlines():
                line = line.strip()
                if line.startswith('- '):
                    item = line[2:].strip()
                    # Check for "commit_hash description" pattern
                    commit_match = re.match(r'^([0-9a-f]{7,}) (.+)', item)
                    if commit_match:
                        builds.append({'what': commit_match.group(2),
                                       'details': f'commit {commit_match.group(1)}'})
                    else:
                        builds.append({'what': item, 'details': ''})
                elif line and not line.startswith('#'):
                    # Non-bullet content — treat as a single build item
                    builds.append({'what': line, 'details': ''})

        # Gotchas → friction
        friction = []
        if s.get('Gotchas'):
            for line in s['Gotchas'].splitlines():
                line = line.strip()
                if line.startswith('- '):
                    friction.append({'problem': line[2:].strip(), 'resolution': ''})
                elif line and not line.startswith('#'):
                    friction.append({'problem': line, 'resolution': ''})

        # Risks also feed into friction (different character — unresolved)
        if s.get('Risks'):
            for line in s['Risks'].splitlines():
                line = line.strip()
                if line.startswith('- '):
                    friction.append({'problem': f'[risk] {line[2:].strip()}',
                                     'resolution': ''})
                elif line and not line.startswith('#'):
                    friction.append({'problem': f'[risk] {line}', 'resolution': ''})

        # Reflection → learnings
        learnings = []
        if s.get('Reflection'):
            # Reflection is typically prose paragraphs, not bullets
            text = s['Reflection'].strip()
            if text:
                # Split on paragraph boundaries (double newline or bold markers)
                paragraphs = re.split(r'\n\n+', text)
                for para in paragraphs:
                    para = para.strip()
                    if para:
                        # Extract labelled parts: "**Claude observed:** ..." or "**User noted:** ..."
                        label_match = re.match(r'\*\*(.+?):\*\*\s*(.*)', para, re.DOTALL)
                        if label_match:
                            learnings.append({
                                'insight': label_match.group(2).strip(),
                                'why_it_matters': '',
                                'context': label_match.group(1).strip(),
                            })
                        else:
                            learnings.append({
                                'insight': para,
                                'why_it_matters': '',
                                'context': '',
                            })

        # Learned → patterns
        patterns = []
        if s.get('Learned'):
            text = s['Learned'].strip()
            if text:
                # Learned is typically one paragraph of architectural insight
                patterns.append(text)

        # Next → open_threads
        open_threads = []
        if s.get('Next'):
            for line in s['Next'].splitlines():
                line = line.strip()
                if line.startswith('- ') or line.startswith('○ '):
                    open_threads.append(line[2:].strip())
                elif line and not line.startswith('#') and not line.startswith('('):
                    open_threads.append(line)

        # Build arc from Done + summary
        arc = None
        if builds or summary:
            arc = {
                'started_with': summary or '',
                'key_turns': [b['what'] for b in builds[:5]],
                'ended_at': open_threads[0] if open_threads else '',
            }

        return {
            'summary': summary,
            'arc': arc,
            'builds': builds,
            'learnings': learnings,
            'friction': friction,
            'patterns': patterns,
            'open_threads': open_threads,
        }

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

        # Parse sections (handles both old flat h2 and new two-zone format)
        sections = _parse_sections(content)

        # Parse preamble for session_id and purpose
        preamble = _parse_preamble(content)

        return cls(
            path=path,
            project_name=project_name,
            project_path=project_path,
            date=date,
            mood=mood,
            sections=sections,
            purpose=preamble.get('purpose'),
            session_id=preamble.get('session_id'),
            mtime=path.stat().st_mtime,
        )


def discover_handoffs(config: dict) -> Iterator[HandoffSource]:
    """Discover all handoff files.

    Searches two locations:
    - ~/.claude/handoffs/ (legacy location, encoded parent dirs)
    - .bon/handoffs/ across all known repos (fond-v1 location)
    """
    source_config = config.get('sources', {}).get('handoffs', {})

    # Legacy location
    legacy_path = Path(source_config.get('path', '~/.claude/handoffs')).expanduser()
    pattern = source_config.get('pattern', '**/*.md')

    seen_stems: set[str] = set()

    if legacy_path.exists():
        for file in legacy_path.glob(pattern):
            try:
                source = HandoffSource.from_file(file)
                seen_stems.add(file.stem)
                yield source
            except Exception as e:
                print(f"Failed to parse {file}: {e}")

    # Bon handoffs: scan .bon/handoffs/ in configured repo roots
    bon_handoff_dirs = source_config.get('bon_handoff_dirs', [])
    if not bon_handoff_dirs:
        # Default: scan repos under ~/Repos/
        repos_root = Path('~/Repos').expanduser()
        if repos_root.exists():
            for repo in repos_root.rglob('.bon/handoffs'):
                if repo.is_dir():
                    bon_handoff_dirs.append(str(repo))

    for dir_path in bon_handoff_dirs:
        handoff_dir = Path(dir_path).expanduser()
        if not handoff_dir.exists():
            continue
        for file in handoff_dir.glob('*.md'):
            if file.stem in seen_stems:
                continue
            try:
                source = HandoffSource.from_file(file)
                seen_stems.add(file.stem)
                yield source
            except Exception as e:
                print(f"Failed to parse {file}: {e}")
