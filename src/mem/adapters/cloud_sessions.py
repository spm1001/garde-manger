"""Cloud sessions adapter for Claude Code web sessions.

Cloud sessions are synced via claude-data-sync to:
~/.claude/claude-ai/cache/sessions/{session_id}.json

Format is similar to local Claude Code JSONL but:
- JSON file with loglines[] array (not JSONL)
- Session IDs prefixed session_01*
- Includes git context: cwd, gitBranch
- May include thinking blocks
"""

from pathlib import Path
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterator

# Reuse patterns and helpers from claude_code adapter
from .claude_code import clean_title
COMMIT_PATTERN = re.compile(r"\[[\w\-/]+ ([a-f0-9]{7,})\] (.+?)(?:\n|$)")


@dataclass
class CloudSessionSource:
    """Cloud Claude Code session from JSON file."""
    path: Path
    session_id: str           # From filename: session_01*
    title: str                # Extracted from first user message or summary
    created_at: datetime
    updated_at: datetime
    cwd: str | None = None    # Working directory (git context)
    git_branch: str | None = None  # Git branch
    messages: list = field(default_factory=list)
    summary_text: str | None = None
    metadata: dict = field(default_factory=dict)

    @property
    def source_id(self) -> str:
        return f"cloud_session:{self.session_id}"

    @property
    def has_presummary(self) -> bool:
        return self.summary_text is not None

    @classmethod
    def from_file(cls, path: Path) -> 'CloudSessionSource':
        """Parse a cloud session JSON file."""
        with path.open() as f:
            data = json.load(f)

        loglines = data.get('loglines', [])
        session_id = path.stem  # session_01ABC...

        # Extract metadata
        cwd = None
        git_branch = None
        summary_text = None
        first_user_content = None
        timestamps = []
        messages = []

        # Tool usage metadata
        tool_calls = []
        files_touched = set()
        skills_used = set()
        subagents_spawned = []
        git_commits = []

        for entry in loglines:
            entry_type = entry.get('type')

            # Extract git context from first entry
            if cwd is None:
                cwd = entry.get('cwd')
                git_branch = entry.get('gitBranch')

            # Check for summary entry
            if entry_type == 'summary' and entry.get('summary'):
                summary_text = entry['summary']
                continue

            ts_str = entry.get('timestamp')
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                    timestamps.append(ts)
                except ValueError:
                    pass

            # Skip non-message entries
            if entry_type not in ('user', 'assistant'):
                continue

            msg_data = entry.get('message', {})
            role = msg_data.get('role', entry_type)
            content = msg_data.get('content', '')

            # Handle content array format
            if isinstance(content, list):
                text_parts = []
                for block in content:
                    if not isinstance(block, dict):
                        continue

                    block_type = block.get('type')

                    if block_type == 'text':
                        text_parts.append(block.get('text', ''))

                    elif block_type == 'thinking':
                        # Cloud sessions may have thinking blocks
                        pass  # Skip for now, could extract later

                    elif block_type == 'tool_use':
                        tool_name = block.get('name', '')
                        tool_input = block.get('input', {})

                        input_summary = None
                        if tool_name == 'Bash':
                            cmd = tool_input.get('command', '')
                            input_summary = cmd[:100] if cmd else None
                        elif tool_name in ('Read', 'Write', 'Edit', 'Glob'):
                            fp = tool_input.get('file_path', '')
                            if fp:
                                files_touched.add(fp)
                                input_summary = fp
                        elif tool_name == 'Skill':
                            skill = tool_input.get('skill', '')
                            if skill:
                                skills_used.add(skill)
                                input_summary = skill
                        elif tool_name == 'Task':
                            st = tool_input.get('subagent_type', '')
                            prompt = tool_input.get('prompt', '')[:50]
                            subagents_spawned.append({
                                'subagent_type': st,
                                'prompt_preview': prompt
                            })
                            input_summary = st

                        tool_calls.append({
                            'name': tool_name,
                            'ts': ts_str,
                            'input_summary': input_summary
                        })

                    elif block_type == 'tool_result':
                        result_content = block.get('content', '')
                        if isinstance(result_content, str):
                            for match in COMMIT_PATTERN.finditer(result_content):
                                git_commits.append({
                                    'hash': match.group(1),
                                    'message': match.group(2)
                                })

                content = '\n'.join(text_parts) if text_parts else str(content)

            # Capture first non-meta user message for title
            if first_user_content is None and role == 'user':
                if entry.get('isMeta'):
                    continue
                if isinstance(content, str) and content:
                    if not content.startswith('Context: This summary will be shown'):
                        first_user_content = content

            messages.append({
                'uuid': entry.get('uuid', ''),
                'role': role,
                'content': content,
                'timestamp': ts_str,
            })

        # Generate title
        title = path.stem
        title_source = first_user_content

        if summary_text:
            title_source = summary_text
        elif not first_user_content:
            # Try to extract from compaction prompt
            for msg in messages:
                if msg.get('role') == 'user':
                    content = msg.get('content', '')
                    if isinstance(content, str) and content.startswith('Context: This summary will be shown'):
                        if '<summary>' in content and '</summary>' in content:
                            start = content.rfind('<summary>') + 9
                            end = content.rfind('</summary>')
                            if start < end:
                                extracted = content[start:end].strip()
                                if extracted and len(extracted) > 10:
                                    title_source = extracted
                                    break
                        if 'User:' in content:
                            parts = content.split('User:', 1)
                            if len(parts) > 1:
                                embedded = parts[1].split('Agent:', 1)[0].strip()
                                if embedded and len(embedded) > 10:
                                    title_source = embedded
                                    break
                    break

        if title_source:
            # Clean internal markup before using as title
            title_source = clean_title(title_source)
            title = title_source[:80]
            if len(title_source) > 80:
                if ' ' in title[60:]:
                    title = title[:60 + title[60:].index(' ')] + '...'
                else:
                    title = title + '...'

        metadata = {
            'tool_calls': tool_calls,
            'files_touched': sorted(files_touched),
            'skills_used': sorted(skills_used),
            'subagents_spawned': subagents_spawned,
            'git_commits': git_commits,
            'tool_count': len(tool_calls),
            'cwd': cwd,
            'git_branch': git_branch,
        }

        return cls(
            path=path,
            session_id=session_id,
            title=title,
            created_at=min(timestamps) if timestamps else datetime.now(),
            updated_at=max(timestamps) if timestamps else datetime.now(),
            cwd=cwd,
            git_branch=git_branch,
            messages=messages,
            summary_text=summary_text,
            metadata=metadata,
        )

    def full_text(self) -> str:
        """Extract text content for indexing."""
        texts = []
        for msg in self.messages:
            content = msg.get('content', '')
            if isinstance(content, str) and content:
                texts.append(content)
        return '\n\n'.join(texts)


