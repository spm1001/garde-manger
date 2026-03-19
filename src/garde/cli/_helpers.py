"""Shared helper functions for CLI commands."""

import json
import re
from datetime import datetime, timezone


def _extract_compacted_summary(content: str) -> str | None:
    """
    Extract summary from Claude Code's episodic compaction.

    Compacted conversations have <summary>...</summary> tags containing
    the actual summary, buried in the compaction prompt.
    """
    match = re.search(r'<summary>\s*(.*?)\s*</summary>', content, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


def _is_compacted_conversation(first_message: str) -> bool:
    """Check if conversation starts with compaction prompt."""
    return first_message.startswith('Context: This summary will be shown')


def _create_basic_summary(source) -> str:
    """
    Create a basic summary from title and first messages.

    Uses presummary (type:summary entry) when available.
    Handles compacted conversations by extracting <summary> tags.
    """
    # Use presummary if available (from type:summary entry)
    if source.summary_text:
        return source.summary_text

    # Check for compacted conversation
    first_user_msg = None
    for msg in source.messages:
        if msg.role == 'user' and not msg.is_tool_result:
            content = msg.content
            if isinstance(content, str) and content.strip():
                first_user_msg = content.strip()
                break

    # If compacted, try to extract the real summary
    if first_user_msg and _is_compacted_conversation(first_user_msg):
        # Look for summary in any message
        for msg in source.messages:
            content = msg.content if isinstance(msg.content, str) else ''
            extracted = _extract_compacted_summary(content)
            if extracted:
                return extracted
        # Fallback: use embedded content after "User:" marker
        if 'User:' in first_user_msg:
            # Extract first embedded user message
            parts = first_user_msg.split('User:', 1)
            if len(parts) > 1:
                embedded = parts[1].split('Agent:', 1)[0].strip()
                if embedded and len(embedded) > 20:
                    return embedded[:500]

    # Normal conversation: use title + first messages
    parts = [source.title]

    user_messages = []
    for msg in source.messages:
        if msg.role == 'user' and not msg.is_tool_result:
            content = msg.content
            if isinstance(content, str) and content.strip():
                # Skip compaction prompts
                if not _is_compacted_conversation(content):
                    user_messages.append(content.strip())
            if len(user_messages) >= 3:
                break

    if user_messages:
        parts.append("\n\n".join(user_messages[:3]))

    return "\n\n".join(parts)


def _format_date(date_str: str) -> str:
    """Format date as relative (if recent) or absolute."""
    try:
        # Parse ISO format, handle various formats
        if 'T' in date_str:
            if '+' in date_str or date_str.endswith('Z'):
                dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            else:
                dt = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        diff = now - dt

        if diff.days == 0:
            hours = diff.seconds // 3600
            if hours == 0:
                mins = diff.seconds // 60
                return f"{mins}m ago" if mins > 0 else "just now"
            return f"{hours}h ago"
        elif diff.days == 1:
            return "yesterday"
        elif diff.days < 7:
            return f"{diff.days}d ago"
        elif diff.days < 30:
            weeks = diff.days // 7
            return f"{weeks}w ago"
        else:
            return dt.strftime("%b %d")
    except (ValueError, TypeError):
        return date_str[:10] if date_str else ""


def _auto_quote_hyphenated(query: str) -> str:
    """Auto-quote hyphenated terms to prevent FTS5 interpreting hyphens as MINUS.

    Leaves already-quoted terms alone.
    Example: 'claude-memory foo' -> '"claude-memory" foo'
    """
    # Find hyphenated terms that aren't already inside quotes
    result = []
    in_quotes = False
    i = 0

    while i < len(query):
        if query[i] == '"':
            # Toggle quote state and include the quote
            in_quotes = not in_quotes
            result.append(query[i])
            i += 1
        elif not in_quotes:
            # Look for hyphenated word
            match = re.match(r'\b(\w+(?:-\w+)+)\b', query[i:])
            if match:
                # Found hyphenated term outside quotes - wrap it
                result.append(f'"{match.group(1)}"')
                i += match.end()
            else:
                result.append(query[i])
                i += 1
        else:
            result.append(query[i])
            i += 1

    return ''.join(result)


def _expand_query(query: str, glossary) -> str:
    """Expand query terms using glossary aliases."""
    # Check if any glossary entity matches
    resolved = glossary.resolve(query)
    if resolved:
        entity = glossary.get(resolved)
        if entity:
            # Build OR query with canonical name and aliases
            terms = [entity.get('name', query)]
            terms.extend(entity.get('aliases', [])[:3])
            return ' OR '.join(f'"{t}"' for t in terms)
    return query


def _add_wildcard_suffix(query: str) -> str:
    """Add wildcard suffix to simple search terms for better recall.

    FTS5 requires exact token matches. Adding * makes 'Reckitt' match 'Reckitts'.
    Only applies to simple terms (no operators, no quotes, no existing wildcards).

    Examples:
        'Reckitt' -> 'Reckitt*'
        'OAuth' -> 'OAuth*'
        'Reckitt*' -> 'Reckitt*' (unchanged)
        '"OAuth refresh"' -> '"OAuth refresh"' (unchanged)
        'OAuth OR JWT' -> 'OAuth* OR JWT*'
        'OAuth NOT old' -> 'OAuth* NOT old*'
    """
    # FTS5 operators that should not be wildcarded
    operators = {'AND', 'OR', 'NOT', 'NEAR'}

    tokens = []
    # Split on whitespace while preserving quoted strings
    pattern = r'"[^"]*"|\S+'

    for match in re.finditer(pattern, query):
        token = match.group()

        # Skip if:
        # - Already quoted (phrase search)
        # - Already has wildcard
        # - Is an FTS5 operator
        # - Contains column prefix (e.g., title:foo)
        if (token.startswith('"') or
            token.endswith('*') or
            token.upper() in operators or
            ':' in token):
            tokens.append(token)
        else:
            # Add wildcard suffix
            tokens.append(token + '*')

    return ' '.join(tokens)


def _flatten_extraction_for_fts(extraction: dict) -> str:
    """Flatten extraction fields into searchable text.

    Combines summary + learnings + builds + friction into one searchable string.
    """
    parts = []

    # Summary
    if extraction.get('summary'):
        parts.append(extraction['summary'])

    # Learnings
    learnings = extraction.get('learnings') or []
    if isinstance(learnings, str):
        learnings = json.loads(learnings)
    for l in learnings:
        if isinstance(l, dict):
            if l.get('insight'):
                parts.append(f"Learning: {l['insight']}")
            if l.get('why_it_matters'):
                parts.append(l['why_it_matters'])
        else:
            parts.append(f"Learning: {l}")

    # Builds
    builds = extraction.get('builds') or []
    if isinstance(builds, str):
        builds = json.loads(builds)
    for b in builds:
        if isinstance(b, dict):
            if b.get('what'):
                parts.append(f"Built: {b['what']}")
            if b.get('outcome'):
                parts.append(b['outcome'])
        else:
            parts.append(f"Built: {b}")

    # Friction
    friction = extraction.get('friction') or []
    if isinstance(friction, str):
        friction = json.loads(friction)
    for f in friction:
        if isinstance(f, dict):
            if f.get('problem'):
                parts.append(f"Friction: {f['problem']}")
        else:
            parts.append(f"Friction: {f}")

    return "\n".join(parts)
