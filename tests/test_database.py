"""Tests for database operations."""

import tempfile
from pathlib import Path
from datetime import datetime

import pytest

from garde.database import Database


@pytest.fixture
def temp_db():
    """Create a temporary database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / 'test.db'
        db = Database(db_path)
        with db:
            yield db


def test_create_database(temp_db):
    """Database creates with schema."""
    stats = temp_db.get_stats()
    assert stats['total_sources'] == 0


def test_upsert_source(temp_db):
    """Insert and retrieve source."""
    temp_db.upsert_source(
        source_id='claude_code:test123',
        source_type='claude_code',
        title='Test conversation',
        path='/path/to/file.jsonl',
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    source = temp_db.get_source('claude_code:test123')
    assert source is not None
    assert source['title'] == 'Test conversation'
    assert source['source_type'] == 'claude_code'


def test_upsert_source_update(temp_db):
    """Upsert updates existing source."""
    temp_db.upsert_source(
        source_id='test:1',
        source_type='test',
        title='Original title',
    )
    temp_db.upsert_source(
        source_id='test:1',
        source_type='test',
        title='Updated title',
    )

    source = temp_db.get_source('test:1')
    assert source['title'] == 'Updated title'


def test_source_exists(temp_db):
    """Check if source exists."""
    assert not temp_db.source_exists('test:1')

    temp_db.upsert_source(
        source_id='test:1',
        source_type='test',
        title='Test',
    )

    assert temp_db.source_exists('test:1')


def test_upsert_summary_and_search(temp_db):
    """Insert summary and search via FTS5."""
    temp_db.upsert_source(
        source_id='test:1',
        source_type='test',
        title='GeoX discussion',
    )
    temp_db.upsert_summary(
        source_id='test:1',
        summary_text='We discussed the GeoX regional measurement approach',
    )

    results = temp_db.search('GeoX')
    assert len(results) == 1
    assert results[0].source_id == 'test:1'
    assert 'GeoX' in results[0].summary_text


def test_search_no_results(temp_db):
    """Search returns empty list for no matches."""
    results = temp_db.search('nonexistent')
    assert results == []


def test_list_sources_by_type(temp_db):
    """List sources filtered by type."""
    temp_db.upsert_source(source_id='a:1', source_type='type_a', title='A1')
    temp_db.upsert_source(source_id='a:2', source_type='type_a', title='A2')
    temp_db.upsert_source(source_id='b:1', source_type='type_b', title='B1')

    type_a = temp_db.list_sources(source_type='type_a')
    assert len(type_a) == 2

    type_b = temp_db.list_sources(source_type='type_b')
    assert len(type_b) == 1


def test_mark_processed(temp_db):
    """Mark source as processed."""
    temp_db.upsert_source(source_id='test:1', source_type='test', title='Test')

    source = temp_db.get_source('test:1')
    assert source['status'] == 'pending'

    temp_db.mark_processed('test:1')

    source = temp_db.get_source('test:1')
    assert source['status'] == 'processed'
    assert source['processed_at'] is not None


def test_get_stats(temp_db):
    """Get database statistics."""
    temp_db.upsert_source(source_id='a:1', source_type='type_a', title='A1')
    temp_db.upsert_source(source_id='a:2', source_type='type_a', title='A2')
    temp_db.mark_processed('a:1')

    stats = temp_db.get_stats()
    assert stats['total_sources'] == 2
    assert stats['by_type']['type_a'] == 2
    assert stats['by_status']['pending'] == 1
    assert stats['by_status']['processed'] == 1


# When metadata is provided, it should be stored and retrievable
def test_upsert_source_with_metadata(temp_db):
    """Insert source with metadata JSON."""
    import json

    metadata = {
        'tool_calls': [{'name': 'Bash', 'ts': '2025-01-01T00:00:00Z'}],
        'files_touched': ['/src/main.py'],
        'skills_used': ['close'],
        'tool_count': 1
    }

    temp_db.upsert_source(
        source_id='claude_code:test456',
        source_type='claude_code',
        title='Test with metadata',
        metadata=metadata
    )

    source = temp_db.get_source('claude_code:test456')
    assert source is not None
    assert source['metadata'] is not None

    stored_metadata = json.loads(source['metadata'])
    assert stored_metadata['tool_count'] == 1
    assert stored_metadata['skills_used'] == ['close']
    assert '/src/main.py' in stored_metadata['files_touched']


def test_fts_update_trigger(temp_db):
    """FTS stays in sync through INSERT/UPDATE/DELETE cycle.

    Regression test for FTS5 trigger bug where UPDATE trigger used wrong
    delete syntax (INSERT...VALUES('delete',...) instead of DELETE FROM)
    for standalone FTS5 tables.
    """
    # Setup: create source and summary
    temp_db.upsert_source(
        source_id='test:fts',
        source_type='test',
        title='FTS Trigger Test',
    )
    temp_db.upsert_summary(
        source_id='test:fts',
        summary_text='Original summary about pandas dataframes',
    )

    # Verify INSERT trigger worked - FTS search finds it
    results = temp_db.search('pandas')
    assert len(results) == 1
    assert results[0].source_id == 'test:fts'

    # UPDATE the summary (this triggers summaries_au)
    temp_db.upsert_summary(
        source_id='test:fts',
        summary_text='Updated summary about numpy arrays',
    )

    # Verify UPDATE trigger worked:
    # - Old content should NOT be searchable
    old_results = temp_db.search('pandas')
    assert len(old_results) == 0, "Old FTS content not deleted"

    # - New content SHOULD be searchable
    new_results = temp_db.search('numpy')
    assert len(new_results) == 1, "New FTS content not inserted"
    assert new_results[0].source_id == 'test:fts'


def test_fts_title_from_sources(temp_db):
    """FTS index includes title from sources table via JOIN."""
    temp_db.upsert_source(
        source_id='test:title',
        source_type='test',
        title='Kubernetes deployment guide',
    )
    temp_db.upsert_summary(
        source_id='test:title',
        summary_text='How to deploy services',
    )

    # Should find via title (from sources table)
    results = temp_db.search('Kubernetes')
    assert len(results) == 1
    assert results[0].title == 'Kubernetes deployment guide'

    # Should also find via summary text
    results = temp_db.search('deploy services')
    assert len(results) == 1
