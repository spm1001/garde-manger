# Hybrid Extraction Prompt

Combines structured outcomes (from Variant B) with narrative arc and "why it matters" (from Variant C).

## Prompt

```
Extract a structured digest from this conversation.

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
Return ONLY valid JSON, no markdown code blocks.
```

## Design Rationale

### Why Hybrid?

Tested three variants on 10+ sessions:

| Variant | Strength | Weakness |
|---------|----------|----------|
| A (entities only) | Conservative | Can't answer outcome questions |
| B (entities + outcomes) | Structured, aggregation-friendly | Misses "why it matters" |
| C (narrative digest) | Captures story and significance | Harder to aggregate |

Hybrid combines B's structured fields with C's narrative elements. One prompt that answers all benchmark questions.

### Key Fields

**learnings.why_it_matters** — This is the critical differentiator. Without it, learnings are just facts. With it, we can identify TIL blog post candidates, significant discoveries, and patterns worth remembering.

**arc** — Captures the journey, not just the destination. Useful for understanding how work evolved, what caused pivots.

**patterns** — Meta-observations about collaboration style, tool usage, recurring themes. Powers ritual improvement questions.

## Chunking for Large Sessions

Sessions >150k chars (~75k tokens) exceed Sonnet's context limit. Use chunking:

1. Split into chunks of ~140k chars with 5k overlap
2. Extract from each chunk with "chunk N of M" context in prompt
3. Merge results with deduplication

### Chunk Extraction Prompt

```
Extract key outcomes from this PARTIAL conversation (chunk {n} of {total}).

<content>
{chunk_content}
</content>

Output JSON with:
- builds: things created/modified
- learnings: insights discovered (include why_it_matters)
- friction: problems encountered
- breakthroughs: key "aha" moments

Return ONLY valid JSON.
```

### Merge Prompt

```
You have extraction results from {n} chunks of the same conversation.
Merge and deduplicate into a single coherent summary.

{chunk_results}

Create a MERGED summary with:
- summary: 2-3 sentences about the whole conversation
- builds: deduplicated list
- learnings: deduplicated insights
- breakthroughs: most significant discoveries with why_it_matters
- arc: started_with, key_turns, ended_at

Return ONLY valid JSON.
```

## Evaluation Results

Tested against 5 benchmark questions:

| Question | Answerable? | Key Fields |
|----------|-------------|------------|
| Q1: /open /close ritual improvement | Yes | patterns, friction |
| Q2: Big builds and learnings | Yes | builds, learnings |
| Q3: TIL blog post candidates | Yes | learnings.why_it_matters |
| Q4: Claude.ai vs Code differences | Needs testing | patterns (cross-session) |
| Q5: Skill usage patterns | Needs testing | patterns + metadata |

## Usage

```python
from anthropic import Anthropic

client = Anthropic()

def extract_hybrid(content: str) -> dict:
    prompt = HYBRID_PROMPT.format(content=content)
    response = client.messages.create(
        model="claude-sonnet-4-20250514",  # or claude-3-5-haiku for cost
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}]
    )
    return json.loads(response.content[0].text)
```

## Next Steps

- [ ] Haiku downgrade test — verify quality with cheaper model
- [x] Implement chunking in pipeline (done: llm.py now splits large sessions)
- [ ] Aggregate across full corpus
- [ ] Verify Q4 and Q5 benchmark questions
