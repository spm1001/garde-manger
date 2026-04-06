"""Claude Code conversation adapter.

Claude Code stores conversations as JSONL files in:
~/.claude/projects/{project-path}/*.jsonl

Conversation text extraction uses deglacer (shared library) for
compaction-aware parsing, deduplication, and system tag stripping.
Metadata extraction (tool calls, files, skills, commits) is local
since deglacer doesn't cover it.
"""

from pathlib import Path
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterator

import deglacer as dg

# Pattern to match git commit output: [branch hash] message
COMMIT_PATTERN = re.compile(r"\[[\w\-/]+ ([a-f0-9]{7,})\] (.+?)(?:\n|$)")

# Pattern to strip internal XML command tags from titles
COMMAND_TAG_PATTERN = re.compile(r'<command-\w+>.*?</command-\w+>', re.DOTALL)


def clean_title(text: str) -> str:
    """Strip internal markup from title text."""
    # Remove <command-*>...</command-*> tags
    cleaned = COMMAND_TAG_PATTERN.sub('', text)
    # Collapse whitespace
    cleaned = ' '.join(cleaned.split())
    return cleaned.strip()


@dataclass
class ClaudeCodeSource:
    """Claude Code conversation from JSONL file."""
    path: Path
    session_id: str           # From first message's sessionId
    agent_id: str | None      # Non-null for subagent conversations
    title: str                # Extracted from summary entry or first user message
    created_at: datetime
    updated_at: datetime
    project_path: str = ""    # e.g., "-Users-jane-Repos-foo"
    summary_text: str | None = None  # From type:summary entry if present
    metadata: dict = field(default_factory=dict)  # Tool usage metadata
    _entries: list[dict] = field(default_factory=list, repr=False)  # Raw JSONL entries for deglacer

    @property
    def source_id(self) -> str:
        if self.agent_id:
            return f"claude_code:{self.agent_id}"
        return f"claude_code:{self.session_id}"

    @property
    def has_presummary(self) -> bool:
        return self.summary_text is not None

    @property
    def is_subagent(self) -> bool:
        return self.agent_id is not None

    @classmethod
    def from_file(cls, path: Path) -> 'ClaudeCodeSource':
        session_id = None
        agent_id = None
        project_path = ""
        summary_text = None  # From type:summary entry
        first_user_content = None
        timestamps = []

        # Metadata extraction
        tool_calls = []  # [{name, ts, input_summary}]
        files_touched = set()  # Deduplicated file paths
        skills_used = set()  # Skill names
        subagents_spawned = []  # [{subagent_type, prompt_preview}]
        git_commits = []  # [{hash, message}]

        # Parse project path from file location
        if 'projects' in path.parts:
            idx = path.parts.index('projects')
            if idx + 1 < len(path.parts) - 1:
                project_path = path.parts[idx + 1]

        # Use deglacer for robust JSONL parsing (handles encoding errors)
        entries = dg.parse_session(str(path))

        for entry in entries:
            entry_type = entry.get('type')

            # Check for explicit summary entry (Claude Code creates these)
            if entry_type == 'summary' and entry.get('summary'):
                summary_text = entry['summary']
                continue

            # Extract session metadata from first message entry
            if session_id is None and entry_type in ('user', 'assistant'):
                session_id = entry.get('sessionId')
                agent_id = entry.get('agentId')

            ts_str = entry.get('timestamp')
            if ts_str:
                ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                timestamps.append(ts)

            # Skip non-message entries for metadata/message extraction
            if entry_type not in ('user', 'assistant'):
                continue

            msg_ts = None
            if ts_str:
                msg_ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))

            msg_data = entry.get('message', {})
            role = msg_data.get('role', entry_type)

            # Extract metadata from content blocks (tool calls, files, skills, commits)
            content = msg_data.get('content', '')
            if isinstance(content, list):
                text_parts = []
                for block in content:
                    if not isinstance(block, dict):
                        continue

                    block_type = block.get('type')

                    if block_type == 'text':
                        text_parts.append(block.get('text', ''))

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

                content = '\n'.join(text_parts) if text_parts else content

            # Capture first non-meta user message for title fallback
            if first_user_content is None and role == 'user':
                if not entry.get('isMeta'):
                    if isinstance(content, str) and content:
                        if not content.startswith('Context: This summary will be shown'):
                            first_user_content = content

        # Generate title: prefer summary, fall back to first user message
        title = path.stem
        title_source = first_user_content

        if summary_text:
            # Use the explicit summary as title
            title_source = summary_text
        elif not first_user_content:
            # No summary and no non-compacted user message
            # Try to extract from compaction prompt (first user entry)
            for e in entries:
                if e.get('type') == 'user' and e.get('message', {}).get('role') == 'user':
                    raw = e.get('message', {}).get('content', '')
                    if not isinstance(raw, str):
                        continue
                    if raw.startswith('Context: This summary will be shown'):
                        if '<summary>' in raw and '</summary>' in raw:
                            start = raw.rfind('<summary>') + 9
                            end = raw.rfind('</summary>')
                            if start < end:
                                extracted = raw[start:end].strip()
                                if extracted and len(extracted) > 10:
                                    title_source = extracted
                                    break
                        if 'User:' in raw:
                            parts = raw.split('User:', 1)
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

        # Build metadata dict
        metadata = {
            'tool_calls': tool_calls,
            'files_touched': sorted(files_touched),
            'skills_used': sorted(skills_used),
            'subagents_spawned': subagents_spawned,
            'git_commits': git_commits,
            'tool_count': len(tool_calls),
        }

        # For subagent sessions, store parent session ID for navigation
        if agent_id and session_id:
            metadata['parent_session_id'] = session_id

        return cls(
            path=path,
            session_id=session_id or path.stem,
            agent_id=agent_id,
            title=title,
            created_at=min(timestamps) if timestamps else datetime.now(),
            updated_at=max(timestamps) if timestamps else datetime.now(),
            project_path=project_path,
            summary_text=summary_text,
            metadata=metadata,
            _entries=entries,
        )

    def _build_turns(self) -> list[dict]:
        """Build conversation turns via deglacer (cached)."""
        if not hasattr(self, '_turns_cache'):
            self._turns_cache = dg.build_turns(self._entries)
        return self._turns_cache

    def full_text(self) -> str:
        """Extract text content via deglacer.

        Handles compaction boundaries, deduplicates streaming entries,
        strips system tags, and preserves compaction summaries.
        """
        return dg.format_text(self._build_turns())

    def messages_with_offsets(self) -> list:
        """Return message metadata with character offsets into full_text.

        Used for semantic chunking - provides the structural information
        needed to detect topic boundaries (timestamps, role changes, tool use).
        Offsets map into the deglacer-formatted text from full_text().

        Returns:
            List of MessageData objects with char_offset/char_length mapping
            to positions in the string returned by full_text().
        """
        from ..llm import MessageData

        turns = self._build_turns()
        full = self.full_text()

        # Build a set of timestamps where tool_use occurred (from original entries)
        tool_use_timestamps = set()
        for entry in self._entries:
            if entry.get('type') == 'assistant':
                ts = entry.get('timestamp')
                for block in entry.get('message', {}).get('content', []):
                    if isinstance(block, dict) and block.get('type') == 'tool_use':
                        tool_use_timestamps.add(ts)
                        break

        result = []
        current_offset = 0

        for turn in turns:
            role = turn['role']
            text = turn['text']
            ts_raw = turn.get('timestamp')

            if role == 'system':
                # Compaction summary — find it in the formatted output
                idx = full.find(text, current_offset)
                if idx >= 0:
                    result.append(MessageData(
                        timestamp=None,
                        role='user',
                        char_offset=idx,
                        char_length=len(text),
                        is_tool_result=False,
                        has_tool_use=False,
                    ))
                    current_offset = idx + len(text)
                continue

            ts = None
            if ts_raw:
                if isinstance(ts_raw, str):
                    ts = datetime.fromisoformat(ts_raw.replace('Z', '+00:00'))
                else:
                    ts = ts_raw

            # Find the role header in formatted output
            header = f'── {role.upper()} ──'
            idx = full.find(header, current_offset)
            if idx < 0:
                continue

            content_start = idx + len(header) + 1
            content_len = len(text)

            result.append(MessageData(
                timestamp=ts,
                role='user' if role == 'human' else role,
                char_offset=content_start,
                char_length=content_len,
                is_tool_result=False,
                has_tool_use=ts_raw in tool_use_timestamps,
            ))
            current_offset = content_start + content_len

        return result

