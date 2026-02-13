"""LLM client for entity extraction and hybrid summarization.

Uses claude -p (Claude Code CLI pipe mode) for all LLM calls,
billing against Max subscription rather than API credits.
"""

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Any

# Single model for all extractions — Opus 4.6 via Max subscription
MODEL = "claude-opus-4-6"


@dataclass
class MessageData:
    """Message metadata for semantic chunking.

    Captures structural information needed to detect topic boundaries:
    - Timestamp for detecting time gaps
    - Role to identify user returns after assistant runs
    - Character offsets for mapping back to full_text positions
    - Tool markers for identifying tool sequence boundaries
    """
    timestamp: datetime
    role: str  # 'user' or 'assistant'
    char_offset: int  # Position in full_text string
    char_length: int
    is_tool_result: bool = False
    has_tool_use: bool = False


def _call_claude(prompt: str, timeout: int = 120) -> str:
    """Send prompt to Claude CLI and return text response.

    Uses claude -p (pipe mode) which bills against Max subscription.
    All tools are disabled to ensure pure text generation.

    Raises RuntimeError if claude CLI is not available, fails, or times out.
    """
    if not shutil.which("claude"):
        raise RuntimeError(
            "claude CLI not found on PATH. "
            "Install Claude Code: https://docs.anthropic.com/en/docs/claude-code"
        )

    # Prevent fork bombs: signal to session-start hooks that this is a
    # programmatic subagent, not an interactive session.
    env = {**os.environ, "GARDE_SUBAGENT": "1"}

    try:
        result = subprocess.run(
            [
                "claude", "-p",
                "--output-format", "json",
                "--model", MODEL,
                "--allowedTools", "",
                "--no-session-persistence",
            ],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"claude CLI timed out after {timeout}s")

    if result.returncode != 0:
        raise RuntimeError(
            f"claude CLI failed (exit {result.returncode}): "
            f"{result.stderr[:500]}"
        )

    try:
        output = json.loads(result.stdout)
        return output["result"]
    except (json.JSONDecodeError, KeyError) as e:
        raise RuntimeError(f"Failed to parse claude CLI output: {e}")


EXTRACTION_PROMPT = """You are extracting named entities from a conversation or document.

<known_entities>
{glossary_sample}
</known_entities>

<content>
{content}
</content>

Extract entities in these categories:
- People: Named individuals (not roles like "the manager")
- Products: Named tools, systems, products
- Projects: Named initiatives, projects
- Organizations: Companies, teams, departments
- Concepts: Technical terms, methodologies (only if domain-specific)

For each entity, provide:
1. The exact mention text
2. Your confidence (high/medium/low)
3. Suggested canonical name (may match known entity)
4. Why you think this is an entity

{voice_note}

Output JSON:
{{
  "entities": [
    {{
      "mention": "GeoX",
      "confidence": "high",
      "suggested_canonical": "Region:Lift",
      "reasoning": "Appears to be alternative name for Region:Lift based on context"
    }}
  ]
}}

Be conservative. Better to miss an entity than hallucinate one."""


def format_glossary_sample(glossary: dict, max_entities: int = 20) -> str:
    """Format a sample of glossary entities for the prompt.

    Prioritizes entities with aliases (more useful for matching)
    and includes category structure.
    """
    lines = []
    count = 0

    # Flatten glossary categories
    for category, entities in glossary.items():
        if not isinstance(entities, dict):
            continue
        for name, details in entities.items():
            if count >= max_entities:
                break

            # Format: "Name (Category): description [aliases: a, b, c]"
            line = f"- {name} ({category})"
            if isinstance(details, dict):
                if details.get("description"):
                    line += f": {details['description']}"
                if details.get("aliases"):
                    aliases = ", ".join(details["aliases"])
                    line += f" [aliases: {aliases}]"
            lines.append(line)
            count += 1

        if count >= max_entities:
            break

    if not lines:
        return "(No known entities yet)"

    return "\n".join(lines)


