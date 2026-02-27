# Memory Workflows

Common patterns for searching and retrieving context from memory.

---

## Workflow 1: Reorientation Search

**When:** User asks about past work, or you need historical context.

```
Step 1: Search
   ↓
Step 2: Triage extraction summaries
   ↓
Step 3: Drill if needed
   ↓
Step 4: Synthesize findings
```

### Example

User: "What did we decide about extraction models?"

```bash
# Step 1: Search
uv run garde search "extraction model haiku sonnet"

# Step 2: Triage - read extraction summary
uv run garde drill claude_code:36108eba...

# Step 3: Drill if needed (specific turn with key discussion)
uv run garde drill claude_code:36108eba --turn 12

# Step 4: Synthesize
```

> "Based on session 36108eba from Dec 15, we compared Haiku vs Sonnet for extraction. Key finding: Haiku loses 40% of learnings depth. Decision: Use Sonnet despite 10x cost—absolute cost still low (~$0.01-0.10/session)."

---

## Workflow 2: Mid-Session Reorientation

**When:** Context is muddy, you've drifted, or user says "I'm lost" / "where were we?"

```bash
# 1. Search for current topic
uv run garde search "topic we're working on"

# 2. Check what past sessions learned
uv run garde drill <relevant_id>

# 3. Check current bon state
bon ready
bon show <current_item>
```

**Then synthesize:**
> "Based on past sessions, we learned X. Current item Y says Z. Does this change our approach?"

---

## Workflow 3: Current Project Context

**When:** Starting work on a project with likely history.

```bash
# Check recent activity for this project
uv run garde recent

# If sparse, check all sources
uv run garde recent --all --days 14

# Search for specific topic within project
uv run garde search "topic" --project .
```

### What to Look For

- **Builds:** What was created that we might extend
- **Learnings:** Gotchas we already discovered
- **Open threads:** Work that was left unfinished
- **Patterns:** Approaches that worked well

---

## Workflow 4: Before Making Decisions

**When:** About to make a decision that might contradict past work.

```bash
# Search for prior discussion
uv run garde search "decision topic"

# Check if there's a handoff with relevant context
uv run garde search "topic" --type handoff
```

### Decision Validation Pattern

1. Search for prior discussion of the topic
2. Read extraction summaries for "Learnings" and "Patterns"
3. Check if current approach aligns or contradicts
4. If contradicting, explain why (things may have changed)

---

## Workflow 5: Cross-Reference with Bon

**When:** Memory search finds context, need to connect to current work.

```bash
# Search memory
uv run garde search "authentication"

# Check current bon state
bon ready
bon show <relevant_item>

# Cross-reference: Does the bon item know about what memory found?
```

### Pattern

Memory provides historical context; bon provides current work state. Cross-referencing catches:
- Items that duplicate past solved problems
- Work that contradicts prior decisions
- Context that should be in item notes but isn't

---

## Workflow 6: Debugging "No Results"

**When:** Search returns nothing but you know content exists.

```bash
# Step 1: Check database status
uv run garde status

# Step 2: If coverage is low, scan
uv run garde scan

# Step 3: Check if FTS needs sync
uv run garde sync-fts

# Step 4: Try different query terms
uv run garde search "alternative terms"

# Step 5: Try without type filter
uv run garde search "query" --type claude_code
```

### Common Causes

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| Zero results, known content | Not indexed | `garde scan` |
| Zero results, recent session | Extraction not in FTS | `garde sync-fts` |
| Results but missing expected | Source type filtered out | Remove `--type` |
| Hyphen breaks search | FTS operator interpretation | Already auto-quoted |

---

## Workflow 7: Handoff Archaeology

**When:** Need context from older sessions, handoffs are the best source.

```bash
# List recent handoffs
uv run garde recent --type handoff

# Search handoffs specifically
uv run garde search "topic" --type handoff

# Drill into handoff (extractions are compact summaries)
uv run garde drill handoff:...
```

### Why Handoffs

Handoffs are designed for continuity—they capture Done, Learned, Next explicitly. When drilling into handoffs:
- **Done:** What was accomplished
- **Gotchas:** Problems encountered
- **Next:** What was planned but not done

---

## Workflow 8: Full Pipeline Refresh

**When:** Setting up fresh, or significant time has passed.

```bash
# Index all sources
uv run garde scan

# Run extraction on sources without it
uv run garde backfill

# Update FTS with extraction content
uv run garde sync-fts

# Verify
uv run garde status
```

### Timing

- `scan`: Fast (~seconds)
- `backfill`: Slow (~minutes, API calls)
- `sync-fts`: Fast (~seconds)

---

## Anti-Patterns

### Drilling Without Triaging

**Bad:** Jump straight to `--full` on every result
**Good:** Read extraction summary first; drill only if needed

### Searching After Context Loaded

**Bad:** Search for topic when handoff already has the answer
**Good:** Check handoff/bon first; search if gaps remain

### Ignoring Source Types

**Bad:** Generic search returns 50 noisy results
**Good:** Filter by type: `--type handoff` for curated context

### Not Cross-Referencing

**Bad:** Find historical context, don't connect to current work
**Good:** Cross-reference with `bon ready` and current item notes
