"""Command-line interface for garde-manger (conversation memory system)."""

# CLI entry point
import os
os.environ.setdefault('RUST_LOG', 'error,sqlite3Parser=off')

import json
from pathlib import Path
import click

from .config import load_config, get_memory_dir
from .glossary import load_glossary
from .database import get_database
from .adapters.claude_code import discover_claude_code, ClaudeCodeSource
from .adapters.claude_ai import discover_claude_ai, ClaudeAISource
from .adapters.cloud_sessions import discover_cloud_sessions, CloudSessionSource
from .adapters.handoffs import discover_handoffs, HandoffSource
from .adapters.local_md import discover_local_md, LocalMdSource
from .adapters.bon import discover_bon, BonSource
from .adapters.knowledge import discover_knowledge, KnowledgeSource
from .adapters.amp import discover_amp, AmpSource


@click.group()
@click.version_option(package_name="garde-manger")
@click.pass_context
def main(ctx):
    """Conversation Memory System - persistent, searchable memory across Claude sessions."""
    ctx.ensure_object(dict)
    ctx.obj['config'] = load_config()
    ctx.obj['glossary'] = load_glossary()


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

        if scan_handoffs:
            click.echo(f"\nScanning handoff files...")
            for source in discover_handoffs(config):
                exists = db.source_exists(source.source_id)

                if dry_run:
                    status = "exists" if exists else "new"
                    click.echo(f"  [{status}] {source.source_id}: {source.title[:60]}...")
                    if not exists:
                        handoff_new += 1
                    continue

                # Store source metadata
                db.upsert_source(
                    source_id=source.source_id,
                    source_type='handoff',
                    title=source.title,
                    path=str(source.path),
                    created_at=source.date,
                    updated_at=source.date,
                    project_path=source.project_path,
                )

                # Use full text as summary (handoffs are already distilled)
                # raw_text same as summary_text for handoffs (they're already small)
                full_text = source.full_text()
                db.upsert_summary(
                    source_id=source.source_id,
                    summary_text=full_text,
                    has_presummary=True,
                    raw_text=full_text,
                )
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
            click.echo(f"  Handoffs: {handoff_new} new, {handoff_updated} updated")
            click.echo(f"  Cloud sessions: {cloud_new} new, {cloud_updated} updated")
            click.echo(f"  Local markdown: {local_md_new} new, {local_md_updated} updated, {local_md_skipped} unchanged")
            click.echo(f"  Bon: {bon_new} new, {bon_updated} updated, {bon_skipped} unchanged")
            click.echo(f"  Knowledge: {knowledge_new} new, {knowledge_updated} updated, {knowledge_skipped} unchanged")
            click.echo(f"  Amp: {amp_new} new, {amp_updated} updated, {amp_skipped} unchanged")


