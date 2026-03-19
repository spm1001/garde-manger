"""Entity resolution and glossary commands."""

import click

from ..database import get_database
from ..glossary import save_glossary
from . import main


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
        click.echo(f"\n{len(key_issues)} entities where key != name and key not in aliases:")
        for key, name, aliases in key_issues:
            alias_hint = f" (aliases: {', '.join(aliases)})" if aliases else ""
            click.echo(f"  {key} → \"{name}\"{alias_hint}")
            click.echo(f"    Fix: add \"{key}\" to aliases, or rename key to match name")
    else:
        click.echo("  All keys are either names or in aliases")

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
        click.echo(f"\n{len(duplicates)} aliases used by multiple entities:")
        for alias, keys in sorted(duplicates.items()):
            click.echo(f"  \"{alias}\" → {', '.join(keys)}")
    else:
        click.echo("  No duplicate aliases")

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
        click.echo(f"\n{len(orphaned)} auto_mappings point to non-existent entities:")
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
        click.echo("  No auto_mappings to review")

    # Summary
    click.echo("\n" + "=" * 40)
    if issues_found:
        click.echo("Issues found. Review above and update glossary.yaml")
    else:
        click.echo("Glossary looks good!")


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
