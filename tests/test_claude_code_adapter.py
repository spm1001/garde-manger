"""Tests for Claude Code adapter.

Tests title extraction, metadata extraction, and summary handling.
"""
import json
import pytest
from pathlib import Path
from datetime import datetime

from src.garde.adapters.claude_code import ClaudeCodeSource, _get_quick_summary, clean_title


@pytest.fixture
def tmp_jsonl(tmp_path):
    """Helper to create temp JSONL files for testing."""
    def _create(lines: list[dict]) -> Path:
        path = tmp_path / "test.jsonl"
        with path.open('w') as f:
            for line in lines:
                f.write(json.dumps(line) + '\n')
        return path
    return _create


# When a session has a type:summary entry, it should use that as title
def test_title_from_summary_entry(tmp_jsonl):
    path = tmp_jsonl([
        {"type": "summary", "summary": "Implemented OAuth for workspace MCP"},
        {"type": "user", "timestamp": "2025-01-01T00:00:00Z", "sessionId": "abc123",
         "message": {"role": "user", "content": "Some user message"}}
    ])

    src = ClaudeCodeSource.from_file(path)
    assert src.title == "Implemented OAuth for workspace MCP"
    assert src.has_presummary is True
    assert src.summary_text == "Implemented OAuth for workspace MCP"


# When a session has no summary entry, it should use first non-meta user message
def test_title_from_first_user_message(tmp_jsonl):
    path = tmp_jsonl([
        {"type": "user", "timestamp": "2025-01-01T00:00:00Z", "sessionId": "abc123",
         "message": {"role": "user", "content": "Help me fix this bug"}}
    ])

    src = ClaudeCodeSource.from_file(path)
    assert src.title == "Help me fix this bug"
    assert src.has_presummary is False


# When first user message is isMeta, it should be skipped for title
def test_title_skips_ismeta_messages(tmp_jsonl):
    path = tmp_jsonl([
        {"type": "user", "timestamp": "2025-01-01T00:00:00Z", "sessionId": "abc123",
         "isMeta": True,
         "message": {"role": "user", "content": "Meta context injection"}},
        {"type": "user", "timestamp": "2025-01-01T00:01:00Z",
         "message": {"role": "user", "content": "Real user question"}}
    ])

    src = ClaudeCodeSource.from_file(path)
    assert src.title == "Real user question"


# When a compacted conversation has <summary> tags, it should extract that
def test_title_from_summary_tags_in_compaction(tmp_jsonl):
    compaction_content = (
        "Context: This summary will be shown in a list...\n"
        "User: What was done?\n"
        "Agent: I helped with OAuth.\n"
        "<summary>Implemented JWT refresh tokens for workspace MCP</summary>"
    )
    path = tmp_jsonl([
        {"type": "user", "timestamp": "2025-01-01T00:00:00Z", "sessionId": "abc123",
         "message": {"role": "user", "content": compaction_content}}
    ])

    src = ClaudeCodeSource.from_file(path)
    assert "JWT refresh tokens" in src.title
    assert not src.title.startswith("Context:")


# When a compacted conversation has no summary tags, extract from User: marker
def test_title_from_user_marker_in_compaction(tmp_jsonl):
    compaction_content = (
        "Context: This summary will be shown in a list...\n"
        "User: Help me debug the authentication flow\n"
        "Agent: Sure, let me check the code."
    )
    path = tmp_jsonl([
        {"type": "user", "timestamp": "2025-01-01T00:00:00Z", "sessionId": "abc123",
         "message": {"role": "user", "content": compaction_content}}
    ])

    src = ClaudeCodeSource.from_file(path)
    assert "debug the authentication" in src.title


# When tool_use blocks are present, they should be captured in metadata
def test_metadata_captures_tool_calls(tmp_jsonl):
    path = tmp_jsonl([
        {"type": "user", "timestamp": "2025-01-01T00:00:00Z", "sessionId": "abc123",
         "message": {"role": "user", "content": "Read the config file"}},
        {"type": "assistant", "timestamp": "2025-01-01T00:00:01Z",
         "message": {"role": "assistant", "content": [
             {"type": "tool_use", "name": "Read", "input": {"file_path": "/etc/config.yaml"}},
             {"type": "tool_use", "name": "Bash", "input": {"command": "cat /etc/hosts"}}
         ]}}
    ])

    src = ClaudeCodeSource.from_file(path)
    assert src.metadata["tool_count"] == 2
    assert len(src.metadata["tool_calls"]) == 2
    assert src.metadata["tool_calls"][0]["name"] == "Read"
    assert src.metadata["tool_calls"][1]["name"] == "Bash"