def build_extraction_prompt(
    content: str,
    glossary: dict,
    is_voice: bool = False,
    max_content_chars: int = 50000
) -> str:
    """Build the entity extraction prompt."""
    sample = format_glossary_sample(glossary, max_entities=20)

    voice_note = ""
    if is_voice:
        voice_note = """Note: This is a voice-transcribed conversation. Expect transcription
errors (homophones, mishearings). Focus on entities that are clearly intentional
references despite any transcription artifacts."""

    # Truncate content if too long
    truncated = content[:max_content_chars]
    if len(content) > max_content_chars:
        truncated += f"\n\n[... truncated, {len(content) - max_content_chars} chars omitted ...]"

    return EXTRACTION_PROMPT.format(
        glossary_sample=sample,
        content=truncated,
        voice_note=voice_note
    )


def extract_entities(
    content: str,
    glossary: dict,
    is_voice: bool = False,
) -> list[dict[str, Any]]:
    """Extract entities from content using LLM.

    Returns list of entity dicts with keys:
        - mention: str (exact text found)
        - confidence: str (high/medium/low)
        - suggested_canonical: str | None
        - reasoning: str

    Raises RuntimeError if claude CLI not available or fails.
    """
    prompt = build_extraction_prompt(content, glossary, is_voice)
    response_text = _call_claude(prompt)

    # Try to find JSON in response (may have preamble)
    try:
        # Look for JSON object
        start = response_text.find("{")
        end = response_text.rfind("}") + 1
        if start >= 0 and end > start:
            json_str = response_text[start:end]
            result = json.loads(json_str)
            return result.get("entities", [])
    except json.JSONDecodeError:
        pass

    # If parsing fails, return empty (conservative)
    return []


def confidence_to_float(confidence: str) -> float:
    """Convert confidence string to float for storage."""
    return {
        "high": 0.9,
        "medium": 0.6,
        "low": 0.3
    }.get(confidence.lower(), 0.5)


# Topic boundary detection patterns
TOPIC_MARKER_PATTERNS = [
    r'(?i)let\'s move on',
    r'(?i)new topic:',
    r'(?i)moving on to',
    r'(?i)switching to',
    r'^---+$',  # Horizontal rule
    r'(?i)^#+\s',  # Markdown headers
]

import re
TOPIC_MARKERS = [re.compile(p, re.MULTILINE) for p in TOPIC_MARKER_PATTERNS]


def detect_topic_boundaries(
    messages: list[MessageData],
    content: str,
    timestamp_gap_seconds: int = 300,
) -> list[int]:
    """Detect topic boundaries in a conversation.

    Uses weighted signals to identify where topics change:
    - Timestamp gap >5min: weight 1.0 (strong signal)
    - User message after 3+ assistant messages: weight 0.5 (new question)
    - Tool sequence boundary (assistant without tools after tools): weight 0.3
    - Explicit markers ("let's move on", "---", headers): weight 0.2

    Args:
        messages: List of MessageData with timestamps and roles
        content: Full text content (for marker detection)
        timestamp_gap_seconds: Threshold for time gap signal (default 300 = 5min)

    Returns:
        List of message indices where boundaries occur (boundary is BEFORE that message)
    """
    if len(messages) < 2:
        return []

    boundaries = []

    # Track consecutive assistant messages for "user return" detection
    consecutive_assistant = 0
    # Track whether previous assistant used tools
    prev_assistant_had_tools = False

    for i in range(1, len(messages)):
        msg = messages[i]
        prev = messages[i - 1]

        boundary_score = 0.0

        # Signal 1: Timestamp gap > threshold
        if msg.timestamp and prev.timestamp:
            gap = (msg.timestamp - prev.timestamp).total_seconds()
            if gap > timestamp_gap_seconds:
                boundary_score += 1.0

        # Signal 2: User message after 3+ consecutive assistant messages
        if msg.role == 'user' and consecutive_assistant >= 3:
            boundary_score += 0.5

        # Signal 3: Tool sequence boundary
        # (assistant without tools following assistant with tools)
        if msg.role == 'assistant' and prev.role == 'assistant':
            if prev_assistant_had_tools and not msg.has_tool_use:
                boundary_score += 0.3

        # Signal 4: Explicit markers in message content
        msg_content = content[msg.char_offset:msg.char_offset + msg.char_length]
        for pattern in TOPIC_MARKERS:
            if pattern.search(msg_content):
                boundary_score += 0.2
                break  # Only count once per message

        # Update tracking state
        if msg.role == 'assistant':
            consecutive_assistant += 1
            prev_assistant_had_tools = msg.has_tool_use
        else:
            consecutive_assistant = 0
            prev_assistant_had_tools = False

        # Threshold: score >= 0.5 marks boundary
        if boundary_score >= 0.5:
            boundaries.append(i)

    return boundaries


