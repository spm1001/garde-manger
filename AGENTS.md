# Agent Instructions

> For Claude Code agents working on this codebase. Humans can ignore this file.

This project uses [arc](https://github.com/spm1001/arc) for work tracking. Arc organizes work as **Outcomes** (desired results) and **Actions** (concrete steps).

## Quick Reference

```bash
arc list                # Hierarchical view of open work
arc list --ready        # Actions with no waiting_for
arc show <id>           # Full details including brief (why/what/done)
arc new "title" --why W --what X --done D  # Create outcome
arc done <id>           # Complete item
```

## Draw-Down Pattern

**Before starting work on an arc item:**

1. `arc show <id>` — read the brief (why/what/done)
2. Create TodoWrite items from `what` and `done` criteria
3. Show user: "Breaking this down into: [list]. Sound right?"
4. Work through with checkpoints

**The test:** Could a Claude with zero context execute this from the brief alone?

## Landing the Plane (Session Completion)

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File work for remaining items** - Create arc items with full briefs for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update work status** - `arc done <id>` for finished work
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
