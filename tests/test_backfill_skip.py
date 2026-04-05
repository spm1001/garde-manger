"""Tests for backfill handoff-dedup logic.

Verifies that backfill skips claude_code sessions that already have
a handoff-section-parse extraction, via both metadata session_id
and stem-based UUID fallback matching.
"""

import json
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from garde.database import Database


@pytest.fixture
def db():
    """Create a temporary database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / 'test.db'
        database = Database(db_path)
        with database:
            yield database


BACKFILL_SQL = """
    SELECT s.id, s.source_type, s.title, s.path
    FROM sources s
    LEFT JOIN extractions e ON s.id = e.source_id
    WHERE e.source_id IS NULL
    AND (s.source_type != 'claude_code' OR NOT EXISTS (
        SELECT 1 FROM sources h
        JOIN extractions he ON h.id = he.source_id
        WHERE h.source_type = 'handoff'
        AND he.model_used = 'handoff-section-parse'
        AND (
            json_extract(h.metadata, '$.session_id') = SUBSTR(s.id, 13)
            OR s.id LIKE 'claude_code:' || SUBSTR(h.id, -8) || '%'
        )
    ))
    ORDER BY s.updated_at DESC
"""


def _add_cc_source(db, uuid):
    db.upsert_source(
        source_id=f'claude_code:{uuid}',
        source_type='claude_code',
        title=f'Session {uuid[:8]}',
    )


def _add_handoff_with_extraction(db, stem, session_id=None):
    metadata = {'session_id': session_id} if session_id else None
    db.upsert_source(
        source_id=f'handoff:{stem}',
        source_type='handoff',
        title=f'Handoff {stem}',
        metadata=metadata,
    )
    db.upsert_extraction(
        source_id=f'handoff:{stem}',
        summary='Test extraction',
        model_used='handoff-section-parse',
    )


class TestBackfillHandoffDedup:
    """Backfill skips claude_code sessions covered by handoff extractions."""

    def test_skips_via_metadata_session_id(self, db):
        """Primary path: match via json_extract on metadata.session_id."""
        uuid = '37cade0a-6c15-4668-8338-c6fcbd3126ee'
        _add_cc_source(db, uuid)
        _add_handoff_with_extraction(db, '2026-04-05-37cade0a', session_id=uuid)

        rows = db.connect().execute(BACKFILL_SQL).fetchall()
        assert len(rows) == 0

    def test_skips_via_stem_fallback(self, db):
        """Fallback: match via last 8 chars of handoff stem = UUID prefix."""
        uuid = 'caba87e1-1234-5678-abcd-ef0123456789'
        _add_cc_source(db, uuid)
        # Old-format handoff: stem IS the short UUID, no metadata
        _add_handoff_with_extraction(db, 'caba87e1')

        rows = db.connect().execute(BACKFILL_SQL).fetchall()
        assert len(rows) == 0

    def test_skips_via_dated_stem_fallback(self, db):
        """Fallback with fond-v1 dated stem (no metadata populated yet)."""
        uuid = 'abcd1234-5678-9abc-def0-123456789abc'
        _add_cc_source(db, uuid)
        # Dated stem, but no metadata stored yet (pre-migration)
        _add_handoff_with_extraction(db, '2026-03-15-abcd1234')

        rows = db.connect().execute(BACKFILL_SQL).fetchall()
        assert len(rows) == 0

    def test_keeps_session_without_handoff(self, db):
        """Sessions with no matching handoff still appear in backfill."""
        _add_cc_source(db, 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee')

        rows = db.connect().execute(BACKFILL_SQL).fetchall()
        assert len(rows) == 1
        assert rows[0]['id'] == 'claude_code:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'

    def test_keeps_session_with_non_handoff_extraction(self, db):
        """Handoff source without section-parse extraction doesn't trigger skip."""
        uuid = 'deadbeef-1234-5678-abcd-ef0123456789'
        _add_cc_source(db, uuid)
        # Handoff exists but with LLM extraction, not section-parse
        db.upsert_source(
            source_id='handoff:deadbeef',
            source_type='handoff',
            title='Handoff deadbeef',
        )
        db.upsert_extraction(
            source_id='handoff:deadbeef',
            summary='LLM extraction',
            model_used='claude-opus-4-6',
        )

        rows = db.connect().execute(BACKFILL_SQL).fetchall()
        assert len(rows) == 1

    def test_non_claude_code_sources_unaffected(self, db):
        """Handoff dedup only applies to claude_code sources."""
        db.upsert_source(
            source_id='bon:bon-test',
            source_type='bon',
            title='Test bon item',
        )
        db.upsert_source(
            source_id='amp:T-12345',
            source_type='amp',
            title='Test amp thread',
        )
        # Add a handoff extraction that could theoretically match
        _add_handoff_with_extraction(db, 'bon-test', session_id='bon-test')

        rows = db.connect().execute(BACKFILL_SQL).fetchall()
        source_ids = [r['id'] for r in rows]
        assert 'bon:bon-test' in source_ids
        assert 'amp:T-12345' in source_ids

    def test_already_extracted_not_returned(self, db):
        """Sessions with their own extraction don't appear regardless."""
        uuid = '11111111-2222-3333-4444-555555555555'
        _add_cc_source(db, uuid)
        db.upsert_extraction(
            source_id=f'claude_code:{uuid}',
            summary='Already extracted',
            model_used='claude-opus-4-6',
        )

        rows = db.connect().execute(BACKFILL_SQL).fetchall()
        assert len(rows) == 0

    def test_mixed_scenario(self, db):
        """Realistic mix: some covered, some not, some already extracted."""
        # Session A: has handoff extraction → skip
        uuid_a = 'aaaa0001-0000-0000-0000-000000000000'
        _add_cc_source(db, uuid_a)
        _add_handoff_with_extraction(db, '2026-01-01-aaaa0001', session_id=uuid_a)

        # Session B: no handoff → keep
        uuid_b = 'bbbb0002-0000-0000-0000-000000000000'
        _add_cc_source(db, uuid_b)

        # Session C: already has its own extraction → excluded by LEFT JOIN
        uuid_c = 'cccc0003-0000-0000-0000-000000000000'
        _add_cc_source(db, uuid_c)
        db.upsert_extraction(
            source_id=f'claude_code:{uuid_c}',
            summary='Done',
            model_used='claude-opus-4-6',
        )

        rows = db.connect().execute(BACKFILL_SQL).fetchall()
        ids = [r['id'] for r in rows]
        assert f'claude_code:{uuid_a}' not in ids  # skipped by handoff
        assert f'claude_code:{uuid_b}' in ids       # needs backfill
        assert f'claude_code:{uuid_c}' not in ids  # already extracted