# When file-related tools are used, files_touched should capture the paths
def test_metadata_captures_files_touched(tmp_jsonl):
    path = tmp_jsonl([
        {"type": "user", "timestamp": "2025-01-01T00:00:00Z", "sessionId": "abc123",
         "message": {"role": "user", "content": "Edit the files"}},
        {"type": "assistant", "timestamp": "2025-01-01T00:00:01Z",
         "message": {"role": "assistant", "content": [
             {"type": "tool_use", "name": "Read", "input": {"file_path": "/src/main.py"}},
             {"type": "tool_use", "name": "Write", "input": {"file_path": "/src/config.py", "content": "x=1"}}
         ]}}
    ])

    src = ClaudeCodeSource.from_file(path)
    assert "/src/main.py" in src.metadata["files_touched"]
    assert "/src/config.py" in src.metadata["files_touched"]


# When Skill tool is used, skills_used should capture skill names
def test_metadata_captures_skills_used(tmp_jsonl):
    path = tmp_jsonl([
        {"type": "user", "timestamp": "2025-01-01T00:00:00Z", "sessionId": "abc123",
         "message": {"role": "user", "content": "Close the session"}},
        {"type": "assistant", "timestamp": "2025-01-01T00:00:01Z",
         "message": {"role": "assistant", "content": [
             {"type": "tool_use", "name": "Skill", "input": {"skill": "close"}}
         ]}}
    ])

    src = ClaudeCodeSource.from_file(path)
    assert "close" in src.metadata["skills_used"]


# When content is in array format (standard Claude format), it should be parsed
def test_content_array_format(tmp_jsonl):
    path = tmp_jsonl([
        {"type": "user", "timestamp": "2025-01-01T00:00:00Z", "sessionId": "abc123",
         "message": {"role": "user", "content": [
             {"type": "text", "text": "First part"},
             {"type": "text", "text": "Second part"}
         ]}}
    ])

    src = ClaudeCodeSource.from_file(path)
    assert "First part" in src.title


# Quick summary helper should detect warmup sessions
def test_quick_summary_detects_warmup(tmp_jsonl):
    path = tmp_jsonl([
        {"type": "user", "timestamp": "2025-01-01T00:00:00Z",
         "message": {"role": "user", "content": "Warmup"}}
    ])

    summary = _get_quick_summary(path)
    assert summary == "Warmup"


# Quick summary should return explicit summary entry if present
def test_quick_summary_uses_summary_entry(tmp_jsonl):
    path = tmp_jsonl([
        {"type": "summary", "summary": "Database migration session"},
        {"type": "user", "timestamp": "2025-01-01T00:00:00Z",
         "message": {"role": "user", "content": "Something else"}}
    ])

    summary = _get_quick_summary(path)
    assert summary == "Database migration session"


# clean_title should strip command XML tags from titles
def test_clean_title_strips_command_tags():
    # Single tag
    assert clean_title("<command-message>open</command-message>") == ""
    
    # Tag with surrounding text
    assert clean_title("Hello <command-name>/open</command-name> world") == "Hello world"
    
    # Multiple tags
    dirty = "<command-message>open</command-message>\n<command-name>/open</command-name># Session"
    assert clean_title(dirty) == "# Session"
    
    # No tags - should pass through
    assert clean_title("Normal title text") == "Normal title text"

    # Collapse whitespace
    assert clean_title("Title   with   spaces") == "Title with spaces"


# messages_with_offsets returns MessageData for semantic chunking
def test_messages_with_offsets(tmp_jsonl):
    path = tmp_jsonl([
        {"type": "user", "timestamp": "2025-01-01T10:00:00Z", "sessionId": "abc123",
         "message": {"role": "user", "content": "First user message"}},  # 18 chars
        {"type": "assistant", "timestamp": "2025-01-01T10:01:00Z",
         "message": {"role": "assistant", "content": "Assistant response here"}},  # 23 chars
        {"type": "user", "timestamp": "2025-01-01T10:02:00Z",
         "message": {"role": "user", "content": "Second user message"}},  # 19 chars
    ])

    src = ClaudeCodeSource.from_file(path)
    messages = src.messages_with_offsets()

    assert len(messages) == 3

    # First message
    assert messages[0].role == 'user'
    assert messages[0].char_offset == 0
    assert messages[0].char_length == 18

    # Second message (offset = first length + separator '\n\n')
    assert messages[1].role == 'assistant'
    assert messages[1].char_offset == 20  # 18 + 2
    assert messages[1].char_length == 23

    # Third message
    assert messages[2].role == 'user'
    assert messages[2].char_offset == 45  # 20 + 23 + 2
    assert messages[2].char_length == 19


# messages_with_offsets tracks tool_use in messages
def test_messages_with_offsets_tool_use(tmp_jsonl):
    path = tmp_jsonl([
        {"type": "assistant", "timestamp": "2025-01-01T10:00:00Z", "sessionId": "abc123",
         "message": {"role": "assistant", "content": [
             {"type": "text", "text": "Let me read that file"},
             {"type": "tool_use", "name": "Read", "input": {"file_path": "/foo"}}
         ]}},
    ])

    src = ClaudeCodeSource.from_file(path)
    messages = src.messages_with_offsets()

    assert len(messages) == 1
    assert messages[0].has_tool_use is True
