"""Tests for Claude Code adapter.

Tests title extraction, metadata extraction, and summary handling.
"""
import json
import pytest
from pathlib import Path
from datetime import datetime

from src.garde.adapters.claude_code import ClaudeCodeSource, _get_quick_summary, clean_title, discover_claude_code


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


# --- Subagent tests ---

def _make_session_lines(session_id, agent_id=None, content="Hello"):
    """Helper to create minimal valid JSONL lines."""
    entry = {
        "type": "user",
        "timestamp": "2025-06-01T12:00:00Z",
        "sessionId": session_id,
        "message": {"role": "user", "content": content},
    }
    if agent_id:
        entry["agentId"] = agent_id
    return [entry]


# source_id should use agent_id when present (not session_id)
def test_source_id_uses_agent_id_for_subagents(tmp_jsonl):
    path = tmp_jsonl(_make_session_lines("parent-123", agent_id="agent-456"))
    src = ClaudeCodeSource.from_file(path)
    assert src.source_id == "claude_code:agent-456"
    assert src.is_subagent is True


# source_id should use session_id when agent_id is absent (regression guard)
def test_source_id_uses_session_id_for_main_sessions(tmp_jsonl):
    path = tmp_jsonl(_make_session_lines("session-789"))
    src = ClaudeCodeSource.from_file(path)
    assert src.source_id == "claude_code:session-789"
    assert src.is_subagent is False


# parent_session_id should appear in metadata for agent sessions
def test_parent_session_id_in_metadata_for_agents(tmp_jsonl):
    path = tmp_jsonl(_make_session_lines("parent-abc", agent_id="agent-def"))
    src = ClaudeCodeSource.from_file(path)
    assert src.metadata["parent_session_id"] == "parent-abc"


# parent_session_id should NOT appear for main sessions
def test_no_parent_session_id_for_main_sessions(tmp_jsonl):
    path = tmp_jsonl(_make_session_lines("session-xyz"))
    src = ClaudeCodeSource.from_file(path)
    assert "parent_session_id" not in src.metadata


# --- Discovery tests ---

@pytest.fixture
def projects_tree(tmp_path):
    """Create a realistic projects directory with main + subagent sessions."""
    base = tmp_path / "projects"
    project = base / "-home-user-Repos-foo"
    project.mkdir(parents=True)

    # Main session
    main_file = project / "abc-def-123.jsonl"
    lines = _make_session_lines("abc-def-123", content="Main session work")
    with main_file.open("w") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")

    # Subagent in subagents/ directory
    subagents_dir = project / "abc-def-123" / "subagents"
    subagents_dir.mkdir(parents=True)
    agent_file = subagents_dir / "agent-ghi-789.jsonl"
    # Agents need enough lines to pass min_lines filter
    agent_lines = _make_session_lines("abc-def-123", agent_id="agent-ghi-789", content="Agent work")
    # Pad with extra messages to pass min_lines=10
    for i in range(15):
        agent_lines.append({
            "type": "assistant",
            "timestamp": f"2025-06-01T12:0{i % 10}:00Z",
            "sessionId": "abc-def-123",
            "agentId": "agent-ghi-789",
            "message": {"role": "assistant", "content": f"Response {i}"},
        })
    with agent_file.open("w") as f:
        for line in agent_lines:
            f.write(json.dumps(line) + "\n")

    # Short agent (should be filtered by min_lines)
    short_agent = subagents_dir / "agent-short.jsonl"
    with short_agent.open("w") as f:
        f.write(json.dumps({"type": "user", "timestamp": "2025-06-01T12:00:00Z",
                            "sessionId": "abc-def-123", "agentId": "agent-short",
                            "message": {"role": "user", "content": "Brief"}}) + "\n")

    return base


# discover should find files in subagents/ directories
def test_discover_finds_subagent_files(projects_tree):
    config = {"sources": {"claude_code": {"path": str(projects_tree), "min_lines": 10}}}
    sources = list(discover_claude_code(config))
    ids = {s.source_id for s in sources}
    assert "claude_code:agent-ghi-789" in ids
    assert "claude_code:abc-def-123" in ids


# discover should respect include_subagents=False
def test_discover_excludes_subagents_when_disabled(projects_tree):
    config = {"sources": {"claude_code": {
        "path": str(projects_tree), "min_lines": 10, "include_subagents": False,
    }}}
    sources = list(discover_claude_code(config))
    ids = {s.source_id for s in sources}
    assert "claude_code:agent-ghi-789" not in ids
    assert "claude_code:abc-def-123" in ids


# discover should filter short agents by min_lines
def test_discover_filters_short_agents(projects_tree):
    config = {"sources": {"claude_code": {"path": str(projects_tree), "min_lines": 10}}}
    sources = list(discover_claude_code(config))
    ids = {s.source_id for s in sources}
    assert "claude_code:agent-short" not in ids


# is_subagent should be True for files in subagents/ dir (even without agent- prefix)
def test_is_subagent_from_subagents_directory(projects_tree):
    config = {"sources": {"claude_code": {"path": str(projects_tree), "min_lines": 1}}}
    sources = list(discover_claude_code(config))
    agent_sources = [s for s in sources if s.is_subagent]
    assert len(agent_sources) >= 1
