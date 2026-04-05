"""Extraction commands — LLM-powered extraction and backfill."""

import json

import click

from ..database import get_database
from . import main
from ._helpers import _flatten_extraction_for_fts


@main.command()
@click.argument('source_id')
@click.option('--dry-run', is_flag=True, help='Show what would be extracted without storing')
@click.pass_context
def extract(ctx, source_id, dry_run):
    """Extract entities from a source using LLM.

    Uses claude -p (Max subscription billing).
    """
    from ..extraction import extract_from_source, get_source_content

    config = ctx.obj['config']
    glossary = ctx.obj['glossary']

    db = get_database()
    with db:
        source = db.get_source(source_id)
        if not source:
            click.echo(f"Source not found: {source_id}")
            return

        click.echo(f"Extracting from: {source['title'][:60]}")
        click.echo(f"Type: {source['source_type']}")

        try:
            full_text, is_voice = get_source_content(source_id, db, config)
        except Exception as e:
            click.echo(f"Error loading content: {e}")
            return

        click.echo(f"Content: {len(full_text)} chars")
        if is_voice:
            click.echo("(Voice transcription detected)")

        if dry_run:
            click.echo("\n[Dry run - would call LLM for extraction]")
            click.echo(f"Glossary has {len(glossary.entities)} entities for matching")
            return

        try:
            result = extract_from_source(
                source_id=source_id,
                full_text=full_text,
                glossary=glossary,
                db=db,
                is_voice=is_voice,
            )
        except RuntimeError as e:
            click.echo(f"Error: {e}")
            return

        click.echo(f"\nExtracted {result.entities_found} entities:")
        click.echo(f"  Matched to glossary: {result.matched}")
        click.echo(f"  Pending resolution: {result.pending}")

        if result.entities:
            click.echo("\nEntities found:")
            for e in result.entities:
                status = "matched" if glossary.resolve(e['mention']) else "pending"
                suggested = f" → {e.get('suggested_canonical')}" if e.get('suggested_canonical') else ""
                click.echo(f"  [{e.get('confidence', '?')}] {e['mention']}{suggested} ({status})")


@main.command()
@click.option('--limit', '-n', default=10, help='Maximum sources to process')
@click.option('--source-type', type=str, help='Only process this source type')
@click.option('--skip-short', is_flag=True, help='Mark sources with <100 chars as skipped instead of processing')
@click.option('--dry-run', is_flag=True, help='Show what would be processed')
@click.pass_context
def backfill(ctx, limit, source_type, skip_short, dry_run):
    """Backfill hybrid extractions for existing sources.

    Finds sources without extractions and runs hybrid extraction on them.
    Uses claude -p (Opus 4.6 via Max subscription) for all extractions.
    Use --limit to control batch size (default 10).
    Use --skip-short to mark sources with insufficient content as skipped.

    Example:
        garde backfill --limit 50 --source-type claude_code
        garde backfill --limit 500 --skip-short
    """
    from ..llm import extract_hybrid, MODEL
    from ..adapters.claude_code import ClaudeCodeSource

    db = get_database()
    with db:
        # Find sources without extractions
        conn = db.connect()

        sql = """
            SELECT s.id, s.source_type, s.title, s.path
            FROM sources s
            LEFT JOIN extractions e ON s.id = e.source_id
            WHERE e.source_id IS NULL
        """
        params = []

        if source_type:
            sql += " AND s.source_type = ?"
            params.append(source_type)

        sql += " ORDER BY s.updated_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()

        if not rows:
            click.echo("No sources need backfill.")
            return

        click.echo(f"Found {len(rows)} sources without extractions")

        if dry_run:
            for row in rows:
                click.echo(f"  [{row['source_type']}] {row['title'][:60]}...")
            click.echo(f"\nDry run: would process {len(rows)} sources")
            return

        processed = 0
        failed = 0

        for row in rows:
            source_id = row['id']
            source_type_val = row['source_type']
            path = row['path']

            click.echo(f"\nProcessing: {row['title'][:50]}...")

            try:
                # Load source to get full text and messages (for semantic chunking)
                messages = None  # Only available for claude_code sources
                if source_type_val == 'claude_code':
                    from pathlib import Path as PathLib
                    source = ClaudeCodeSource.from_file(PathLib(path))
                    full_text = source.full_text()
                    messages = source.messages_with_offsets()
                else:
                    # For other types, try to get from summaries table
                    summary_row = conn.execute(
                        "SELECT summary_text FROM summaries WHERE source_id = ?",
                        (source_id,)
                    ).fetchone()
                    if summary_row:
                        full_text = summary_row['summary_text']
                    else:
                        if skip_short:
                            db.upsert_extraction(source_id=source_id, model_used='skipped:no_content')
                            click.echo(f"  Marked skipped: no content")
                        else:
                            click.echo(f"  Skipping: no content available")
                        continue

                if not full_text or len(full_text) < 100:
                    if skip_short:
                        db.upsert_extraction(source_id=source_id, model_used='skipped:content_too_short')
                        click.echo(f"  Marked skipped: content too short")
                    else:
                        click.echo(f"  Skipping: content too short")
                    continue

                # Run hybrid extraction (uses semantic chunking if messages available)
                hybrid_result = extract_hybrid(full_text, messages=messages)

                db.upsert_extraction(
                    source_id=source_id,
                    summary=hybrid_result.get('summary'),
                    arc=hybrid_result.get('arc'),
                    builds=hybrid_result.get('builds'),
                    learnings=hybrid_result.get('learnings'),
                    friction=hybrid_result.get('friction'),
                    patterns=hybrid_result.get('patterns'),
                    open_threads=hybrid_result.get('open_threads'),
                    model_used=MODEL,
                )

                builds_count = len(hybrid_result.get('builds', []))
                learnings_count = len(hybrid_result.get('learnings', []))
                click.echo(f"  {builds_count} builds, {learnings_count} learnings")
                processed += 1

            except Exception as e:
                click.echo(f"  Error: {e}")
                failed += 1

        click.echo(f"\nBackfill complete: {processed} processed, {failed} failed")


@main.command('extract-prompt')
@click.argument('source_id')
@click.pass_context
def extract_prompt(ctx, source_id):
    """Output the extraction prompt for a source.

    Outputs the hybrid extraction prompt with session content filled in.
    Useful for debugging extraction prompts or manual extraction.

    Example:
        uv run garde extract-prompt claude_code:abc123
    """
    from ..extraction import get_source_content
    from ..llm import HYBRID_EXTRACTION_PROMPT

    config = ctx.obj['config']
    db = get_database()

    with db:
        source = db.get_source(source_id)
        if not source:
            click.echo(f"Source not found: {source_id}", err=True)
            raise SystemExit(1)

    try:
        full_text, _ = get_source_content(source_id, db, config)
    except Exception as e:
        click.echo(f"Error loading content: {e}", err=True)
        raise SystemExit(1)

    # Truncate if needed (same limit as extract_hybrid)
    max_chars = 140000
    if len(full_text) > max_chars:
        full_text = full_text[:max_chars]
        full_text += f"\n\n[... truncated, showing first {max_chars} chars ...]"

    # Output the prompt with content filled in
    prompt = HYBRID_EXTRACTION_PROMPT.format(content=full_text)
    click.echo(prompt)