def _get_quick_summary(path: Path) -> str | None:
    """Quick scan for summary without full parse."""
    try:
        with path.open() as f:
            data = json.load(f)
        loglines = data.get('loglines', [])

        for entry in loglines:
            if entry.get('type') == 'summary' and entry.get('summary'):
                return entry['summary']

            if entry.get('type') == 'user' and not entry.get('isMeta'):
                msg = entry.get('message', {})
                content = msg.get('content', '')
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get('type') == 'text':
                            return block.get('text', '')[:100]
                elif isinstance(content, str):
                    return content[:100]
    except Exception as e:
        import sys
        print(f"Warning: Failed to parse {path.name}: {e}", file=sys.stderr)
    return None


def discover_cloud_sessions(config: dict) -> Iterator[CloudSessionSource]:
    """Discover cloud Claude Code sessions."""
    source_config = config.get('sources', {}).get('cloud_sessions', {})
    base_path = Path(source_config.get('path', '~/.claude/claude-ai/cache/sessions')).expanduser()

    if not base_path.exists():
        return

    for json_file in base_path.glob('session_*.json'):
        # Skip warmup/empty sessions
        quick_summary = _get_quick_summary(json_file)
        if quick_summary is None or quick_summary.lower() == 'warmup':
            continue

        try:
            yield CloudSessionSource.from_file(json_file)
        except Exception as e:
            print(f"Failed to parse {json_file}: {e}")
