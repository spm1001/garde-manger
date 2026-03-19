"""FTS maintenance commands — index rebuilding and data backfill."""

from pathlib import Path

import click

from ..config import load_config
from ..database import get_database
from ..adapters.claude_code import ClaudeCodeSource
from ..adapters.claude_ai import ClaudeAISource
from ..adapters.cloud_sessions import CloudSessionSource
from ..adapters.handoffs import HandoffSource
from ..adapters.local_md import LocalMdSource
from . import main
from ._helpers import _flatten_extraction_for_fts


@main.command('sync-fts')
@click.pass_context
def sync_fts(ctx):
    """Sync FTS index with extraction summaries and learnings.

    Updates the FTS index for all sources that have extractions,
    replacing thin scan summaries with rich extraction content
    including flattened learnings, builds, and friction.
    """
    db = get_database()
    conn = db.connect()

    # Find all extractions
    rows = conn.execute("""
        SELECT e.source_id, e.summary, e.learnings, e.builds, e.friction,
               s.summary_text
        FROM extractions e
        JOIN summaries s ON e.source_id = s.source_id
        WHERE e.summary IS NOT NULL
    """).fetchall()

    if not rows:
        click.echo("No extractions to sync.")
        return

    click.echo(f"Checking {len(rows)} sources with extractions...")

    updated = 0
    for row in rows:
        # Build rich searchable text
        extraction = {
            'summary': row['summary'],
            'learnings': row['learnings'],
            'builds': row['builds'],
            'friction': row['friction'],
        }
        rich_text = _flatten_extraction_for_fts(extraction)

        # Only update if different
        if row['summary_text'] != rich_text:
            conn.execute("""
                UPDATE summaries SET summary_text = ?
                WHERE source_id = ?
            """, (rich_text, row['source_id']))
            updated += 1

    conn.commit()
    click.echo(f"Updated {updated} FTS entries with rich extraction content.")


@main.command('rebuild-fts')
@click.pass_context
def rebuild_fts(ctx):
    """Rebuild FTS index from scratch.

    Drops and recreates the summaries_fts table, repopulating from
    the summaries table. Use after schema changes or data corruption.

    This also ensures raw_text is indexed for full-text search.
    """
    db = get_database()
    conn = db.connect()

    click.echo("Dropping old FTS table and triggers...")

    # Drop triggers first
    conn.execute("DROP TRIGGER IF EXISTS summaries_ai")
    conn.execute("DROP TRIGGER IF EXISTS summaries_ad")
    conn.execute("DROP TRIGGER IF EXISTS summaries_au")

    # Drop and recreate FTS table
    conn.execute("DROP TABLE IF EXISTS summaries_fts")
    conn.execute("""
        CREATE VIRTUAL TABLE summaries_fts USING fts5(
            source_id,
            title,
            summary_text,
            raw_text
        )
    """)

    # Recreate triggers
    conn.execute("""
        CREATE TRIGGER summaries_ai AFTER INSERT ON summaries BEGIN
            INSERT INTO summaries_fts(rowid, source_id, title, summary_text, raw_text)
            SELECT s.rowid, s.source_id, src.title, s.summary_text, s.raw_text
            FROM summaries s JOIN sources src ON s.source_id = src.id
            WHERE s.source_id = NEW.source_id;
        END
    """)
    conn.execute("""
        CREATE TRIGGER summaries_ad AFTER DELETE ON summaries BEGIN
            DELETE FROM summaries_fts WHERE rowid = OLD.rowid;
        END
    """)
    conn.execute("""
        CREATE TRIGGER summaries_au AFTER UPDATE ON summaries BEGIN
            DELETE FROM summaries_fts WHERE rowid = OLD.rowid;
            INSERT INTO summaries_fts(rowid, source_id, title, summary_text, raw_text)
            SELECT s.rowid, s.source_id, src.title, s.summary_text, s.raw_text
            FROM summaries s JOIN sources src ON s.source_id = src.id
            WHERE s.source_id = NEW.source_id;
        END
    """)

    # Count rows to repopulate
    count = conn.execute("SELECT COUNT(*) FROM summaries").fetchone()[0]
    click.echo(f"Repopulating FTS index with {count} entries...")

    # Repopulate FTS
    conn.execute("""
        INSERT INTO summaries_fts(rowid, source_id, title, summary_text, raw_text)
        SELECT s.rowid, s.source_id, src.title, s.summary_text, s.raw_text
        FROM summaries s
        JOIN sources src ON s.source_id = src.id
    """)

    conn.commit()

    click.echo(f"FTS index rebuilt with {count} entries (including raw_text).")