# Default semantic chunk sizes
DEFAULT_SEMANTIC_MIN = 15_000     # Merge smaller chunks with neighbors
DEFAULT_SEMANTIC_MAX = 80_000     # Split larger chunks at paragraph breaks
DEFAULT_SEMANTIC_TARGET = 40_000  # Preferred single-topic chunk size


def _split_at_paragraphs(content: str, target: int, max_size: int) -> list[str]:
    """Split content at paragraph breaks, targeting chunks near target size.

    Args:
        content: Text to split
        target: Target chunk size (split near this point)
        max_size: Maximum chunk size (hard limit)

    Returns:
        List of content chunks
    """
    if len(content) <= max_size:
        return [content]

    chunks = []
    remaining = content

    while len(remaining) > max_size:
        # Find paragraph break nearest to target
        search_start = max(0, target - 5000)
        search_end = min(len(remaining), target + 5000)

        # Look for \n\n in the search window
        best_break = -1
        search_region = remaining[search_start:search_end]

        # Find break closest to target
        pos = 0
        while True:
            idx = search_region.find('\n\n', pos)
            if idx == -1:
                break
            actual_pos = search_start + idx
            if best_break == -1 or abs(actual_pos - target) < abs(best_break - target):
                best_break = actual_pos
            pos = idx + 1

        if best_break == -1:
            # No paragraph break found - split at max_size
            best_break = max_size

        chunks.append(remaining[:best_break])
        remaining = remaining[best_break:].lstrip('\n')

    if remaining:
        chunks.append(remaining)

    return chunks


def split_semantic(
    content: str,
    messages: list[MessageData],
    min_size: int = DEFAULT_SEMANTIC_MIN,
    max_size: int = DEFAULT_SEMANTIC_MAX,
    target_size: int = DEFAULT_SEMANTIC_TARGET,
) -> list[str]:
    """Split content into semantic chunks based on topic boundaries.

    Algorithm:
    1. Detect topic boundaries using message structure
    2. Split content at boundary points
    3. Merge chunks smaller than min_size with neighbors
    4. Split chunks larger than max_size at paragraph breaks

    Args:
        content: Full conversation text
        messages: List of MessageData for boundary detection
        min_size: Minimum chunk size (merge smaller)
        max_size: Maximum chunk size (split larger)
        target_size: Target size for splitting large chunks

    Returns:
        List of content chunks
    """
    # Edge case: no messages or single chunk fits
    if not messages:
        return _split_at_paragraphs(content, target_size, max_size)

    if len(content) <= max_size:
        # Check if any boundaries exist
        boundaries = detect_topic_boundaries(messages, content)
        if not boundaries:
            return [content]

    # Step 1: Detect boundaries
    boundaries = detect_topic_boundaries(messages, content)

    if not boundaries:
        # No topic boundaries - treat as one coherent thread
        return _split_at_paragraphs(content, target_size, max_size)

    # Step 2: Split at boundary points (using message char_offset)
    segments = []
    prev_offset = 0

    for boundary_idx in boundaries:
        msg = messages[boundary_idx]
        # Split just before this message
        segment = content[prev_offset:msg.char_offset].rstrip()
        if segment:
            segments.append(segment)
        prev_offset = msg.char_offset

    # Add final segment
    final = content[prev_offset:].rstrip()
    if final:
        segments.append(final)

    # Step 3: Merge small chunks with neighbors
    merged = []
    current = ""

    for segment in segments:
        if not current:
            current = segment
        elif len(current) + len(segment) + 2 < min_size:
            # Merge with current
            current = current + "\n\n" + segment
        else:
            # Current is big enough, start new
            if current:
                merged.append(current)
            current = segment

    if current:
        merged.append(current)

    # Check if we only have one merged chunk that's still small
    if len(merged) == 1 and len(merged[0]) < min_size:
        # That's fine - small sessions stay as one chunk
        pass
    # Re-merge if final chunk is too small
    elif len(merged) > 1 and len(merged[-1]) < min_size:
        last = merged.pop()
        merged[-1] = merged[-1] + "\n\n" + last

    # Step 4: Split large chunks at paragraph breaks
    final_chunks = []
    for chunk in merged:
        if len(chunk) > max_size:
            final_chunks.extend(_split_at_paragraphs(chunk, target_size, max_size))
        else:
            final_chunks.append(chunk)

    return final_chunks


