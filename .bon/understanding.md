# Garde-manger — Understanding

> **Status: decommissioning (decided 2026-06-03).** garde is being retired. Its function — clean finished sessions → keep → find — folds into `~/notes`. This document is now a *teardown map*, not a portrait of a living system. The plan is **gm-kudasu** + 7 ordered actions; **gm-gumopi** (format), **gm-firaso** (predicate + AMP + tier) and **gm-kenave** (live hook — built+published, verify pending) are done — next is **gm-jewode** (the bulk export). NB the "106-session ark" that drove the original DB-deletion caution was **debunked 2026-06-03** (a matching artifact — see risk #1): the real off-both-disks set is 3 trivial sessions, so a cold DB backup is prudent hygiene, not the high-stakes gate it was framed as.

## The decision, in one breath

garde-the-database is over-built for its actual job. The job was only ever "clean finished sessions and make them findable." Measuring the payload collapsed the edifice: deglacer compresses raw CC JSONL ~74× (4.9 GB → 67 MB), and the real corpus is ~2,267 substantial CC sessions / **~61 MB** of deglacer-clean text — measured by a full deglacer pass over all 5,948 non-agent on-disk sessions (2026-06-03, `gm-firaso`); the earlier ~1,300 / 41 MB estimate predated the corpus growth from the `cleanupPeriodDays=99999` retention bump. Add 42 amp threads (~33 MB, Source C); the "~106 DB-only orphans" were a miscount (risk #1 — only 3 trivial sessions are genuinely DB-only). The 692 MB DB is mostly FTS-index bloat over that. deglacer is now a shared library, so it survives garde. `~/notes` already solves cross-machine (Syncthing) and is building a raw→digest→promote pipeline (`notes-sobute`) whose cleaning step *is* deglacer.

So: **retire garde-the-DB, keep garde-the-idea inside notes.** The corpus folds into `notes/raw/`. Search becomes Claude+grep over that folder — at 41 MB, a Claude with grep out-searches BM25 because it *judges* relevance rather than just ranking it. No database needed.

## The plan — gm-kudasu, 7 ordered actions

Strict sequence; each step's reason is the gate on the next.

| # | Action | What it does | Why it gates the next |
|---|--------|--------------|----------------------|
| 0 | **gm-gumopi** | Pin archive format (foldering / dating / frontmatter) + decommission done-criteria | Everything below writes into this format — decide it first |
| 1 | **gm-firaso** | Tune capture criteria + decide AMP in or out | Sets what the corpus *contains* before we build it |
| 2 | **gm-kenave** | Wire + **live-verify** the new `/close` → deglacer → notes hook | The replacement capture path; must be proven live before any teardown |
| 3 | **gm-jewode** | Build the canonical historical corpus into `notes/raw/` — garde's one last parse: Source A (disk, ~2,267; Hezza pass + a Mac-side pass for 295 Mac-only) + Source C (42 amp threads). Source B dropped (no ark — risk #1). | The actual preservation; depends on the format + capture rules above |
| 4 | **gm-jerapu** | Pass the verify-before-burn gate | Proves the export is complete + grep-findable on both machines before anything is destroyed |
| 5 | **gm-damoku** | Repoint garde's consumers (memory skill, hooks, cron, `garde search`) off the dying tool | Nothing should still call garde when the engines go off |
| 6 | **gm-pamadu** | Engines off, DB cold-backed-up, repo archived | The end — only after 2–5 are green |

**Done when** (canonical: `gm-kudasu --done`): Mac greps a 6-month-old session with Hezza unreachable; the next real `/close` drops a fresh dated markdown into `notes/raw/` that Syncs to Mac; nothing references garde (memory skill, hooks, cron, `garde search` all repointed or retired); the disk corpus (Source A both machines + amp) is confirmed present + grep-able in notes; the DB is retired to a cold backup; the repo is archived on GitHub.

**Archive format + capture predicate** are pinned (`gm-gumopi` + `gm-firaso`, 2026-06-03): flat files in `notes/raw/claude/code/`, kebab filenames `YYYY-MM-DD-HHMM-<slug>-<uuid8>.md`, frontmatter = converter fields + `machine` (the `tier` field was **dropped** — under one uniform filter everything kept is substantial, so the tag was redundant). The **capture predicate** — `real-/close OR conv≥3000 OR (turns≥8 AND conv≥800)`, excluding `agent-*` subagents and ~450 tmux-labeler automation sessions, applied uniformly to old + new — and the **AMP-in decision** (preserve 42 substantial threads via the amp adapter, tail-end) live in the full spec: `~/notes/raw/claude/_converters/ARCHIVE-FORMAT.md`.

## Three risks that shape the order

1. **The DB is NOT a unique ark — corrected 2026-06-03 (gm-jewode), this is a reversal of the prior claim.** The earlier "1,645 off-disk sources / 106 substantial / sole copy in the DB" was a **measurement artifact**. garde stores subagent sources as `claude_code:{uuid}` while their on-disk file is `agent-{uuid}.jsonl`, so a naïve `uuid in disk` check flags all ~1,702 subagents as "off-disk" (≈ the claimed 1,645). With the prefix handled — and the old JSONLs evidently re-synced to disk at some point (their mtimes are Feb 2026, their in-file timestamps Nov–Dec 2025) — the genuine off-**both**-disks set is **3 main sessions, all ~350 chars (trivial)**, all below the capture threshold. Ground-truthed: a 26-Nov session's JSONL exists on disk with matching content; the 3 true orphans are absent from Hezza *and* Mac (SSH-checked). **There is no substantial ark** — everything meaningful is on disk (source A). Consequence: **gm-pamadu's irreversibility risk collapses** — a cold DB backup stays prudent hygiene, but it guards 3 trivial summaries, not 106 irreplaceable sessions; and **gm-jewode's Source B (`--from-garde-db`) is dropped** (nothing substantial to recover). gm-jerapu lightens to "confirm the disk export is complete," not "verify the ark survived."

   **Cross-machine (gm-jewode step 1, 2026-06-03):** Mac has 1,640 main on-disk sessions, Hezza 4,932; 1,345 overlap, **295 Mac-only**, 3,587 Hezza-only. So Hezza is the bulk but not a superset — jewode needs a **Mac-side converter pass too** for the 295. The converter's skip-existing-by-`uuid8` dedups the overlap automatically via the shared Syncthing'd `notes/raw/claude/code/`.

2. **The capture-gap in teardown order.** The new `/close` → deglacer → notes hook (gm-kenave) must be **live and verified** *before* garde's own hooks are torn down (gm-pamadu) — otherwise sessions fall through the gap between the two systems. Replacement before teardown, always.

3. **The tree is mid-migration.** Don't start the file-moving work until Mac's repo migration settles, or you'll get rug-pulls — the previous session lost its cwd to exactly that. This repo moved from `~/repos/batterie/garde-manger` to `~/repos/spm1001/garde-manger` mid-session (part of the `batterie/* → {spm1001,itv,third-party}/` owner-bucket migration). **Hezza is canonical** (clean 3-bucket layout); **Mac is the satellite** (loose top-level repos, cornichon still in `batterie/`).

## The sync model — do not conflate the two layers

Sameer flagged this explicitly. Two independent sync mechanisms:

- **`~/notes` → Syncthing** (Hezza ↔ Mac, sub-2s on LAN). The garde corpus folds into `notes/raw/` *precisely so* Mac sees the whole archive via **notes' Syncthing** — that IS the cross-machine transparency mechanism.
- **`~/repos` → git** (Hezza canonical, Mac auto-pulls). `.git` is deliberately **not** Syncthing'd (corruption risk). garde-manger lives in `~/repos`, so it syncs by **git**, not Syncthing.

We did **not** plan to Syncthing `~/repos`. The archive's transparency comes from landing in **notes**, not from where this repo lives.

## What garde was — reference for the one-last-parse (gm-jewode)

Enough of the old architecture to do the export correctly. Everything below is *how it works*, kept only because gm-jewode needs it.

**deglacer is the load-bearing survivor.** The CC adapter (`src/garde/adapters/`) is a thin wrapper: `full_text()` delegates to `deglacer.build_turns()` + `format_text()`, which handles compaction boundaries, streaming-message dedup, and system-tag stripping. This is exactly the cleaning step the export needs — and it's a shared git library, so it outlives garde. Metadata extraction (tools, files, skills, commits) stays local to the adapter.

**Where the data is.** DB lives at `~/.claude/plugins/data/garde-manager-batterie-de-savoir/memory.db` (plugin data dir, persists across plugin updates; legacy location `~/.claude/memory/memory.db` may be a symlink). Config (`config.yaml`, `glossary.yaml`) stays at `~/.claude/memory/`.

**The divergence between machines (as of 2026-06-03).** Both run garde (SessionEnd hook fires), but badly diverged:
- **Hezza healthy** — ~9,919 sources, ~7,613 extractions, current to today. This is the real archive.
- **Mac stunted** — 134 sources, **0 extractions ever** (backfill never bootstrapped locally). Do the export from Hezza's DB, not Mac's.

**The data model (for reading the DB out).** Sources are the index (composite `source_id` like `claude_code:uuid`). Summaries hold pre-parsed summaries + raw text + FTS5. Extractions are the LLM/handoff-parse semantic layer (summary, builds, learnings, friction, patterns, open_threads). (The old "106 off-disk sessions live only in the DB" claim is debunked — see risk #1; only 3 trivial sessions are genuinely DB-only, so this read-out-the-DB rationale no longer drives Source B.)

**Recovery is not server-side.** Local CC transcripts have no user-facing read path on Anthropic's servers (only the 117 claude.ai web chats are listable) — so for any session genuinely off both disks, the DB would be the only copy. But that set turned out to be just 3 trivial sessions (risk #1), so this is now moot rather than load-bearing.

## Landmines still live

- **`--limit 0` means SQL `LIMIT 0` (returns nothing), not "unlimited."** Use `--limit 10000`.
- **Fork-bomb guard is non-negotiable while garde still runs.** `_call_claude()` sets `GARDE_SUBAGENT=1`; hooks check it and exit early. Don't remove until gm-pamadu turns the engines off.
- **`uv tool install` caches stale binaries** — cron uses the installed binary, not `uv run`. Reinstall after code changes (relevant if gm-kenave touches CLI before teardown).
- **bon here uses the Dolt backend** (`dolt-bon.service` on hezza), so bon items are directory-independent — which is why gm-kudasu survived the repo move. If `bon` fails with "Cannot connect," start the service on hezza.
- **Crumb:** `dotfiles/UPGRADING.md` lines 68-69 still cite `~/Repos/batterie` paths (cosmetic, fix-on-contact).