def _extract_compacted_summary(content: str) -> str | None:
    """
    Extract summary from Claude Code's episodic compaction.

    Compacted conversations have <summary>...</summary> tags containing
    the actual summary, buried in the compaction prompt.
    """
    import re
    match = re.search(r'<summary>\s*(.*?)\s*</summary>', content, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


def _is_compacted_conversation(first_message: str) -> bool:
    """Check if conversation starts with compaction prompt."""
    return first_message.startswith('Context: This summary will be shown')


def _create_basic_summary(source: ClaudeCodeSource) -> str:
    """
    Create a basic summary from title and first messages.

    Uses presummary (type:summary entry) when available.
    Handles compacted conversations by extracting <summary> tags.
    """
    # Use presummary if available (from type:summary entry)
    if source.summary_text:
        return source.summary_text

    # Check for compacted conversation
    first_user_msg = None
    for msg in source.messages:
        if msg.role == 'user' and not msg.is_tool_result:
            content = msg.content
            if isinstance(content, str) and content.strip():
                first_user_msg = content.strip()
                break

    # If compacted, try to extract the real summary
    if first_user_msg and _is_compacted_conversation(first_user_msg):
        # Look for summary in any message
        for msg in source.messages:
            content = msg.content if isinstance(msg.content, str) else ''
            extracted = _extract_compacted_summary(content)
            if extracted:
                return extracted
        # Fallback: use embedded content after "User:" marker
        if 'User:' in first_user_msg:
            # Extract first embedded user message
            parts = first_user_msg.split('User:', 1)
            if len(parts) > 1:
                embedded = parts[1].split('Agent:', 1)[0].strip()
                if embedded and len(embedded) > 20:
                    return embedded[:500]

    # Normal conversation: use title + first messages
    parts = [source.title]

    user_messages = []
    for msg in source.messages:
        if msg.role == 'user' and not msg.is_tool_result:
            content = msg.content
            if isinstance(content, str) and content.strip():
                # Skip compaction prompts
                if not _is_compacted_conversation(content):
                    user_messages.append(content.strip())
            if len(user_messages) >= 3:
                break

    if user_messages:
        parts.append("\n\n".join(user_messages[:3]))

    return "\n\n".join(parts)


@main.command()
@click.pass_context
def status(ctx):
    """Show system status and statistics."""
    glossary = ctx.obj['glossary']

    click.echo(f"Memory dir: {get_memory_dir()}")
    click.echo(f"Glossary: {len(glossary.entities)} entities")

    db = get_database()
    with db:
        stats = db.get_stats()

    click.echo(f"\nDatabase:")
    click.echo(f"  Sources: {stats['total_sources']}")
    for stype, count in stats.get('by_type', {}).items():
        click.echo(f"    {stype}: {count}")
    click.echo(f"  Summaries indexed: {stats['summaries']}")

    # Entity stats
    if stats.get('resolved_entities') or stats.get('pending_entities'):
        click.echo(f"\nEntities:")
        click.echo(f"  Resolved: {stats.get('resolved_entities', 0)}")
        click.echo(f"  Pending: {stats.get('pending_entities', 0)}")

    # Check for stale sources
    already_stale = stats['by_status'].get('stale', 0)
    newly_stale = 0
    with db:
        # Only check sources not already marked stale
        sources_with_paths = db.get_sources_with_paths(include_stale=False)
    for source in sources_with_paths:
        # Skip virtual paths (claude_ai stores claude_ai:uuid)
        if source['source_type'] == 'claude_ai':
            continue
        if source['path'] and not Path(source['path']).exists():
            newly_stale += 1

    if already_stale or newly_stale:
        click.echo(f"\nStale sources:")
        if already_stale:
            click.echo(f"  Marked stale: {already_stale}")
        if newly_stale:
            click.echo(click.style(
                f"  Paths missing: {newly_stale} (run 'garde prune --dry-run' to see details)",
                fg='yellow'
            ))


@main.command()
@click.option('--dry-run', is_flag=True, help='Show what would be marked stale')
@click.option('--type', 'source_type', help='Only check specific source type')
@click.option('--yes', '-y', is_flag=True, help='Skip confirmation prompt')
@click.option('--delete', 'hard_delete', is_flag=True, help='Delete sources instead of marking stale (loses extractions)')
def prune(dry_run, source_type, yes, hard_delete):
    """Mark sources as stale when their paths no longer exist.

    By default, marks sources as 'stale' but preserves summaries and
    extractions so they remain searchable.

    Use --delete to permanently remove sources and all related data.

    Examples:
        garde prune --dry-run              # Preview what would be marked stale
        garde prune --dry-run --type local_md  # Only check local_md
        garde prune --yes                  # Mark stale without confirmation
        garde prune --delete --yes         # Hard delete (loses extractions)
    """
    db = get_database()
    with db:
        sources = db.get_sources_with_paths(source_type)

    if not sources:
        click.echo("No sources with filesystem paths found.")
        return

    click.echo(f"Checking {len(sources)} sources with filesystem paths...")

    # Group stale sources by type
    stale_by_type: dict[str, list[dict]] = {}
    for source in sources:
        # Skip virtual paths (claude_ai stores claude_ai:uuid)
        if source['source_type'] == 'claude_ai':
            continue

        if source['path'] and not Path(source['path']).exists():
            stype = source['source_type']
            if stype not in stale_by_type:
                stale_by_type[stype] = []
            stale_by_type[stype].append(source)

    if not stale_by_type:
        click.echo(click.style("✓ All source paths are valid.", fg='green'))
        return

    # Report findings
    total_stale = sum(len(v) for v in stale_by_type.values())
    click.echo(f"\nStale sources (path no longer exists):")

    for stype, sources_list in sorted(stale_by_type.items()):
        click.echo(f"  {stype}: {len(sources_list)}")
        # Show first few examples
        for source in sources_list[:3]:
            title = source['title'][:50] if source['title'] else source['id']
            click.echo(f"    - {title}")
        if len(sources_list) > 3:
            click.echo(f"    ... and {len(sources_list) - 3} more")

    click.echo(f"\nTotal: {total_stale} stale sources")

    action = "delete" if hard_delete else "mark as stale"
    if dry_run:
        click.echo(f"\nRun without --dry-run to {action}, or add --yes to skip confirmation.")
        return

    # Confirm action
    if not yes:
        msg = f"\n{'Delete' if hard_delete else 'Mark'} {total_stale} stale sources?"
        if hard_delete:
            msg += " (This will also delete summaries and extractions!)"
        if not click.confirm(msg):
            click.echo("Aborted.")
            return

    # Process stale sources
    processed = 0
    with db:
        all_stale_ids = [s['id'] for sources_list in stale_by_type.values() for s in sources_list]
        if hard_delete:
            for source_id in all_stale_ids:
                if db.delete_source(source_id):
                    processed += 1
        else:
            processed = db.mark_stale_batch(all_stale_ids)

    verb = "Deleted" if hard_delete else "Marked stale"
    click.echo(click.style(f"\n✓ {verb} {processed} sources.", fg='green'))


@main.command('list')
@click.option('--type', 'source_type', help='Filter by source type')
@click.option('--limit', '-n', default=20, help='Number of results')
@click.pass_context
def list_sources(ctx, source_type, limit):
    """List indexed sources.

    Shows sources in the database, sorted by most recent.

    Examples:
        garde list                    # Recent 20 sources
        garde list --type handoff     # Only handoffs
        garde list -n 50              # More results
    """
    db = get_database()
    with db:
        conn = db.connect()

        sql = """
            SELECT id, source_type, title, updated_at
            FROM sources
            WHERE 1=1
        """
        params = []

        if source_type:
            sql += " AND source_type = ?"
            params.append(source_type)

        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()

    if not rows:
        click.echo("No sources found.")
        return

    click.echo(f"\n{len(rows)} sources:\n")
    for row in rows:
        title = row['title'][:55] if row['title'] else '(untitled)'
        date_str = _format_date(row['updated_at'])
        click.echo(f"  [{row['source_type']}] {title}")
        click.echo(f"    {date_str} · {row['id']}")


@main.command()
@click.argument('query', nargs=-1, required=True)
@click.option('--type', 'source_type', help='Filter by source type')
@click.option('--project', 'project_path', help='Filter by project path (use "." for current directory)')
@click.option('--limit', '-n', default=5, help='Number of results')
@click.option('--recency', 'recency_half_life', type=int, default=None,
              help='Apply recency weighting with half-life in days (e.g., 90 = 90-day-old results get 0.5x weight)')
@click.pass_context
def search(ctx, query, source_type, project_path, limit, recency_half_life):
    """Search across indexed conversations.

    Supports FTS5 operators: OR, AND, NOT. Quote phrases with double quotes.

    Examples:
        garde search OAuth
        garde search "OAuth refresh"
        garde search OAuth OR JWT
        garde search OAuth NOT deprecated
        garde search OAuth --project .          # current project only
        garde search OAuth --project ~/Repos/x  # specific project
        garde search OAuth --recency 90         # boost recent results (90-day half-life)
    """
    import subprocess
    glossary = ctx.obj['glossary']

    # Join multiple arguments (allows: garde search term1 OR term2)
    query = ' '.join(query)

    # Auto-quote hyphenated terms that aren't already quoted
    # FTS5 interprets hyphens as MINUS operator
    query = _auto_quote_hyphenated(query)

    # Expand query with glossary aliases
    expanded = _expand_query(query, glossary)
    if expanded != query:
        click.echo(f"Expanded: {query} → {expanded}")

    # Add wildcard suffix for better recall (unless glossary expanded it)
    if expanded == query:
        expanded = _add_wildcard_suffix(query)
        if expanded != query:
            click.echo(f"Search: {expanded}")

    # Resolve project path
    resolved_project = None
    if project_path:
        if project_path == '.':
            # Use current git repo root
            try:
                result = subprocess.run(
                    ['git', 'rev-parse', '--show-toplevel'],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    resolved_project = result.stdout.strip()
                else:
                    click.echo("Error: Not in a git repository. Use explicit path instead of '.'")
                    return
            except (subprocess.TimeoutExpired, FileNotFoundError):
                click.echo("Error: Could not determine git root")
                return
        else:
            # Expand ~ and resolve path
            from pathlib import Path
            resolved_project = str(Path(project_path).expanduser().resolve())

        # Convert to encoded format used in database (e.g., /Users/foo/bar -> -Users-foo-bar)
        resolved_project = resolved_project.replace('/', '-').lstrip('-')

    db = get_database()
    try:
        with db:
            results = db.search(expanded, source_type=source_type, project_path=resolved_project, limit=limit, recency_half_life=recency_half_life)
    except Exception as e:
        if 'no such column' in str(e):
            # FTS5 interprets hyphens as MINUS operator (shouldn't happen with auto-quote, but keep as fallback)
            import re
            hyphenated = re.findall(r'\b\w+-\w+\b', expanded)
            if hyphenated:
                suggested = expanded
                for term in hyphenated:
                    suggested = suggested.replace(term, f'"{term}"')
                click.echo(f"Error: FTS5 interprets hyphens as operators.")
                click.echo(f"Try quoting hyphenated terms: garde search '{suggested}'")
                return
        raise

    if not results:
        click.echo("No results found.")
        return

    click.echo(f"\n{len(results)} results:\n")
    for i, r in enumerate(results, 1):
        # Format date as relative or absolute
        date_str = _format_date(r.created_at)

        click.echo(f"{i}. [{r.source_type}] {r.title[:60]}")

        # Check for hybrid extraction (the "unfolding label")
        extraction = db.get_extraction(r.source_id)
        if extraction and extraction.get('summary'):
            # Show extraction summary (more useful than raw text)
            click.echo(f"   {extraction['summary']}")

            # Show builds/learnings counts
            builds = extraction.get('builds') or []
            learnings = extraction.get('learnings') or []
            if builds or learnings:
                parts = []
                if builds:
                    parts.append(f"{len(builds)} builds")
                if learnings:
                    parts.append(f"{len(learnings)} learnings")
                click.echo(f"   [{', '.join(parts)}]")
        else:
            # Fallback to raw summary snippet
            snippet = r.summary_text[:200].replace('\n', ' ')
            if len(r.summary_text) > 200:
                snippet += "..."
            click.echo(f"   {snippet}")

        click.echo(f"   {date_str} · ID: {r.source_id}")
        click.echo()


def _format_date(date_str: str) -> str:
    """Format date as relative (if recent) or absolute."""
    from datetime import datetime, timezone

    try:
        # Parse ISO format, handle various formats
        if 'T' in date_str:
            if '+' in date_str or date_str.endswith('Z'):
                dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            else:
                dt = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        diff = now - dt

        if diff.days == 0:
            hours = diff.seconds // 3600
            if hours == 0:
                mins = diff.seconds // 60
                return f"{mins}m ago" if mins > 0 else "just now"
            return f"{hours}h ago"
        elif diff.days == 1:
            return "yesterday"
        elif diff.days < 7:
            return f"{diff.days}d ago"
        elif diff.days < 30:
            weeks = diff.days // 7
            return f"{weeks}w ago"
        else:
            return dt.strftime("%b %d")
    except (ValueError, TypeError):
        return date_str[:10] if date_str else ""


def _auto_quote_hyphenated(query: str) -> str:
    """Auto-quote hyphenated terms to prevent FTS5 interpreting hyphens as MINUS.

    Leaves already-quoted terms alone.
    Example: 'claude-memory foo' -> '"claude-memory" foo'
    """
    import re

    # Find hyphenated terms that aren't already inside quotes
    # This is a simplified approach - find all hyphenated words and quote them
    # if they're not already quoted
    result = []
    in_quotes = False
    i = 0

    while i < len(query):
        if query[i] == '"':
            # Toggle quote state and include the quote
            in_quotes = not in_quotes
            result.append(query[i])
            i += 1
        elif not in_quotes:
            # Look for hyphenated word
            match = re.match(r'\b(\w+(?:-\w+)+)\b', query[i:])
            if match:
                # Found hyphenated term outside quotes - wrap it
                result.append(f'"{match.group(1)}"')
                i += match.end()
            else:
                result.append(query[i])
                i += 1
        else:
            result.append(query[i])
            i += 1

    return ''.join(result)


def _expand_query(query: str, glossary) -> str:
    """Expand query terms using glossary aliases."""
    # Check if any glossary entity matches
    resolved = glossary.resolve(query)
    if resolved:
        entity = glossary.get(resolved)
        if entity:
            # Build OR query with canonical name and aliases
            terms = [entity.get('name', query)]
            terms.extend(entity.get('aliases', [])[:3])
            return ' OR '.join(f'"{t}"' for t in terms)
    return query


def _add_wildcard_suffix(query: str) -> str:
    """Add wildcard suffix to simple search terms for better recall.

    FTS5 requires exact token matches. Adding * makes 'Reckitt' match 'Reckitts'.
    Only applies to simple terms (no operators, no quotes, no existing wildcards).

    Examples:
        'Reckitt' -> 'Reckitt*'
        'OAuth' -> 'OAuth*'
        'Reckitt*' -> 'Reckitt*' (unchanged)
        '"OAuth refresh"' -> '"OAuth refresh"' (unchanged)
        'OAuth OR JWT' -> 'OAuth* OR JWT*'
        'OAuth NOT old' -> 'OAuth* NOT old*'
    """
    import re

    # FTS5 operators that should not be wildcarded
    operators = {'AND', 'OR', 'NOT', 'NEAR'}

    tokens = []
    # Split on whitespace while preserving quoted strings
    # Pattern: quoted strings OR non-whitespace sequences
    pattern = r'"[^"]*"|\S+'

    for match in re.finditer(pattern, query):
        token = match.group()

        # Skip if:
        # - Already quoted (phrase search)
        # - Already has wildcard
        # - Is an FTS5 operator
        # - Contains column prefix (e.g., title:foo)
        if (token.startswith('"') or
            token.endswith('*') or
            token.upper() in operators or
            ':' in token):
            tokens.append(token)
        else:
            # Add wildcard suffix
            tokens.append(token + '*')

    return ' '.join(tokens)


@main.command()
@click.argument('query', nargs=-1, required=True)
@click.option('--limit', '-n', default=20, help='Number of results')
@click.pass_context
def files(ctx, query, limit):
    """Search for conversations by file path.

    Find conversations that touched specific files.

    Examples:
        garde files server.py           # Files ending in server.py
        garde files cli                  # Any file with 'cli' in path
        garde files "mcp-google"         # Quote for exact match
        garde files SKILL.md             # Find SKILL.md files
    """
    db = get_database()

    # Join multiple arguments
    query = ' '.join(query)

    with db:
        results = db.search_files(query, limit=limit)

    if not results:
        click.echo("No results found.")
        click.echo("\nNote: File search requires backfill. Run: garde backfill-files")
        return

    click.echo(f"\n{len(results)} results:\n")

    # Group by source for cleaner output
    from collections import defaultdict
    by_source = defaultdict(list)
    source_meta = {}
    for r in results:
        by_source[r['source_id']].append(r['file_path'])
        source_meta[r['source_id']] = r

    for source_id, files in by_source.items():
        meta = source_meta[source_id]
        date_str = _format_date(meta['created_at']) if meta['created_at'] else ''
        title = meta['title'][:50] if meta['title'] else '(untitled)'

        click.echo(f"[{meta['source_type']}] {title}")
        click.echo(f"  {date_str} · {source_id}")
        for f in files[:3]:  # Show up to 3 matching files
            click.echo(f"  → {f}")
        if len(files) > 3:
            click.echo(f"  → ... and {len(files) - 3} more files")
        click.echo()


@main.command('backfill-files')
@click.option('--dry-run', is_flag=True, help='Show what would be done without doing it')
@click.pass_context
def backfill_files(ctx, dry_run):
    """Populate file_mentions from existing extractions.

    Extracts files_touched from extraction metadata and adds to searchable index.
    """
    db = get_database()

    with db:
        conn = db.connect()

        # Get sources with extractions that have files_touched
        rows = conn.execute("""
            SELECT s.id, s.metadata
            FROM sources s
            WHERE s.metadata IS NOT NULL
              AND json_extract(s.metadata, '$.files_touched') IS NOT NULL
        """).fetchall()

        if not rows:
            click.echo("No sources with files_touched metadata found.")
            return

        total_files = 0
        sources_processed = 0

        for row in rows:
            source_id = row['id']
            try:
                metadata = json.loads(row['metadata']) if row['metadata'] else {}
                files = metadata.get('files_touched', [])
                if files:
                    if dry_run:
                        click.echo(f"{source_id}: {len(files)} files")
                    else:
                        added = db.add_file_mentions_batch(source_id, files)
                        total_files += added
                    sources_processed += 1
            except (json.JSONDecodeError, TypeError):
                continue

        if dry_run:
            click.echo(f"\nDry run: would process {sources_processed} sources")
        else:
            click.echo(f"Added files from {sources_processed} sources ({total_files} file mentions)")


@main.command()
@click.argument('source_id')
@click.option('--full', is_flag=True, help='Show full content (not just summary)')
@click.option('--outline', is_flag=True, help='Show message index with snippets')
@click.option('--turn', type=int, help='Show specific turn in full (1-indexed)')
@click.pass_context
def drill(ctx, source_id, full, outline, turn):
    """Load and display a source's content.

    Progressive disclosure:
      drill ID           → metadata + extraction summary
      drill ID --outline → numbered message index with snippets
      drill ID --turn 5  → specific turn in full (no truncation)
      drill ID --full    → all turns (truncated to 2000 chars each)
    """
    db = get_database()
    with db:
        source = db.get_source(source_id)

    if not source:
        click.echo(f"Source not found: {source_id}")
        return

    click.echo(f"Title: {source['title']}")
    click.echo(f"Type: {source['source_type']}")
    click.echo(f"Created: {source['created_at']}")
    click.echo(f"Path: {source['path']}")

    # Show extraction if available (the "unfolding label")
    with db:
        extraction = db.get_extraction(source_id)

    if extraction and extraction.get('summary'):
        click.echo(f"\n--- Extraction ---")
        click.echo(f"Summary: {extraction['summary']}")

        if extraction.get('arc'):
            arc = extraction['arc']
            click.echo(f"\nArc:")
            click.echo(f"  Started: {arc.get('started_with', 'N/A')}")
            if arc.get('key_turns'):
                click.echo(f"  Turns: {', '.join(str(t) for t in arc['key_turns'][:3])}")
            click.echo(f"  Ended: {arc.get('ended_at', 'N/A')}")

        if extraction.get('builds'):
            click.echo(f"\nBuilds ({len(extraction['builds'])}):")
            for b in extraction['builds'][:5]:
                what = b.get('what', str(b)) if isinstance(b, dict) else str(b)
                click.echo(f"  • {what}")
            if len(extraction['builds']) > 5:
                click.echo(f"  ... and {len(extraction['builds']) - 5} more")

        if extraction.get('learnings'):
            click.echo(f"\nLearnings ({len(extraction['learnings'])}):")
            for l in extraction['learnings'][:5]:
                if isinstance(l, dict):
                    insight = l.get('insight', str(l))
                    why = l.get('why_it_matters', '')
                    click.echo(f"  • {insight}")
                    if why:
                        click.echo(f"    → {why}")
                else:
                    click.echo(f"  • {l}")
            if len(extraction['learnings']) > 5:
                click.echo(f"  ... and {len(extraction['learnings']) - 5} more")

        if extraction.get('patterns'):
            click.echo(f"\nPatterns: {', '.join(str(p) for p in extraction['patterns'][:5])}")

        if extraction.get('open_threads'):
            click.echo(f"\nOpen threads: {len(extraction['open_threads'])}")

        click.echo(f"\n[Extracted with {extraction.get('model_used', 'unknown')} at {(extraction.get('extracted_at') or 'unknown')[:10]}]")
    elif not full:
        # Fallback to raw summary
        with db:
            row = db.connect().execute(
                "SELECT summary_text FROM summaries WHERE source_id = ?",
                (source_id,)
            ).fetchone()
            if row and row[0]:
                click.echo(f"\nSummary:\n{row[0]}")
            else:
                click.echo("\n(No summary indexed)")

    # Handle content display modes: --outline, --turn, --full
    if (full or outline or turn) and source['path']:
        from pathlib import Path
        source_type = source['source_type']
        stored_path = source['path']

        # Resolve virtual paths to actual files
        if source_type == 'claude_ai' and stored_path.startswith('claude_ai:'):
            uuid = stored_path.split(':', 1)[1]
            config = ctx.obj or load_config()
            base_path = config.get('sources', {}).get('claude_ai', {}).get(
                'path', '~/.claude/claude-ai/cache/conversations'
            )
            path = Path(base_path).expanduser() / f"{uuid}.json"
        else:
            path = Path(stored_path)

        if not path.exists():
            click.echo(f"File not found: {path}")
            return

        # Handoffs and local markdown are already human-readable - no progressive disclosure needed
        if source_type in ('handoff', 'local_md'):
            click.echo(f"\n{'='*60}\n")
            click.echo(path.read_text())
            return

        # Load messages based on source type
        messages = []  # List of (role, content) tuples
        if source_type == 'claude_ai':
            from .adapters.claude_ai import ClaudeAISource
            conv = ClaudeAISource.from_file(path)
            for msg in conv.messages:
                sender = msg.get('sender', 'unknown').upper()
                text = msg.get('text', '')
                if not text:
                    for block in msg.get('content', []):
                        if isinstance(block, dict) and block.get('type') == 'text':
                            text = block.get('text', '')
                            break
                if text:
                    messages.append((sender, text))

        elif source_type == 'cloud_session':
            from .adapters.cloud_sessions import CloudSessionSource
            conv = CloudSessionSource.from_file(path)
            for msg in conv.messages:
                role = msg.get('role', 'unknown').upper()
                content = msg.get('content', '')
                if isinstance(content, str) and content:
                    messages.append((role, content))

        elif source_type == 'claude_code':
            from .adapters.claude_code import ClaudeCodeSource
            conv = ClaudeCodeSource.from_file(path)
            for msg in conv.messages:
                if msg.is_tool_result:
                    continue
                role = "USER" if msg.role == 'user' else "ASSISTANT"
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                if content:
                    messages.append((role, content))

        else:
            click.echo(f"Unknown source type: {source_type}")
            return

        # Display based on mode
        if outline:
            # Show numbered index with snippets
            click.echo(f"\n--- Outline ({len(messages)} turns) ---\n")
            for i, (role, content) in enumerate(messages, 1):
                snippet = content[:100].replace('\n', ' ')
                if len(content) > 100:
                    snippet += '...'
                click.echo(f"  {i:3d}. [{role}] {snippet}")
            click.echo(f"\nUse --turn N to see a specific turn in full")

        elif turn:
            # Show specific turn in full (1-indexed)
            if turn < 1 or turn > len(messages):
                click.echo(f"Turn {turn} out of range (1-{len(messages)})")
                return
            role, content = messages[turn - 1]
            click.echo(f"\n--- Turn {turn} of {len(messages)} ---\n")
            click.echo(f"[{role}]\n{content}")

        elif full:
            # Show all turns (truncated)
            click.echo(f"\n{'='*60}\n")
            for i, (role, content) in enumerate(messages, 1):
                click.echo(f"\n[{role}] (turn {i})\n{content[:2000]}")
                if len(content) > 2000:
                    click.echo(f"... (showing 2000 of {len(content)} chars)")


@main.command()
@click.option('--days', default=7, help='Number of days to look back')
@click.option('--all', 'show_all', is_flag=True, help='Show all sources, not just current project')
@click.option('--type', 'source_type', help='Filter by source type')
@click.option('--by-project', 'group_by_project', is_flag=True, help='Group by project instead of by day')
@click.pass_context
def recent(ctx, days, show_all, source_type, group_by_project):
    """Show recent activity, grouped by day or project.

    By default, shows sources from the current project (if in a git repo).
    Use --all to see everything regardless of location.
    Use --by-project for a project-grouped summary (useful for daily recaps).

    Examples:
        garde recent              # Current project's recent activity
        garde recent --all        # All recent activity
        garde recent --all --by-project  # Summary grouped by project
        garde recent --days 14    # Last 2 weeks
        garde recent --type handoff  # Only handoffs
    """
    from datetime import datetime, timedelta, timezone
    from collections import defaultdict
    import subprocess

    db = get_database()

    # Detect current project if not --all
    project_filter = None
    if not show_all:
        try:
            result = subprocess.run(
                ['git', 'rev-parse', '--show-toplevel'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                repo_path = result.stdout.strip()
                # Convert /Users/jane/Repos/foo to -Users-jane-Repos-foo
                project_filter = repo_path.replace('/', '-').lstrip('-')
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    # Calculate cutoff date
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_str = cutoff.isoformat()

    with db:
        conn = db.connect()

        # Build query
        sql = """
            SELECT s.id, s.source_type, s.title, s.updated_at, s.project_path
            FROM sources s
            WHERE s.updated_at >= ?
        """
        params = [cutoff_str]

        if source_type:
            sql += " AND s.source_type = ?"
            params.append(source_type)

        if project_filter:
            # Match project_path for claude_code, or title/id for handoffs
            # project_filter is like "Users-jane-Repos-project"
            # repo_name is the folder name: "claude-memory"
            if '-Repos-' in project_filter:
                repo_name = project_filter.split('-Repos-')[-1]
            else:
                # For non-Repos paths, take last segment (e.g., "-Users-jane-foo" → "foo")
                repo_name = project_filter.rsplit('-', 1)[-1]
            sql += " AND (s.project_path LIKE ? OR (s.source_type = 'handoff' AND (s.title LIKE ? OR s.id LIKE ?)))"
            params.append(f"%{project_filter}%")
            params.append(f"%{repo_name}%")
            params.append(f"%{repo_name}%")

        sql += " ORDER BY s.updated_at DESC LIMIT 100"

        rows = conn.execute(sql, params).fetchall()

    if not rows:
        if project_filter:
            click.echo(f"No recent activity in current project (last {days} days).")
            click.echo("Use --all to see all sources.")
        else:
            click.echo(f"No recent activity (last {days} days).")
        return

    # Helper to extract project name from project_path
    def get_project_name(row):
        path = row['project_path'] or '' if 'project_path' in row.keys() else ''
        # project_path looks like "-Users-jane-Repos-project" or similar
        if '-Repos-' in path:
            return path.split('-Repos-')[-1]
        elif path:
            # For non-Repos paths, take last segment
            return path.rsplit('-', 1)[-1] if '-' in path else path
        # Fallback: try to extract from source_id or title
        source_type = row['source_type'] if 'source_type' in row.keys() else ''
        if 'handoff' in source_type:
            # Handoffs have project in title usually
            title = row['title'] if 'title' in row.keys() else ''
            if title:
                return title.split()[0] if title else '(unknown)'
        return '(unknown)'

    # Batch prefetch extractions for rows that might need fallback titles
    # (Avoids N+1 queries in get_display_title)
    extraction_cache = {}
    rows_needing_extraction = [
        row['id'] for row in rows
        if not row['title'] or row['title'] == '(untitled)'
    ]
    if rows_needing_extraction:
        with db:
            conn = db.connect()
            placeholders = ','.join('?' * len(rows_needing_extraction))
            extractions = conn.execute(
                f"SELECT source_id, summary FROM extractions WHERE source_id IN ({placeholders})",
                rows_needing_extraction
            ).fetchall()
            for ext in extractions:
                if ext['summary']:
                    extraction_cache[ext['source_id']] = ext['summary'][:55] + '...'

    # Helper to get display title (with extraction fallback)
    def get_display_title(row):
        title = row['title'] if 'title' in row.keys() else None
        if title and title != '(untitled)':
            return title[:55]
        # Try extraction summary as fallback (already prefetched)
        source_id = row['id'] if 'id' in row.keys() else None
        if source_id and extraction_cache.get(source_id):
            return extraction_cache[source_id]
        return '(untitled)'

    if group_by_project:
        # Group by project
        by_project = defaultdict(list)
        for row in rows:
            project = get_project_name(row)
            by_project[project].append(row)

        click.echo(f"\n{len(rows)} sessions across {len(by_project)} projects (last {days} days):\n")

        # Sort projects by session count (most active first)
        for project in sorted(by_project.keys(), key=lambda p: len(by_project[p]), reverse=True):
            sessions = by_project[project]
            count = len(sessions)
            session_word = "session" if count == 1 else "sessions"
            click.echo(f"{project} ({count} {session_word})")

            # Show up to 3 session titles as preview
            for row in sessions[:3]:
                title = get_display_title(row)
                click.echo(f"  · {title}")
            if len(sessions) > 3:
                click.echo(f"  · ... and {len(sessions) - 3} more")
            click.echo()
    else:
        # Group by day (original behavior)
        by_day = defaultdict(list)
        for row in rows:
            updated = row['updated_at']
            if updated:
                # Parse and extract date part
                try:
                    if 'T' in updated:
                        dt = datetime.fromisoformat(updated.replace('Z', '+00:00'))
                    else:
                        dt = datetime.fromisoformat(updated)
                    day_key = dt.strftime('%Y-%m-%d')
                    by_day[day_key].append(row)
                except ValueError:
                    by_day['unknown'].append(row)
            else:
                by_day['unknown'].append(row)

        # Format output
        scope = "current project" if project_filter else "all sources"
        click.echo(f"\n{len(rows)} sources ({scope}, last {days} days):\n")

        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime('%Y-%m-%d')

        for day in sorted(by_day.keys(), reverse=True):
            # Format day header
            if day == today:
                day_label = "Today"
            elif day == yesterday:
                day_label = "Yesterday"
            elif day == 'unknown':
                day_label = "Unknown date"
            else:
                try:
                    dt = datetime.strptime(day, '%Y-%m-%d')
                    day_label = dt.strftime('%b %d')
                except ValueError:
                    day_label = day

            click.echo(f"{day_label}:")

            for row in by_day[day]:
                title = get_display_title(row)
                stype = row['source_type']
                click.echo(f"  [{stype}] {title}")

            click.echo()


@main.command()
@click.argument('source_id')
@click.option('--dry-run', is_flag=True, help='Show what would be extracted without storing')
@click.pass_context
def extract(ctx, source_id, dry_run):
    """Extract entities from a source using LLM.

    Uses claude -p (Max subscription billing).
    """
    from .extraction import extract_from_source, get_source_content

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
@click.pass_context
def resolve(ctx):
    """Interactive entity resolution."""
    db = get_database()
    with db:
        pending = db.get_pending_entities(limit=20)

    if not pending:
        click.echo("No pending entities to resolve.")
        return

    click.echo(f"\n{len(pending)} entities pending resolution:\n")

    for p in pending:
        source_title = p.get('source_title', '(unknown)')[:40]
        suggested = f" → {p['suggested_entity']}" if p['suggested_entity'] else ""
        click.echo(f"  [{p['id']}] {p['mention_text']}{suggested}")
        click.echo(f"      confidence: {p['confidence']:.1f}, from: {source_title}")

    click.echo("\n(Interactive resolution UI: not yet implemented)")
    click.echo("Use: garde resolve-one <id> --as <entity> to resolve manually")


@main.command('resolve-one')
@click.argument('pending_id', type=int)
@click.option('--as', 'entity_name', required=True, help='Entity to resolve as')
@click.option('--reject', is_flag=True, help='Reject instead of resolve')
@click.pass_context
def resolve_one(ctx, pending_id, entity_name, reject):
    """Resolve a single pending entity.

    If the entity doesn't exist in glossary, it will be added to auto_mappings
    for later review with 'garde digest'.
    """
    from .glossary import save_glossary

    glossary = ctx.obj['glossary']

    db = get_database()
    with db:
        if reject:
            db.resolve_pending_entity(pending_id, None, status='rejected')
            click.echo(f"Rejected pending entity {pending_id}")
        else:
            # Get the pending entity to know its mention text
            pending = db.connect().execute(
                "SELECT mention_text FROM pending_entities WHERE id = ?",
                (pending_id,)
            ).fetchone()

            if not pending:
                click.echo(f"Pending entity {pending_id} not found")
                return

            mention = pending[0]

            # Check if entity exists in glossary
            resolved = glossary.resolve(entity_name)
            if resolved:
                # Existing entity - just link the mention as an alias
                if mention.lower() != entity_name.lower():
                    glossary.add_auto_mapping(mention, resolved)
                    save_glossary(glossary)
                    click.echo(f"Added '{mention}' as alias for {resolved}")
            else:
                # New entity - add to auto_mappings for review
                glossary.add_auto_mapping(mention, entity_name)
                save_glossary(glossary)
                click.echo(f"Added '{mention}' → '{entity_name}' to auto_mappings")
                click.echo("(Use 'garde digest' to review and graduate to full entity)")
                resolved = entity_name

            db.resolve_pending_entity(pending_id, resolved, status='resolved')
            click.echo(f"Resolved: {mention} → {resolved}")


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
    from .extraction import extract_from_source
    from .llm import extract_hybrid, MODEL

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
    from .llm import extract_hybrid, MODEL
    from .adapters.claude_code import ClaudeCodeSource

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
                click.echo(f"  ✓ {builds_count} builds, {learnings_count} learnings")
                processed += 1

            except Exception as e:
                click.echo(f"  ✗ Error: {e}")
                failed += 1

        click.echo(f"\nBackfill complete: {processed} processed, {failed} failed")


def _flatten_extraction_for_fts(extraction: dict) -> str:
    """Flatten extraction fields into searchable text.

    Combines summary + learnings + builds + friction into one searchable string.
    """
    import json
    parts = []

    # Summary
    if extraction.get('summary'):
        parts.append(extraction['summary'])

    # Learnings
    learnings = extraction.get('learnings') or []
    if isinstance(learnings, str):
        learnings = json.loads(learnings)
    for l in learnings:
        if isinstance(l, dict):
            if l.get('insight'):
                parts.append(f"Learning: {l['insight']}")
            if l.get('why_it_matters'):
                parts.append(l['why_it_matters'])
        else:
            parts.append(f"Learning: {l}")

    # Builds
    builds = extraction.get('builds') or []
    if isinstance(builds, str):
        builds = json.loads(builds)
    for b in builds:
        if isinstance(b, dict):
            if b.get('what'):
                parts.append(f"Built: {b['what']}")
            if b.get('outcome'):
                parts.append(b['outcome'])
        else:
            parts.append(f"Built: {b}")

    # Friction
    friction = extraction.get('friction') or []
    if isinstance(friction, str):
        friction = json.loads(friction)
    for f in friction:
        if isinstance(f, dict):
            if f.get('problem'):
                parts.append(f"Friction: {f['problem']}")
        else:
            parts.append(f"Friction: {f}")

    return "\n".join(parts)


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
    # Note: summaries_fts is STANDALONE mode, so use regular DELETE (not the special
    # INSERT ... VALUES('delete', ...) syntax which is only for contentless/external content)
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

    click.echo(f"✅ FTS index rebuilt with {count} entries (including raw_text).")


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
        click.echo(f"\n⚠️  Orphaned FTS entries (no summary): {len(orphaned)}")
        for row in orphaned[:5]:
            click.echo(f"  - {row[0]}")
        if len(orphaned) > 5:
            click.echo(f"  ... and {len(orphaned) - 5} more")

    if missing:
        click.echo(f"\n⚠️  Missing FTS entries (have summary): {len(missing)}")
        for row in missing[:5]:
            click.echo(f"  - {row[0]}")
        if len(missing) > 5:
            click.echo(f"  ... and {len(missing) - 5} more")

    if not orphaned and not missing and summaries_count == fts_count:
        click.echo("\n✅ FTS index is in sync with summaries.")
    else:
        click.echo("\n❌ FTS index is out of sync. Run 'uv run garde rebuild-fts' to fix.")


@main.command('populate-raw-text')
@click.option('--batch-size', default=50, help="Number of sources to process per batch (syncs after each)")
@click.option('--limit', default=0, help="Max sources to process (0 = all)")
@click.pass_context
def populate_raw_text(ctx, batch_size, limit):
    """Populate raw_text for summaries missing it.

    Faster than full scan - only updates summaries without raw_text,
    loading source content on demand.
    """
    from pathlib import Path

    db = get_database()
    conn = db.connect()

    # Find summaries missing raw_text
    # Order by source type to process working types first (claude_code, etc.)
    # before hitting types that need special handling (local_md)
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
        path = row[3]

        try:
            # Load source based on type using from_file classmethod
            raw_text = None
            p = Path(path) if path else None

            if source_type == 'claude_code' and p and p.exists():
                source = ClaudeCodeSource.from_file(p)
                raw_text = source.full_text()

            elif source_type == 'claude_ai' and path and path.startswith('claude_ai:'):
                # Resolve virtual claude_ai:{uuid} path to actual file
                uuid = path.split(':', 1)[1]
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

    click.echo(f"✅ Updated {updated} summaries with raw_text ({errors} errors)")


@main.command('extract-prompt')
@click.argument('source_id')
@click.pass_context
def extract_prompt(ctx, source_id):
    """Output the extraction prompt for a source.

    Outputs the hybrid extraction prompt with session content filled in.
    Designed for in-context extraction from Claude Code (Max subscription).

    Usage from /close:
        PROMPT=$(uv run garde extract-prompt claude_code:abc123)
        # Claude processes prompt, generates extraction JSON
        echo '$JSON' | uv run garde store-extraction claude_code:abc123
    """
    from .extraction import get_source_content
    from .llm import HYBRID_EXTRACTION_PROMPT

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


@main.command('glossary-check')
@click.pass_context
def glossary_check(ctx):
    """Audit glossary for common issues.

    Checks for:
    1. Key/name mismatch: Entity key differs from name and key not in aliases
       (search for 'csp' won't find 'CS&P' unless 'csp' is an alias)
    2. Duplicate aliases: Same alias used by multiple entities
    3. Orphaned auto_mappings: Mappings to non-existent entity keys
    """
    glossary = ctx.obj['glossary']
    issues_found = False

    # Check 1: Key differs from name and key not in aliases
    click.echo("Checking key/name alignment...")
    key_issues = []
    for key, entity in glossary.entities.items():
        name = entity.get('name', '')
        aliases = [a.lower() for a in entity.get('aliases', [])]

        # Key differs from name (case-insensitive)
        if key.lower() != name.lower():
            # Key not in aliases
            if key.lower() not in aliases:
                key_issues.append((key, name, aliases[:3]))

    if key_issues:
        issues_found = True
        click.echo(f"\n⚠ {len(key_issues)} entities where key ≠ name and key not in aliases:")
        for key, name, aliases in key_issues:
            alias_hint = f" (aliases: {', '.join(aliases)})" if aliases else ""
            click.echo(f"  {key} → \"{name}\"{alias_hint}")
            click.echo(f"    Fix: add \"{key}\" to aliases, or rename key to match name")
    else:
        click.echo("  ✓ All keys are either names or in aliases")

    # Check 2: Duplicate aliases across entities
    click.echo("\nChecking for duplicate aliases...")
    alias_to_entities: dict[str, list[str]] = {}

    for key, entity in glossary.entities.items():
        # Collect all terms this entity claims (dedupe within entity)
        terms = set()
        terms.add(key.lower())  # Key itself
        name = entity.get('name', '')
        if name:
            terms.add(name.lower())
        for alias in entity.get('aliases', []):
            terms.add(alias.lower())

        # Add each unique term to the index
        for term in terms:
            alias_to_entities.setdefault(term, []).append(key)

    duplicates = {alias: keys for alias, keys in alias_to_entities.items() if len(keys) > 1}

    if duplicates:
        issues_found = True
        click.echo(f"\n⚠ {len(duplicates)} aliases used by multiple entities:")
        for alias, keys in sorted(duplicates.items()):
            click.echo(f"  \"{alias}\" → {', '.join(keys)}")
    else:
        click.echo("  ✓ No duplicate aliases")

    # Check 3: Orphaned auto_mappings
    click.echo("\nChecking auto_mappings...")
    orphaned = []
    valid_mappings = []

    for alias, entity_key in glossary.auto_mappings.items():
        if entity_key not in glossary.entities:
            orphaned.append((alias, entity_key))
        else:
            valid_mappings.append((alias, entity_key))

    if orphaned:
        issues_found = True
        click.echo(f"\n⚠ {len(orphaned)} auto_mappings point to non-existent entities:")
        for alias, entity_key in orphaned:
            click.echo(f"  \"{alias}\" → {entity_key} (entity not found)")
            click.echo(f"    Fix: create entity '{entity_key}' or update mapping")

    if valid_mappings:
        click.echo(f"\n  {len(valid_mappings)} valid auto_mappings (could graduate to aliases):")
        for alias, entity_key in valid_mappings[:5]:
            entity_name = glossary.get_name(entity_key) or entity_key
            click.echo(f"    \"{alias}\" → {entity_name}")
        if len(valid_mappings) > 5:
            click.echo(f"    ... and {len(valid_mappings) - 5} more")
    else:
        click.echo("  ✓ No auto_mappings to review")

    # Summary
    click.echo("\n" + "=" * 40)
    if issues_found:
        click.echo("Issues found. Review above and update glossary.yaml")
    else:
        click.echo("✓ Glossary looks good!")


@main.command('store-extraction')
@click.argument('source_id')
@click.option('--model', default='claude-code-context', help='Model name for audit trail')
@click.pass_context
def store_extraction(ctx, source_id, model):
    """Store extraction results from stdin.

    Reads JSON from stdin and stores in the extractions table.
    FTS index is updated automatically.

    Expected JSON format:
    {
        "summary": "...",
        "arc": {"started_with": "...", "key_turns": [...], "ended_at": "..."},
        "builds": [{"what": "...", "details": "..."}],
        "learnings": [{"insight": "...", "why_it_matters": "...", "context": "..."}],
        "friction": [{"problem": "...", "resolution": "..."}],
        "patterns": ["..."],
        "open_threads": ["..."]
    }
    """
    import sys

    db = get_database()

    with db:
        source = db.get_source(source_id)
        if not source:
            click.echo(f"Source not found: {source_id}", err=True)
            raise SystemExit(1)

    # Read JSON from stdin
    try:
        input_text = sys.stdin.read()
        # Find JSON in input (may have preamble from Claude)
        start = input_text.find("{")
        end = input_text.rfind("}") + 1
        if start >= 0 and end > start:
            json_str = input_text[start:end]
            data = json.loads(json_str)
        else:
            click.echo("No JSON object found in input", err=True)
            raise SystemExit(1)
    except json.JSONDecodeError as e:
        click.echo(f"Invalid JSON: {e}", err=True)
        raise SystemExit(1)

    # Store extraction and sync full flattened text to FTS
    with db:
        db.upsert_extraction(
            source_id=source_id,
            summary=data.get('summary'),
            arc=data.get('arc'),
            builds=data.get('builds'),
            learnings=data.get('learnings'),
            friction=data.get('friction'),
            patterns=data.get('patterns'),
            open_threads=data.get('open_threads'),
            model_used=model,
        )

        # Flatten full extraction (builds, learnings, friction) into FTS
        # upsert_extraction only syncs the summary field — this adds the rest
        rich_text = _flatten_extraction_for_fts(data)
        if rich_text:
            db.upsert_summary(
                source_id=source_id,
                summary_text=rich_text,
                has_presummary=True,
            )

    click.echo(f"Stored extraction for {source_id}")

    # Show summary of what was stored
    builds_count = len(data.get('builds', []))
    learnings_count = len(data.get('learnings', []))
    click.echo(f"  {builds_count} builds, {learnings_count} learnings")



@main.command()
@click.option('--remove', multiple=True, help="Remove auto-mapping by mention text")
@click.pass_context
def digest(ctx, remove):
    """Review auto-mappings for quality control.

    Shows all auto-resolved entity mappings so you can spot errors.
    Use --remove to delete bad mappings.

    Examples:
        garde digest                    # Show all auto-mappings
        garde digest --remove "typo"    # Remove a bad mapping
    """
    from .glossary import save_glossary

    glossary = ctx.obj['glossary']
    auto_mappings = glossary.auto_mappings

    if remove:
        removed = 0
        for mention in remove:
            if mention in auto_mappings:
                del auto_mappings[mention]
                removed += 1
                click.echo(f"  Removed: {mention}")
            else:
                click.echo(f"  Not found: {mention}")
        if removed:
            save_glossary(glossary)
            click.echo(f"\nRemoved {removed} mapping(s), glossary saved.")
        return

    if not auto_mappings:
        click.echo("No auto-mappings to review.")
        return

    click.echo(f"\n{len(auto_mappings)} auto-mappings:\n")

    # Group by target entity for easier review
    by_target: dict[str, list[str]] = {}
    for mention, target in sorted(auto_mappings.items()):
        by_target.setdefault(target, []).append(mention)

    for target in sorted(by_target.keys()):
        mentions = by_target[target]
        if len(mentions) == 1 and mentions[0].lower().replace(' ', '_').replace('-', '_') == target.lower():
            # Simple case: mention maps to normalized version of itself
            click.echo(f"  {mentions[0]} → {target}")
        else:
            # Multiple mentions or non-obvious mapping
            click.echo(f"  → {target}:")
            for m in sorted(mentions):
                click.echo(f"      {m}")

    click.echo(f"\nTo remove a bad mapping: garde digest --remove \"mention text\"")
    click.echo("To promote to full entity: edit ~/.claude/memory/glossary.yaml")


if __name__ == '__main__':
    main()
