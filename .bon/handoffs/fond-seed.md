# Handoff — 2026-04-04 (cross-repo seed)

session_id: seeded from ~/Repos session on Mac
purpose: Fond architecture — garde's extraction pipeline is being redesigned

## Now

### Gotchas
- This is a CROSS-REPO handoff seeded from a design session in batterie-de-savoir. Read the design brief first: ~/Repos/batterie/batterie-de-savoir/docs/fond-architecture.md
- The bon items live in batterie-de-savoir (bds-gorite). Action bds-kevapu is the garde-specific workstream.
- The staged extraction pipeline (/close writes JSON to /tmp, session-end hook ingests it) is being retired. Handoffs replace it as the extraction source.
- ccconv (the JSONL preprocessor in auto-handoff.sh) should be replaced by deglacer for the cold-transcript fallback path. Deglacer encodes hard-won knowledge about JSONL structure (compaction boundaries, subagent nesting, tool call parsing).
- Mac's garde DB is empty (0 sources, 0 extractions). Hezza has 661MB (8,555 sources, 7,222 extractions). The multi-machine problem is real but not this workstream's concern — Dolt migration (bon-forebi) handles that separately.

### Risks
- Handoff format is changing (bon repo, bds-fitipe). The garde adapter depends on the new two-zone format being stable. Don't build the adapter until the handoff template is finalised.
- Existing handoffs (hundreds across repos) use the old format. The adapter needs to handle both, or we accept that only new handoffs get the free extraction and old ones stay with their existing extractions.

### Next
- Wait for bds-fitipe (two-zone handoff template) to land in bon
- Then build handoff adapter: parse Done→builds, Gotchas→friction, Reflection→learnings, Learned→patterns
- Retire ingest-session's staged extraction path
- Replace ccconv with deglacer in the unclosed-session fallback
- The overnight composting process (bds-zowetu) will call garde's adapter — design the interface

### Commands
```bash
# Read the design brief
cat ~/Repos/batterie/batterie-de-savoir/docs/fond-architecture.md

# See the bon hierarchy
cd ~/Repos/batterie/batterie-de-savoir && bon show bds-gorite

# Current handoff adapter
grep -r "handoff" ~/Repos/batterie/garde-manger/src/ --include="*.py" -l

# Current staged extraction path
grep -r "staged\|pending.*extraction\|ingest.session" ~/Repos/batterie/garde-manger/src/ --include="*.py" -l

# Current garde understanding.md (has the full data model)
cat ~/Repos/batterie/garde-manger/.bon/understanding.md
```

## Compost

### Done
- Audited garde DB on both machines: Mac empty, hezza 8,555 sources / 7,222 extractions
- Compared handoff content with staged extraction for same session (b5c2a55f) — ~90% overlap, handoff is richer prose, extraction is structured JSON of the same information
- Identified that garde already indexes 1,580 handoffs as a source type, but treats them as simple text, not structured sections
- Identified ccconv as the predecessor to deglacer for JSONL preprocessing

### Reflection
Garde's extraction pipeline was designed when handoffs were thin session batons. Now that handoffs are rich, pre-structured artifacts written with full context, the extraction pipeline can be dramatically simplified: parse markdown sections instead of running an Opus call on cold JSONL. The staged extraction (written by /close to /tmp) becomes unnecessary because the handoff IS the extraction in prose form. For the ~15% of sessions that end without /close (auto-handoffs), deglacer's JSONL parsing is the fallback — but this is the minority path, not the default.

### Learned
Garde's primary consumer is future Claudes (86% of searches are Claude-initiated). The extraction quality matters more than the extraction mechanism. A handoff written by a Claude with full session context produces higher-quality summaries, learnings, and friction records than any cold-transcript extraction can. The architectural shift is: stop spending Opus tokens reconstructing what a session Claude already wrote in the handoff, and instead parse the handoff's pre-structured sections into garde's schema. The expensive LLM path (backfill via claude -p) becomes the fallback for sessions without handoffs, not the default for all sessions.
