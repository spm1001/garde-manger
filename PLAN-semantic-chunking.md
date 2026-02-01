# Semantic Chunking & Remaining OpenClaw Adoption

## Context

Session a95361e implemented:
- ✅ Vector spike (FTS5 wins, skip vector search)
- ✅ Basic chunking (140K fixed size — needs improvement)
- ✅ Knowledge source adapter

## Priority 1: Semantic Chunking (Replaces Fixed-Size)

Current implementation splits at ~140K chars with 5K overlap. This is naive — splits mid-thought.

**Better approach:** Split at topic boundaries, variable chunk sizes.

### Detection Signals
- Explicit markers: "Let's move on to...", "New topic:", "---"
- Timestamp gaps (>5 min between messages)
- Speaker pattern shifts (user asks new question after long assistant response)
- Tool usage boundaries (end of one tool sequence, start of another)

### Implementation Sketch
```python
def split_semantic(content: str, messages: list) -> list[str]:
    """Split at topic boundaries, not fixed sizes."""
    boundaries = detect_topic_shifts(messages)
    chunks = []
    for start, end in pairwise(boundaries):
        chunk = extract_chunk(content, start, end)
        # Merge tiny chunks (<10K) with neighbors
        # Split huge chunks (>80K) at paragraph breaks
        chunks.append(chunk)
    return chunks
```

### Questions to Resolve
- What's the minimum useful chunk size? (10K? 20K?)
- What's the maximum before quality degrades? (50K? 80K?)
- How to handle sessions that are one long coherent thread?

## Priority 2: Typed Learnings

Tag extractions with OpenClaw's type system:

| Type | Meaning | Example |
|------|---------|---------|
| W | World fact | "FTS5 has two delete syntaxes" |
| B | Biographical | "We fixed the trigger mismatch" |
| O(c=0.9) | Opinion with confidence | "Progressive disclosure works better" |
| S | Summary | Generated observations |

Enables: `mem search --type opinion` or filtering TIL candidates.

### Implementation
Add `learning_type` field to extractions schema. Update hybrid prompt to output typed learnings.

## Priority 3: Entity Pages (Research)

Auto-generate `~/.claude/memory/entities/<name>.md` from aggregated mentions.

OpenClaw's design:
- One file per entity
- Updated by scheduled "reflect" job
- Tracks opinion confidence over time
- Human-reviewable and editable

This is sophisticated — park for later unless entity queries become frequent.

## Files to Modify

| File | Change |
|------|--------|
| `src/mem/llm.py` | Replace `_split_with_overlap` with `_split_semantic` |
| `src/mem/adapters/claude_code.py` | Expose message boundaries for semantic splitting |
| `prompts/hybrid.md` | Document semantic chunking approach |
| `src/mem/database.py` | Add `learning_type` column (Priority 2) |

## Test Cases

1. Long meandering session with 3+ topic shifts → should produce 3+ chunks
2. Short focused session (<50K) → single extraction, no chunking
3. Session with one huge tangent → tangent as separate chunk
