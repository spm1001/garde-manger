"""Amp thread adapter.

Amp stores conversations as individual JSON files at:
~/.local/share/amp/threads/T-{uuid}.json

Key features:
- Structured JSON with messages array (same content block types as Anthropic API)
- Thread titles, agent modes, activated skills
- Project context from env.initial.trees
- No pre-generated summaries — needs LLM extraction
"""

from pathlib import Path
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterator


@dataclass
class AmpSource:
    thread_id: str
    title: str
    path: Path
    created_at: datetime
    updated_at: datetime
    messages: list
    agent_mode: str = "smart"
    project_path: str | None = None
    activated_skills: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @property
    def source_id(self) -> str:
        return f"amp:{self.thread_id}"

    @property
    def has_presummary(self) -> bool:
        return False

    @classmethod
    def from_file(cls, path: Path) -> 'AmpSource':
        data = json.loads(path.read_text())

        thread_id = data['id']
        created_ms = data.get('created', 0)
        created_at = datetime.fromtimestamp(created_ms / 1000, tz=timezone.utc)

        # updated_at: use the last assistant message timestamp, or fall back to created
        updated_at = created_at
        for msg in reversed(data.get('messages', [])):
            if msg.get('role') == 'assistant':
                usage = msg.get('usage', {})
                ts = usage.get('timestamp')
                if ts:
                    updated_at = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                    break

        # Project path from env.initial.trees
        project_path = None
        trees = data.get('env', {}).get('initial', {}).get('trees', [])
        if trees:
            uri = trees[0].get('uri', '')
            if uri.startswith('file://'):
                project_path = uri[7:]  # strip file://

        # Activated skills
        skills = [s.get('name', '') for s in data.get('activatedSkills', [])]

        # Metadata for enrichment
        metadata = {}
        if data.get('agentMode'):
            metadata['agent_mode'] = data['agentMode']
        if skills:
            metadata['skills'] = skills
        if trees:
            metadata['trees'] = [t.get('displayName', '') for t in trees]

        # Handoff chain links (parent/child relationships between threads)
        relationships = data.get('relationships', [])
        if relationships:
            metadata['relationships'] = [
                {
                    'thread_id': r['threadID'],
                    'type': r.get('type', 'handoff'),
                    'role': r.get('role', 'unknown'),
                }
                for r in relationships
            ]

        return cls(
            thread_id=thread_id,
            title=data.get('title', 'Untitled'),
            path=path,
            created_at=created_at,
            updated_at=updated_at,
            messages=data.get('messages', []),
            agent_mode=data.get('agentMode', 'smart'),
            project_path=project_path,
            activated_skills=skills,
            metadata=metadata,
        )

    def full_text(self) -> str:
        """Extract human-readable text from the conversation.

        Includes user and assistant text blocks. Skips thinking blocks
        (internal reasoning), tool_use (JSON payloads), and tool_result
        (often large/noisy). This matches what a human would read.
        """
        parts = []
        for msg in self.messages:
            role = msg.get('role', '')
            if role not in ('user', 'assistant'):
                continue

            for block in msg.get('content', []):
                if isinstance(block, dict) and block.get('type') == 'text':
                    text = block.get('text', '').strip()
                    if text:
                        prefix = 'Human' if role == 'user' else 'Assistant'
                        parts.append(f"{prefix}: {text}")
                elif isinstance(block, str):
                    # Some user messages have bare string content
                    if block.strip():
                        parts.append(f"Human: {block.strip()}")

        return '\n\n'.join(parts)


def discover_amp(config: dict) -> Iterator[AmpSource]:
    """Discover all Amp thread files."""
    source_config = config.get('sources', {}).get('amp', {})
    path = Path(source_config.get('path', '~/.local/share/amp/threads')).expanduser()
    pattern = source_config.get('pattern', 'T-*.json')

    if not path.exists():
        return

    for file in sorted(path.glob(pattern)):
        # Skip write-ahead temp files
        if file.name.endswith('.amptmp'):
            continue
        try:
            yield AmpSource.from_file(file)
        except Exception as e:
            print(f"Failed to parse {file.name}: {e}")