@main.command('verify-fts')
@click.pass_context
def verify_fts(ctx):
    """Verify FTS index is in sync with summaries table.

    Checks that every summary has a corresponding FTS entry and
    reports any mismatches.
    """
    db = get_database()
    conn = db.connect()

    # Count summaries
    summaries_count = conn.execute("SELECT COUNT(*) FROM summaries").fetchone()[0]

    # Count FTS entries
    fts_count = conn.execute("SELECT COUNT(*) FROM summaries_fts").fetchone()[0]

    # Find orphaned FTS entries (in FTS but not in summaries)
    orphaned = conn.execute("""
        SELECT source_id FROM summaries_fts
        WHERE source_id NOT IN (SELECT source_id FROM summaries)
    """).fetchall()

    # Find missing FTS entries (in summaries but not in FTS)
    missing = conn.execute("""
        SELECT source_id FROM summaries
        WHERE source_id NOT IN (SELECT source_id FROM summaries_fts)
    """).fetchall()

    click.echo(f"Summaries: {summaries_count}")
    click.echo(f"FTS entries: {fts_count}")

    if orphaned:
        click.echo(f"\nOrphaned FTS entries (no summary): {len(orphaned)}")
        for row in orphaned[:5]:
            click.echo(f"  - {row[0]}")
        if len(orphaned) > 5:
            click.echo(f"  ... and {len(orphaned) - 5} more")

    if missing:
        click.echo(f"\nMissing FTS entries (have summary): {len(missing)}")
        for row in missing[:5]:
            click.echo(f"  - {row[0]}")
        if len(missing) > 5:
            click.echo(f"  ... and {len(missing) - 5} more")

    if not orphaned and not missing and summaries_count == fts_count:
        click.echo("\nFTS index is in sync with summaries.")
    else:
        click.echo("\nFTS index is out of sync. Run 'uv run garde rebuild-fts' to fix.")


@main.command('populate-raw-text')
@click.option('--batch-size', default=50, help="Number of sources to process per batch (syncs after each)")
@click.option('--limit', default=0, help="Max sources to process (0 = all)")
@click.pass_context
def populate_raw_text(ctx, batch_size, limit):
    """Populate raw_text for summaries missing it.

    Faster than full scan - only updates summaries without raw_text,
    loading source content on demand.
    """
    db = get_database()
    conn = db.connect()

    # Find summaries missing raw_text
    query = """
        SELECT s.source_id, s.summary_text, src.source_type, src.path
        FROM summaries s
        JOIN sources src ON s.source_id = src.id
        WHERE s.raw_text IS NULL OR s.raw_text = ''
        ORDER BY CASE src.source_type
            WHEN 'claude_code' THEN 1
            WHEN 'claude_ai' THEN 2
            WHEN 'handoff' THEN 3
            WHEN 'cloud_session' THEN 4
            WHEN 'bon' THEN 5
            WHEN 'local_md' THEN 6
            ELSE 7
        END
    """
    if limit > 0:
        query += f" LIMIT {limit}"

    missing = conn.execute(query).fetchall()
    total = len(missing)
    click.echo(f"Found {total} summaries missing raw_text")

    if total == 0:
        click.echo("Nothing to do!")
        return

    updated = 0
    errors = 0
    config = ctx.obj or load_config()

    for i, row in enumerate(missing):
        source_id = row[0]
        source_type = row[2]
        path_str = row[3]

        try:
            # Load source based on type using from_file classmethod
            raw_text = None
            p = Path(path_str) if path_str else None

            if source_type == 'claude_code' and p and p.exists():
                source = ClaudeCodeSource.from_file(p)
                raw_text = source.full_text()

            elif source_type == 'claude_ai' and path_str and path_str.startswith('claude_ai:'):
                # Resolve virtual claude_ai:{uuid} path to actual file
                uuid = path_str.split(':', 1)[1]
                ai_base = config.get('sources', {}).get('claude_ai', {}).get(
                    'path', '~/.claude/claude-ai/cache/conversations'
                )
                actual_path = Path(ai_base).expanduser() / f"{uuid}.json"
                if actual_path.exists():
                    source = ClaudeAISource.from_file(actual_path)
                    raw_text = source.full_text()

            elif source_type == 'handoff' and p and p.exists():
                source = HandoffSource.from_file(p)
                raw_text = source.full_text()

            elif source_type == 'cloud_session' and p and p.exists():
                source = CloudSessionSource.from_file(p)
                raw_text = source.full_text()

            elif source_type == 'local_md' and p and p.exists():
                # LocalMdSource.from_file needs base_path; use parent as approximation
                source = LocalMdSource.from_file(p, p.parent)
                raw_text = source.full_text()

            if raw_text:
                # Cap at 100K chars
                if len(raw_text) > 100_000:
                    raw_text = raw_text[:100_000]

                conn.execute("""
                    UPDATE summaries SET raw_text = ?
                    WHERE source_id = ?
                """, (raw_text, source_id))
                updated += 1

                if updated % batch_size == 0:
                    conn.commit()
                    click.echo(f"  Progress: {updated}/{total} ({100*updated//total}%)")

        except Exception as e:
            errors += 1
            if errors <= 5:
                click.echo(f"  Error on {source_id}: {e}")

    conn.commit()

    click.echo(f"Updated {updated} summaries with raw_text ({errors} errors)")