def _get_quick_summary(path: Path) -> str | None:
    """Quick scan for summary entry without full parse.

    Returns the summary text if found, or first user message snippet,
    or None if file is empty/warmup.
    """
    with path.open() as f:
        for line in f:
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Found explicit summary
            if entry.get('type') == 'summary' and entry.get('summary'):
                return entry['summary']

            # Found first user message
            if entry.get('type') == 'user' and not entry.get('isMeta'):
                msg = entry.get('message', {})
                content = msg.get('content', '')
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get('type') == 'text':
                            return block.get('text', '')[:100]
                elif isinstance(content, str):
                    return content[:100]
    return None


def discover_claude_code(config: dict) -> Iterator[ClaudeCodeSource]:
    """
    Discover Claude Code conversations.

    Args:
        config: Configuration dict
    """
    source_config = config.get('sources', {}).get('claude_code', {})
    base_path = Path(source_config.get('path', '~/.claude/projects')).expanduser()
    min_lines = source_config.get('min_lines', 10)
    include_subagents = source_config.get('include_subagents', True)

    if not base_path.exists():
        return

    for project_dir in base_path.glob('*'):
        if not project_dir.is_dir():
            continue

        for jsonl_file in project_dir.glob('**/*.jsonl'):
            is_agent = jsonl_file.name.startswith('agent-') or 'subagents' in jsonl_file.parts

            # Skip agents if not included
            if is_agent and not include_subagents:
                continue

            # Quick line count check for agents
            if is_agent:
                with jsonl_file.open() as f:
                    line_count = sum(1 for _ in f)
                if line_count < min_lines:
                    continue

            # Skip warmup/empty sessions
            quick_summary = _get_quick_summary(jsonl_file)
            if quick_summary is None or quick_summary.lower() == 'warmup':
                continue

            try:
                yield ClaudeCodeSource.from_file(jsonl_file)
            except Exception as e:
                print(f"Failed to parse {jsonl_file}: {e}")
