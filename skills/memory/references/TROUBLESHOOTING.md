# Memory Troubleshooting

Known issues and fixes for common problems.

---

## Search Issues

### "No results" for content that should exist

**Symptoms:** Search returns nothing, but you know the content is in a session.

**Diagnosis:**
```bash
# Check database status
uv run garde status
```

**Causes and fixes:**

| If status shows... | Cause | Fix |
|-------------------|-------|-----|
| Low source count | Not scanned | `uv run garde scan` |
| Low extraction % | Backfill incomplete | `uv run garde backfill` |
| Good coverage | FTS not synced | `uv run garde sync-fts` |

### Search not finding recent sessions

**Cause:** New sessions aren't auto-indexed.

**Fix:**
```bash
uv run garde scan
uv run garde sync-fts  # If extraction exists but not searchable
```

### Hyphenated terms return weird results

**Cause:** FTS5 interprets hyphens as operators.

**Fix:** The CLI auto-quotes hyphenated terms now. If still failing:
```bash
uv run garde search '"claude-mem"'  # Explicit quotes
```

### Glossary aliases not expanding

**Cause:** Aliases only expand from `name` and `aliases` fields in glossary.yaml.

**Fix:** Check `~/.claude/memory/glossary.yaml` — add missing aliases:
```yaml
entities:
  - name: "CS&P"
    aliases: ["CSP", "CS and P", "CS & P"]
```

---

## Drill Issues

### "Source not found"

**Cause:** Source ID doesn't exist in database.

**Fix:** Verify the ID with:
```bash
uv run garde list --limit 20
```

### Extraction is thin/missing

**Cause:** Source wasn't backfilled, or content was too short.

**Symptoms:** Drill shows minimal arc/learnings.

**Fix:**
```bash
# Force re-extraction (if implemented)
uv run garde backfill --source-type claude_code --force
```

**Note:** Sessions under 100 characters are skipped as "warmups."

---

## Recent Issues

### Project detection not working

**Cause:** Not in a git repo, or repo not matching expected path format.

**Symptoms:** `garde recent` shows all sources instead of current project.

**Diagnosis:**
```bash
git rev-parse --show-toplevel  # Should return repo root
```

**Fix:** Run from within a git repository, or use `--all` explicitly.

### Wrong project matched

**Cause:** Path encoding mismatch between sources and detection.

**Context:** Paths are encoded: `/Users/jane/Repos/foo` → `-Users-jane-Repos-foo`

**Known limitation:** Only `-Repos-` and `-.claude-` patterns are recognized. Handoffs from other locations (e.g., `~/Documents/`) won't have project_path extracted.

---

## Database Issues

### Database locked

**Cause:** Multiple processes accessing SQLite.

**Fix:** Wait and retry. If persistent:
```bash
# Kill any hanging processes
ps aux | grep "garde"
```

### Database corruption

**Symptoms:** Queries fail with SQLite errors.

**Fix:** Database can be rebuilt:
```bash
rm ~/.claude/memory/memory.db
uv run garde scan
uv run garde backfill
uv run garde sync-fts
```

---

## Extraction Issues

### API key not found

**Symptoms:** Backfill fails with authentication error.

**Fix:** Ensure `~/.claude/memory/env` contains:
```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

### Extraction quality is poor

**Cause:** Using Haiku instead of Sonnet.

**Context:** Haiku loses ~40% of learnings depth. The extraction pipeline uses Sonnet by default.

**If overridden:** Check extraction config, ensure Sonnet is specified.

### Old sessions have thin extractions

**Cause:** Older extraction prompts captured less detail.

**Fix:** Re-run backfill with `--force` (if implemented) or accept that older sessions have less rich extractions.

---

## Integration Issues

### Skill not triggering

**Symptoms:** Say "search memory" but skill doesn't invoke.

**Possible causes:**
- Skill not symlinked to `~/.claude/skills/garde`
- Session started before skill was created (needs reload)

**Fix:**
```bash
# Check symlink exists
ls -la ~/.claude/skills/garde

# If missing, create it
ln -sf ~/Repos/garde-manger/skill ~/.claude/skills/garde
```

Then restart Claude session for skill to load.

### Grounding skill not calling memory

**Cause:** Skills are independent; grounding orchestrates but user invokes.

**Expected behavior:** Grounding skill documents memory primitives; it doesn't auto-invoke memory skill. User controls when to search.

---

## Known Limitations

### Source types not indexed

Only these source types are supported:
- `claude_code` — Local sessions from `~/.claude/projects/`
- `handoff` — Files from `~/.claude/handoffs/`
- `claude_ai` — Synced via claude-data-sync
- `cloud_session` — Synced via claude-data-sync

Other conversation formats (exports, screenshots, etc.) not indexed.

### Path patterns for handoffs

`decode_parent_dir()` only recognizes:
- `-Repos-` → `~/Repos/`
- `-.claude-` → `~/.claude/`

Handoffs from other directories won't have project_path extracted.

### Warmup sessions filtered

Sessions with just "Warmup" or under 100 characters are excluded from backfill.

---

## Filing Issues

If you encounter a problem not covered here, file a bon item:

```bash
bon new "memory: [brief description]" \
  --why "[Detailed problem]" \
  --what "Debug and fix the issue" \
  --done "[Expected behavior restored]"
```

See SKILL.md "Feedback: Filing Issues" section for full templates.
