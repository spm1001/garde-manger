"""Browse commands — read-only queries against the database."""

import json
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import click

from ..config import load_config, get_memory_dir
from ..database import get_database
from . import main
from ._helpers import _format_date, _auto_quote_hyphenated, _expand_query, _add_wildcard_suffix


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
        click.echo(click.style("All source paths are valid.", fg='green'))
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
    click.echo(click.style(f"\n{verb} {processed} sources.", fg='green'))


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
    by_source = defaultdict(list)
    source_meta = {}
    for r in results:
        by_source[r['source_id']].append(r['file_path'])
        source_meta[r['source_id']] = r

    for source_id, file_list in by_source.items():
        meta = source_meta[source_id]
        date_str = _format_date(meta['created_at']) if meta['created_at'] else ''
        title = meta['title'][:50] if meta['title'] else '(untitled)'

        click.echo(f"[{meta['source_type']}] {title}")
        click.echo(f"  {date_str} · {source_id}")
        for f in file_list[:3]:  # Show up to 3 matching files
            click.echo(f"  → {f}")
        if len(file_list) > 3:
            click.echo(f"  → ... and {len(file_list) - 3} more files")
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
                file_list = metadata.get('files_touched', [])
                if file_list:
                    if dry_run:
                        click.echo(f"{source_id}: {len(file_list)} files")
                    else:
                        added = db.add_file_mentions_batch(source_id, file_list)
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
                click.echo(f"  - {what}")
            if len(extraction['builds']) > 5:
                click.echo(f"  ... and {len(extraction['builds']) - 5} more")

        if extraction.get('learnings'):
            click.echo(f"\nLearnings ({len(extraction['learnings'])}):")
            for l in extraction['learnings'][:5]:
                if isinstance(l, dict):
                    insight = l.get('insight', str(l))
                    why = l.get('why_it_matters', '')
                    click.echo(f"  - {insight}")
                    if why:
                        click.echo(f"    → {why}")
                else:
                    click.echo(f"  - {l}")
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
            from ..adapters.claude_ai import ClaudeAISource
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
            from ..adapters.cloud_sessions import CloudSessionSource
            conv = CloudSessionSource.from_file(path)
            for msg in conv.messages:
                role = msg.get('role', 'unknown').upper()
                content = msg.get('content', '')
                if isinstance(content, str) and content:
                    messages.append((role, content))

        elif source_type == 'claude_code':
            from ..adapters.claude_code import ClaudeCodeSource
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
        st = row['source_type'] if 'source_type' in row.keys() else ''
        if 'handoff' in st:
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
