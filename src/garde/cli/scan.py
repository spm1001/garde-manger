"""Scan command — discover and index sources."""

import click

from ..database import get_database
from ..adapters.claude_code import discover_claude_code, ClaudeCodeSource
from ..adapters.claude_ai import discover_claude_ai, ClaudeAISource
from ..adapters.cloud_sessions import discover_cloud_sessions, CloudSessionSource
from ..adapters.handoffs import discover_handoffs, HandoffSource
from ..adapters.local_md import discover_local_md, LocalMdSource
from ..adapters.bon import discover_bon, BonSource
from ..adapters.knowledge import discover_knowledge, KnowledgeSource
from ..adapters.amp import discover_amp, AmpSource
from . import main
from ._helpers import _create_basic_summary, _flatten_extraction_for_fts


@main.command()
@click.option('--dry-run', is_flag=True, help="Show what would be indexed without storing")
@click.option('--source', 'source_filter',
              type=click.Choice(['claude_code', 'claude_ai', 'handoffs', 'cloud_sessions', 'local_md', 'bon', 'knowledge', 'amp']),
              help="Only scan this source type")
@click.pass_context
def scan(ctx, dry_run, source_filter):
    """Discover and index Claude Code conversations."""
    config = ctx.obj['config']

    # Determine which sources to scan
    scan_claude_code = source_filter is None or source_filter == 'claude_code'
    scan_claude_ai = source_filter is None or source_filter == 'claude_ai'
    scan_handoffs = source_filter is None or source_filter == 'handoffs'
    scan_cloud = source_filter is None or source_filter == 'cloud_sessions'
    scan_local_md = source_filter is None or source_filter == 'local_md'
    scan_bon = source_filter is None or source_filter == 'bon'
    scan_knowledge = source_filter is None or source_filter == 'knowledge'
    scan_amp = source_filter is None or source_filter == 'amp'

    if not scan_claude_code:
        click.echo(f"Skipping Claude Code conversations...")
    else:
        click.echo(f"Scanning Claude Code conversations...")

    db = get_database()
    with db:
        new_count = 0
        updated_count = 0
        skipped_count = 0

        if scan_claude_code:
            for source in discover_claude_code(config):
                exists = db.source_exists(source.source_id)

                if dry_run:
                    status = "exists" if exists else "new"
                    click.echo(f"  [{status}] {source.source_id}: {source.title[:60]}...")
                    if not exists:
                        new_count += 1
                    continue

                # Store source metadata
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

                # Create summary (use presummary if available, else basic extraction)
                summary = _create_basic_summary(source)
                db.upsert_summary(
                    source_id=source.source_id,
                    summary_text=summary,
                    has_presummary=source.has_presummary,
                    raw_text=source.full_text(),
                )
                db.mark_processed(source.source_id)

                if exists:
                    updated_count += 1
                else:
                    new_count += 1
                    click.echo(f"  + {source.title[:70]}...")

        # Scan Claude.ai conversations
        ai_new = 0
        ai_updated = 0

        if scan_claude_ai:
            click.echo(f"\nScanning Claude.ai conversations...")
            for source in discover_claude_ai(config):
                exists = db.source_exists(source.source_id)

                if dry_run:
                    status = "exists" if exists else "new"
                    click.echo(f"  [{status}] {source.source_id}: {source.name[:60]}...")
                    if not exists:
                        ai_new += 1
                    continue

                # Store source metadata
                db.upsert_source(
                    source_id=source.source_id,
                    source_type='claude_ai',
                    title=source.name,
                    path=f"claude_ai:{source.uuid}",  # Virtual path using UUID
                    created_at=source.created_at,
                    updated_at=source.updated_at,
                )

                # Use pre-generated summary (Claude.ai has these)
                summary = source.summary if source.summary else source.name
                db.upsert_summary(
                    source_id=source.source_id,
                    summary_text=summary,
                    has_presummary=source.has_presummary,
                    raw_text=source.full_text(),
                )
                db.mark_processed(source.source_id)

                if exists:
                    ai_updated += 1
                else:
                    ai_new += 1
                    click.echo(f"  + {source.name[:70]}...")

        # Scan handoff files
        handoff_new = 0
        handoff_updated = 0

        handoff_extracted = 0
        handoff_skipped = 0

        if scan_handoffs:
            click.echo(f"\nScanning handoff files...")
            for source in discover_handoffs(config):
                existing = db.get_source(source.source_id)
                mtime_str = str(source.mtime)

                if existing and existing.get('content_hash') == mtime_str:
                    handoff_skipped += 1
                    continue

                if dry_run:
                    status = "exists" if existing else "new"
                    click.echo(f"  [{status}] {source.source_id}: {source.title[:60]}...")
                    if not existing:
                        handoff_new += 1
                    continue

                exists = existing is not None

                # Store source metadata
                db.upsert_source(
                    source_id=source.source_id,
                    source_type='handoff',
                    title=source.title,
                    path=str(source.path),
                    created_at=source.date,
                    updated_at=source.date,
                    project_path=source.project_path,
                    content_hash=mtime_str,
                )

                # Use full text as summary (handoffs are already distilled)
                full_text = source.full_text()
                db.upsert_summary(
                    source_id=source.source_id,
                    summary_text=full_text,
                    has_presummary=True,
                    raw_text=full_text,
                )

                # Extract structured fields from handoff sections (free, no LLM)
                extraction = source.to_extraction()
                if extraction:
                    db.upsert_extraction(
                        source_id=source.source_id,
                        summary=extraction.get('summary'),
                        arc=extraction.get('arc'),
                        builds=extraction.get('builds'),
                        learnings=extraction.get('learnings'),
                        friction=extraction.get('friction'),
                        patterns=extraction.get('patterns'),
                        open_threads=extraction.get('open_threads'),
                        model_used='handoff-section-parse',
                    )
                    # Sync to FTS for searchability
                    rich_text = _flatten_extraction_for_fts(extraction)
                    if rich_text:
                        db.upsert_summary(
                            source_id=source.source_id,
                            summary_text=rich_text,
                            has_presummary=True,
                            raw_text=full_text,
                        )
                    handoff_extracted += 1

                db.mark_processed(source.source_id)

                if exists:
                    handoff_updated += 1
                else:
                    handoff_new += 1
                    click.echo(f"  + {source.title[:70]}...")

        # Scan cloud sessions (Claude Code for web)
        cloud_new = 0
        cloud_updated = 0

        if scan_cloud:
            click.echo(f"\nScanning cloud sessions...")
            for source in discover_cloud_sessions(config):
                exists = db.source_exists(source.source_id)

                if dry_run:
                    status = "exists" if exists else "new"
                    click.echo(f"  [{status}] {source.source_id}: {source.title[:60]}...")
                    if not exists:
                        cloud_new += 1
                    continue

                # Store source metadata
                db.upsert_source(
                    source_id=source.source_id,
                    source_type='cloud_session',
                    title=source.title,
                    path=str(source.path),
                    created_at=source.created_at,
                    updated_at=source.updated_at,
                    metadata=source.metadata,
                )

                # Use summary if available, else full text
                summary = source.summary_text if source.summary_text else source.full_text()[:500]
                db.upsert_summary(
                    source_id=source.source_id,
                    summary_text=summary,
                    has_presummary=source.has_presummary,
                    raw_text=source.full_text(),
                )
                db.mark_processed(source.source_id)

                if exists:
                    cloud_updated += 1
                else:
                    cloud_new += 1
                    click.echo(f"  + {source.title[:70]}...")

        # Scan local markdown files
        local_md_new = 0
        local_md_updated = 0
        local_md_skipped = 0

        if scan_local_md:
            click.echo(f"\nScanning local markdown files...")
            for source in discover_local_md(config):
                # Check if file has changed since last scan (mtime-based)
                existing = db.get_source(source.source_id)
                mtime_str = str(source.mtime)

                if existing and existing.get('content_hash') == mtime_str:
                    # File unchanged, skip processing
                    local_md_skipped += 1
                    continue

                if dry_run:
                    status = "exists" if existing else "new"
                    click.echo(f"  [{status}] {source.source_id}: {source.title[:60]}...")
                    if not existing:
                        local_md_new += 1
                    continue

                # Store source metadata with mtime for change detection
                db.upsert_source(
                    source_id=source.source_id,
                    source_type='local_md',
                    title=source.title,
                    path=str(source.path),
                    created_at=source.date,
                    updated_at=source.date,
                    project_path=source.project_path,
                    content_hash=mtime_str,
                )

                # Index full content (no LLM summarization)
                # For local_md, summary_text = raw_text (both are full content)
                full_text = source.full_text()
                db.upsert_summary(
                    source_id=source.source_id,
                    summary_text=full_text,
                    has_presummary=False,
                    raw_text=full_text,
                )
                db.mark_processed(source.source_id)

                if existing:
                    local_md_updated += 1
                else:
                    local_md_new += 1
                    if local_md_new <= 10:  # Limit output for large scans
                        click.echo(f"  + {source.title[:70]}...")
                    elif local_md_new == 11:
                        click.echo(f"  ... (limiting output)")

        # Scan bon (lightweight work tracker)
        bon_new = 0
        bon_updated = 0
        bon_skipped = 0

        if scan_bon:
            click.echo(f"\nScanning bon...")
            for source in discover_bon(config):
                existing = db.get_source(source.source_id)
                created_at_str = source.created_at.isoformat() if source.created_at else ''

                # Use done_at for change detection (items change when completed)
                change_key = f"{created_at_str}:{source.status}"
                if existing and existing.get('content_hash') == change_key:
                    bon_skipped += 1
                    continue

                if dry_run:
                    status = "exists" if existing else "new"
                    click.echo(f"  [{status}] {source.source_id}: {source.title[:60]}...")
                    if not existing:
                        bon_new += 1
                    continue

                db.upsert_source(
                    source_id=source.source_id,
                    source_type='bon',
                    title=source.title,
                    path=str(source.path),
                    created_at=source.created_at,
                    updated_at=source.done_at or source.created_at,
                    project_path=source.project_path,
                    content_hash=change_key,
                    metadata=source.metadata,
                )

                full_text = source.full_text()
                db.upsert_summary(
                    source_id=source.source_id,
                    summary_text=full_text,
                    has_presummary=True,
                    raw_text=full_text,
                )
                db.mark_processed(source.source_id)

                if existing:
                    bon_updated += 1
                else:
                    bon_new += 1
                    click.echo(f"  + {source.title[:70]}...")

        # Scan knowledge articles
        knowledge_new = 0
        knowledge_updated = 0
        knowledge_skipped = 0

        if scan_knowledge:
            click.echo(f"\nScanning knowledge articles...")
            for source in discover_knowledge(config):
                # Check if file has changed since last scan (mtime-based)
                existing = db.get_source(source.source_id)
                mtime_str = str(source.mtime)

                if existing and existing.get('content_hash') == mtime_str:
                    # File unchanged, skip processing
                    knowledge_skipped += 1
                    continue

                if dry_run:
                    status = "exists" if existing else "new"
                    click.echo(f"  [{status}] {source.source_id}: {source.title[:60]}...")
                    if not existing:
                        knowledge_new += 1
                    continue

                # Store source metadata with mtime for change detection
                db.upsert_source(
                    source_id=source.source_id,
                    source_type='knowledge',
                    title=source.title,
                    path=str(source.path),
                    created_at=source.date,
                    updated_at=source.date,
                    project_path=source.project_path,
                    content_hash=mtime_str,
                )

                # Index full content (knowledge is already distilled)
                full_text = source.full_text()
                db.upsert_summary(
                    source_id=source.source_id,
                    summary_text=full_text,
                    has_presummary=True,
                    raw_text=full_text,
                )
                db.mark_processed(source.source_id)

                if existing:
                    knowledge_updated += 1
                else:
                    knowledge_new += 1
                    if knowledge_new <= 10:
                        click.echo(f"  + {source.title[:70]}...")
                    elif knowledge_new == 11:
                        click.echo(f"  ... (limiting output)")

        # Scan Amp threads
        amp_new = 0
        amp_updated = 0
        amp_skipped = 0

        if scan_amp:
            click.echo(f"\nScanning Amp threads...")
            for source in discover_amp(config):
                existing = db.get_source(source.source_id)
                # Use updated_at for change detection (new messages update this)
                change_key = source.updated_at.isoformat()

                if existing and existing.get('content_hash') == change_key:
                    amp_skipped += 1
                    continue

                if dry_run:
                    status = "exists" if existing else "new"
                    click.echo(f"  [{status}] {source.source_id}: {source.title[:60]}")
                    if not existing:
                        amp_new += 1
                    continue

                db.upsert_source(
                    source_id=source.source_id,
                    source_type='amp',
                    title=source.title,
                    path=str(source.path),
                    created_at=source.created_at,
                    updated_at=source.updated_at,
                    project_path=source.project_path,
                    content_hash=change_key,
                    metadata=source.metadata,
                )

                full_text = source.full_text()
                if full_text:
                    db.upsert_summary(
                        source_id=source.source_id,
                        summary_text=source.title,  # Placeholder until backfill or amp-close extracts
                        has_presummary=False,  # Needs LLM extraction — title is NOT a real summary
                        raw_text=full_text,
                    )

                if existing:
                    amp_updated += 1
                else:
                    amp_new += 1
                    click.echo(f"  + {source.title[:70]}")

        if dry_run:
            click.echo(f"\nDry run: {new_count} Claude Code, {ai_new} Claude.ai, {handoff_new} handoffs, {cloud_new} cloud, {local_md_new} local_md, {bon_new} bon, {knowledge_new} knowledge, {amp_new} amp new")
        else:
            total_new = new_count + ai_new + handoff_new + cloud_new + local_md_new + bon_new + knowledge_new + amp_new
            total_updated = updated_count + ai_updated + handoff_updated + cloud_updated + local_md_updated + bon_updated + knowledge_updated + amp_updated
            click.echo(f"\nIndexed: {total_new} new, {total_updated} updated")
            click.echo(f"  Claude Code: {new_count} new, {updated_count} updated")
            click.echo(f"  Claude.ai: {ai_new} new, {ai_updated} updated")
            click.echo(f"  Handoffs: {handoff_new} new, {handoff_updated} updated, {handoff_skipped} unchanged, {handoff_extracted} extracted")
            click.echo(f"  Cloud sessions: {cloud_new} new, {cloud_updated} updated")
            click.echo(f"  Local markdown: {local_md_new} new, {local_md_updated} updated, {local_md_skipped} unchanged")
            click.echo(f"  Bon: {bon_new} new, {bon_updated} updated, {bon_skipped} unchanged")
            click.echo(f"  Knowledge: {knowledge_new} new, {knowledge_updated} updated, {knowledge_skipped} unchanged")
            click.echo(f"  Amp: {amp_new} new, {amp_updated} updated, {amp_skipped} unchanged")