# Default chunk size for large sessions (chars, not tokens)
# These can be overridden via config.yaml processing.chunk_size/chunk_overlap
DEFAULT_CHUNK_SIZE = 140_000
DEFAULT_CHUNK_OVERLAP = 5_000

# Hybrid extraction prompt - validated against 5 benchmark questions
HYBRID_EXTRACTION_PROMPT = """Extract a structured digest from this conversation.

<content>
{content}
</content>

Output JSON with these fields:

1. **summary**: 2-3 sentences — what happened and why it matters

2. **arc**: the journey
   - started_with: initial goal/problem
   - key_turns: array of pivots, discoveries, changes in direction
   - ended_at: final state

3. **builds**: array of things created or modified
   - what: the thing
   - details: context

4. **learnings**: array of insights discovered
   - insight: what was learned
   - why_it_matters: significance (not just "it's useful" — be specific)
   - context: how discovered

5. **friction**: array of problems encountered
   - problem: what was hard
   - resolution: how resolved (or "unresolved")

6. **patterns**: array of recurring themes, collaboration style, meta-observations

7. **open_threads**: array of unfinished business, deferred work

Focus on OUTCOMES and STORY, not just entities mentioned.
Return ONLY valid JSON, no markdown code blocks."""


# Chunk extraction prompt - for partial conversations
CHUNK_EXTRACTION_PROMPT = """Extract key outcomes from this PARTIAL conversation (chunk {chunk_num} of {total_chunks}).

<content>
{content}
</content>

Output JSON with:
- builds: array of things created/modified (what, details)
- learnings: array of insights (insight, why_it_matters, context)
- friction: array of problems (problem, resolution)
- breakthroughs: array of key "aha" moments with why_it_matters

Return ONLY valid JSON, no markdown code blocks."""


# Merge prompt - combines chunk results into coherent summary
MERGE_PROMPT = """You have extraction results from {num_chunks} chunks of the same conversation.
Merge and deduplicate into a single coherent summary.

<chunk_results>
{chunk_results}
</chunk_results>

Create a MERGED summary with:
1. summary: 2-3 sentences about the whole conversation
2. arc: the journey (started_with, key_turns array, ended_at)
3. builds: deduplicated list of things created/modified
4. learnings: deduplicated insights with why_it_matters
5. friction: deduplicated problems encountered
6. patterns: recurring themes, collaboration style, meta-observations
7. open_threads: unfinished business, deferred work

Deduplicate by meaning, not just exact text. Combine related items.
Return ONLY valid JSON, no markdown code blocks."""


