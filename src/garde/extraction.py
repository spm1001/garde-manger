"""Entity extraction from sources.

Extracts entities using LLM, matches against glossary, and queues unknowns.
"""

import sys
from dataclasses import dataclass
from typing import Any

from .database import Database
from .glossary import Glossary
from .llm import extract_entities, confidence_to_float


@dataclass
class ExtractionResult:
    """Result of extracting entities from a source."""
    source_id: str
    entities_found: int
    matched: int      # Matched existing glossary entity
    pending: int      # Queued for resolution
    entities: list[dict]


def extract_from_source(
    source_id: str,
    full_text: str,
    glossary: Glossary,
    db: Database,
    is_voice: bool = False,
) -> ExtractionResult:
    """Extract entities from source content.

    Args:
        source_id: The source identifier
        full_text: Full text content to extract from
        glossary: Loaded glossary for matching
        db: Database connection
        is_voice: Whether this is voice-transcribed content

    Returns:
        ExtractionResult with counts and entity details
    """
    # Extract entities via LLM
    entities = extract_entities(full_text, glossary.raw, is_voice=is_voice)

    matched = 0
    pending = 0
    skipped = 0

    for entity in entities:
        # LLM may return malformed entities - skip gracefully
        if not isinstance(entity, dict) or 'mention' not in entity:
            skipped += 1
            continue

        mention = entity['mention']
        confidence = confidence_to_float(entity.get('confidence', 'medium'))
        suggested = entity.get('suggested_canonical')

        # Try to match against glossary
        resolved = glossary.resolve(mention)

        if resolved:
            # Known entity - store as resolved
            db.add_source_entity(
                source_id=source_id,
                entity_id=resolved,
                mention_text=mention,
                confidence=confidence,
            )
            matched += 1
        elif suggested:
            # Has suggestion - check if suggestion is known
            resolved_suggestion = glossary.resolve(suggested)
            if resolved_suggestion:
                db.add_source_entity(
                    source_id=source_id,
                    entity_id=resolved_suggestion,
                    mention_text=mention,
                    confidence=confidence,
                )
                matched += 1
            else:
                # Suggested entity not in glossary - queue for review
                db.queue_pending_entity(
                    mention_text=mention,
                    source_id=source_id,
                    suggested_entity=suggested,
                    confidence=confidence,
                )
                pending += 1
        else:
            # Completely unknown - queue for review
            db.queue_pending_entity(
                mention_text=mention,
                source_id=source_id,
                suggested_entity=None,
                confidence=confidence,
            )
            pending += 1

    if skipped > 0:
        print(f"⚠️  Skipped {skipped} malformed entities in {source_id}", file=sys.stderr)

    return ExtractionResult(
        source_id=source_id,
        entities_found=len(entities) - skipped,
        matched=matched,
        pending=pending,
        entities=entities,
    )


def get_source_content(source_id: str, db: Database, config: dict = None) -> tuple[str, bool]:
    """Load full text content for a source from database.

    Retrieves raw_text stored during indexing, which works for ALL source types
    (claude_code, claude_ai, cloud_session, handoff, local_md, beads, arc, knowledge).

    Args:
        source_id: The source identifier
        db: Database connection
        config: Unused, kept for backwards compatibility

    Returns:
        Tuple of (full_text, is_voice)
    """
    # Get source metadata for is_voice check
    source = db.get_source(source_id)
    if not source:
        raise ValueError(f"Source not found: {source_id}")

    is_voice = source.get('input_mode') == 'voice'

    # Retrieve raw_text from summaries table (stored during indexing)
    conn = db.connect()
    row = conn.execute(
        "SELECT raw_text FROM summaries WHERE source_id = ?",
        (source_id,)
    ).fetchone()

    if not row or not row['raw_text']:
        raise ValueError(f"No raw_text found for source {source_id}. Run 'garde scan' to index it first.")

    return row['raw_text'], is_voice
