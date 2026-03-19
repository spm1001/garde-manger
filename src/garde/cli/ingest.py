"""Ingest commands — index and process session files."""

import click

from ..database import get_database
from ..adapters.claude_code import ClaudeCodeSource
from . import main
from ._helpers import _create_basic_summary, _flatten_extraction_for_fts


@main.command()
@click.argument('path', type=click.Path(exists=True))
@click.option('--no-extract', is_flag=True, help='Skip entity extraction (index only)')
@click.option('--no-hybrid', is_flag=True, help='Skip hybrid extraction (entities only)')
@click.option('--quiet', '-q', is_flag=True, help='Minimal output for scripted use')
@click.pass_context
def process(ctx, path, no_extract, no_hybrid, quiet):
    """Index a session file and run hybrid extraction.

    Designed for use by session-end hooks. Takes a single JSONL session file,
    indexes it into the database, and runs hybrid extraction (builds, learnings,
    patterns, etc.) plus entity extraction.

    Example:
        garde process ~/.claude/projects/-Users-foo/abc123.jsonl
    """
    from pathlib import Path as PathLib
    from ..extraction import extract_from_source
    from ..llm import extract_hybrid, MODEL

    config = ctx.obj['config']
    glossary = ctx.obj['glossary']

    session_path = PathLib(path).resolve()

    # Validate it's a JSONL file
    if session_path.suffix != '.jsonl':
        if not quiet:
            click.echo(f"Error: Expected .jsonl file, got: {session_path}")
        return

    # Parse the session file
    try:
        source = ClaudeCodeSource.from_file(session_path)
    except Exception as e:
        if not quiet:
            click.echo(f"Error parsing {session_path}: {e}")
        return

    # Skip warmup/empty sessions
    if source.title.lower() == 'warmup' or not source.messages:
        if not quiet:
            click.echo(f"Skipping empty/warmup session: {session_path.name}")
        return

    db = get_database()
    with db:
        # Index the source
        db.upsert_source(
            source_id=source.source_id,
            source_type='claude_code',
            title=source.title,
            path=str(source.path),
            created_at=source.created_at,
            updated_at=source.updated_at,
            is_subagent=source.is_subagent,
            project_path=source.project_path,
            metadata=source.metadata,
        )

        # Create summary
        summary = _create_basic_summary(source)
        db.upsert_summary(
            source_id=source.source_id,
            summary_text=summary,
            has_presummary=source.has_presummary,
        )
        db.mark_processed(source.source_id)

        if not quiet:
            click.echo(f"Indexed: {source.title[:60]}")
            click.echo(f"  ID: {source.source_id}")
        else:
            click.echo(f"INDEXED: {source.source_id}")

        # Extract entities unless skipped
        if not no_extract:
            try:
                full_text = source.full_text()
                is_voice = False  # Could detect from metadata if needed

                result = extract_from_source(
                    source_id=source.source_id,
                    full_text=full_text,
                    glossary=glossary,
                    db=db,
                    is_voice=is_voice,
                )

                if not quiet:
                    click.echo(f"  Entities: {result.entities_found} found, "
                              f"{result.matched} matched, {result.pending} pending")
                else:
                    # Even in quiet mode, output key stats for logging
                    click.echo(f"ENTITIES: {source.source_id} found={result.entities_found}")

            except RuntimeError as e:
                if not quiet:
                    click.echo(f"  Extraction error: {e}")
                else:
                    click.echo(f"ENTITIES_ERROR: {source.source_id} {e}")
                # Still successful for indexing, just no extraction
        elif not quiet:
            click.echo("  (entity extraction skipped)")

        # Run hybrid extraction (builds, learnings, patterns)
        if not no_hybrid:
            try:
                full_text = source.full_text()
                # Use semantic chunking with message data for better topic detection
                messages = source.messages_with_offsets()
                hybrid_result = extract_hybrid(full_text, messages=messages)

                db.upsert_extraction(
                    source_id=source.source_id,
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
                if not quiet:
                    click.echo(f"  Hybrid: {builds_count} builds, {learnings_count} learnings")
                else:
                    click.echo(f"HYBRID: {source.source_id} builds={builds_count} learnings={learnings_count}")

                # Sync extraction to FTS for immediate searchability
                rich_text = _flatten_extraction_for_fts(hybrid_result)
                db.upsert_summary(
                    source_id=source.source_id,
                    summary_text=rich_text,
                    has_presummary=True,
                )

            except RuntimeError as e:
                if not quiet:
                    click.echo(f"  Hybrid extraction error: {e}")
                else:
                    click.echo(f"HYBRID_ERROR: {source.source_id} {e}")
        elif not quiet:
            click.echo("  (hybrid extraction skipped)")


@main.command()
@click.argument('path', type=click.Path(exists=True))
@click.option('--quiet', '-q', is_flag=True, help='Minimal output for scripted use')
@click.pass_context
def index(ctx, path, quiet):
    """Index a session file without running extraction.

    Parses a JSONL session file, creates source + summary records in the
    database, and marks it processed. Does NOT run entity or hybrid extraction.

    Designed for use with staged extractions from /close — the session-end
    hook calls `garde index` to create the source record, then pipes the
    pre-generated extraction JSON into `garde store-extraction`.

    Example:
        garde index ~/.claude/projects/-Users-foo/abc123.jsonl
    """
    from pathlib import Path as PathLib

    session_path = PathLib(path).resolve()

    if session_path.suffix != '.jsonl':
        if not quiet:
            click.echo(f"Error: Expected .jsonl file, got: {session_path}")
        return

    try:
        source = ClaudeCodeSource.from_file(session_path)
    except Exception as e:
        if not quiet:
            click.echo(f"Error parsing {session_path}: {e}")
        return

    if source.title.lower() == 'warmup' or not source.messages:
        if not quiet:
            click.echo(f"Skipping empty/warmup session: {session_path.name}")
        return

    db = get_database()
    with db:
        db.upsert_source(
            source_id=source.source_id,
            source_type='claude_code',
            title=source.title,
            path=str(source.path),
            created_at=source.created_at,
            updated_at=source.updated_at,
            is_subagent=source.is_subagent,
            project_path=source.project_path,
            metadata=source.metadata,
        )

        summary = _create_basic_summary(source)
        db.upsert_summary(
            source_id=source.source_id,
            summary_text=summary,
            has_presummary=source.has_presummary,
        )
        db.mark_processed(source.source_id)

        if not quiet:
            click.echo(f"Indexed: {source.title[:60]}")
            click.echo(f"  ID: {source.source_id}")
        else:
            click.echo(f"INDEXED: {source.source_id}")