def _split_with_overlap(content: str, chunk_size: int, overlap: int) -> list[str]:
    """Split content into overlapping chunks.

    Tries to split at paragraph boundaries when possible.
    """
    if len(content) <= chunk_size:
        return [content]

    chunks = []
    start = 0

    while start < len(content):
        end = start + chunk_size

        # If not at the end, try to find a paragraph break
        if end < len(content):
            # Look for paragraph break in last 10% of chunk
            search_start = end - (chunk_size // 10)
            para_break = content.rfind('\n\n', search_start, end)
            if para_break > search_start:
                end = para_break + 2  # Include the newlines

        chunks.append(content[start:end])

        # Next chunk starts with overlap
        start = end - overlap
        if start >= len(content):
            break

    return chunks


def _extract_chunk(
    content: str,
    chunk_num: int,
    total_chunks: int,
) -> dict[str, Any]:
    """Extract from a single chunk."""
    prompt = CHUNK_EXTRACTION_PROMPT.format(
        chunk_num=chunk_num,
        total_chunks=total_chunks,
        content=content,
    )

    response_text = _call_claude(prompt)

    try:
        start = response_text.find("{")
        end = response_text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(response_text[start:end])
    except json.JSONDecodeError:
        pass

    return {"builds": [], "learnings": [], "friction": [], "breakthroughs": []}


def _merge_chunk_results(
    chunk_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Merge multiple chunk extractions into one coherent result."""
    # Format chunk results for the merge prompt
    formatted = json.dumps(chunk_results, indent=2)

    prompt = MERGE_PROMPT.format(
        num_chunks=len(chunk_results),
        chunk_results=formatted,
    )

    response_text = _call_claude(prompt)

    try:
        start = response_text.find("{")
        end = response_text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(response_text[start:end])
    except json.JSONDecodeError:
        pass

    # Return empty structure if parsing fails
    return {
        "summary": None,
        "arc": None,
        "builds": [],
        "learnings": [],
        "friction": [],
        "patterns": [],
        "open_threads": [],
    }


def extract_hybrid(
    content: str,
    messages: list[MessageData] | None = None,
    max_content_chars: int = 80000,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    semantic_min: int | None = None,
    semantic_max: int | None = None,
    semantic_target: int | None = None,
) -> dict[str, Any]:
    """Extract structured digest from conversation using hybrid prompt.

    For content exceeding max_content_chars, uses chunking:
    1. If messages provided: semantic chunking at topic boundaries
    2. Otherwise: fixed-size overlapping chunks (backward compat)
    3. Extract from each chunk
    4. Merge results with deduplication

    Args:
        content: Full conversation text
        messages: Optional list of MessageData for semantic chunking
        max_content_chars: Threshold for triggering chunking
        chunk_size: Override default chunk size (for fixed-size chunking)
        chunk_overlap: Override default overlap (for fixed-size chunking)
        semantic_min: Min chunk size for semantic chunking (default 15K)
        semantic_max: Max chunk size for semantic chunking (default 80K)
        semantic_target: Target chunk size for semantic chunking (default 40K)

    Returns dict with keys:
        - summary: str
        - arc: dict with started_with, key_turns, ended_at
        - builds: list of {what, details}
        - learnings: list of {insight, why_it_matters, context}
        - friction: list of {problem, resolution}
        - patterns: list of str
        - open_threads: list of str

    Raises RuntimeError if claude CLI not available or fails.
    """

    # Semantic chunking settings
    actual_semantic_min = semantic_min or DEFAULT_SEMANTIC_MIN
    actual_semantic_max = semantic_max or DEFAULT_SEMANTIC_MAX
    actual_semantic_target = semantic_target or DEFAULT_SEMANTIC_TARGET

    # Fixed-size chunking settings (fallback)
    actual_chunk_size = chunk_size or DEFAULT_CHUNK_SIZE
    actual_chunk_overlap = chunk_overlap or DEFAULT_CHUNK_OVERLAP

    # Use chunking for large content
    if len(content) > max_content_chars:
        # Choose chunking strategy based on whether messages are provided
        if messages:
            # Semantic chunking: split at topic boundaries
            chunks = split_semantic(
                content,
                messages,
                min_size=actual_semantic_min,
                max_size=actual_semantic_max,
                target_size=actual_semantic_target,
            )
        else:
            # Fixed-size chunking: backward compatible fallback
            chunks = _split_with_overlap(content, actual_chunk_size, actual_chunk_overlap)

        # Extract from each chunk
        chunk_results = []
        for i, chunk in enumerate(chunks):
            result = _extract_chunk(chunk, i + 1, len(chunks))
            chunk_results.append(result)

        # Merge chunk results
        return _merge_chunk_results(chunk_results)

    # Single extraction for content that fits
    prompt = HYBRID_EXTRACTION_PROMPT.format(content=content)
    response_text = _call_claude(prompt)

    # Parse JSON from response
    try:
        # Look for JSON object
        start = response_text.find("{")
        end = response_text.rfind("}") + 1
        if start >= 0 and end > start:
            json_str = response_text[start:end]
            result = json.loads(json_str)
            return result
    except json.JSONDecodeError:
        pass

    # Return empty structure if parsing fails
    return {
        "summary": None,
        "arc": None,
        "builds": [],
        "learnings": [],
        "friction": [],
        "patterns": [],
        "open_threads": [],
    }
