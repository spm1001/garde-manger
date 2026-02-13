"""Claude.ai conversation adapter.

Claude.ai conversations are synced via claude-data-sync to:
~/.claude/claude-ai/cache/conversations/{uuid}.json

Key features:
- Pre-generated summaries (avg 259 words) - no LLM call needed
- Platform UUID for stable identity
- Voice conversation detection via input_mode field
"""

from pathlib import Path
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Iterator


@dataclass
class ClaudeAISource:
    uuid: str
    name: str
    summary: str              # Pre-generated (avg 259 words)
    model: str
    created_at: datetime
    updated_at: datetime
    input_mode: str | None    # 'voice' or None
    messages: list
    platform: str = "CLAUDE_AI"

    @property
    def source_id(self) -> str:
        return f"claude_ai:{self.uuid}"

    @property
    def has_presummary(self) -> bool:
        return bool(self.summary)

    @classmethod
    def from_file(cls, path: Path) -> 'ClaudeAISource':
        data = json.loads(path.read_text())

        # Detect voice conversation from first human message
        input_mode = None
        for msg in data.get('chat_messages', []):
            if msg.get('sender') == 'human':
                input_mode = msg.get('input_mode')
                break

        return cls(
            uuid=data['uuid'],
            name=data.get('name', 'Untitled'),
            summary=data.get('summary', ''),
            model=data.get('model', 'unknown'),
            created_at=datetime.fromisoformat(data['created_at'].replace('Z', '+00:00')),
            updated_at=datetime.fromisoformat(data['updated_at'].replace('Z', '+00:00')),
            input_mode=input_mode,
            messages=data.get('chat_messages', []),
            platform=data.get('platform', 'CLAUDE_AI')
        )

    def full_text(self) -> str:
        """Extract all text content for entity extraction."""
        texts = []
        for msg in self.messages:
            # Message text may be in 'text' field or content blocks
            if msg.get('text'):
                texts.append(msg['text'])
            for block in msg.get('content', []):
                if isinstance(block, dict) and block.get('type') == 'text':
                    texts.append(block.get('text', ''))
        return '\n\n'.join(texts)


def discover_claude_ai(config: dict) -> Iterator[ClaudeAISource]:
    """Discover all Claude.ai conversation files."""
    source_config = config.get('sources', {}).get('claude_ai', {})
    path = Path(source_config.get('path', '~/.claude/claude-ai/cache/conversations')).expanduser()
    pattern = source_config.get('pattern', '*.json')

    if not path.exists():
        return

    for file in path.glob(pattern):
        try:
            yield ClaudeAISource.from_file(file)
        except Exception as e:
            print(f"Failed to parse {file}: {e}")
