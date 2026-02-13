"""Tests for entity extraction."""

import pytest
from unittest.mock import patch, MagicMock

from garde.extraction import extract_from_source, ExtractionResult
from garde.glossary import Glossary
from garde.database import Database


@pytest.fixture
def mock_glossary():
    """Create a glossary with some test entities."""
    data = {
        'entities': {
            'acme': {'name': 'Acme Corp', 'type': 'organization', 'aliases': ['acme inc', 'acme']},
            'oauth': {'name': 'OAuth', 'type': 'concept', 'aliases': ['oauth2']},
        },
        'auto_mappings': {}
    }
    return Glossary(data)


@pytest.fixture
def mock_db(tmp_path):
    """Create a test database."""
    db = Database(tmp_path / "test.db")
    db.connect()
    return db


# When LLM returns entities that match glossary, they should be stored as resolved
def test_extraction_matches_known_entities(mock_glossary, mock_db):
    mock_entities = [
        {'mention': 'Acme', 'confidence': 'high', 'suggested_canonical': None, 'reasoning': 'Company name'},
        {'mention': 'OAuth', 'confidence': 'high', 'suggested_canonical': None, 'reasoning': 'Auth protocol'},
    ]

    with patch('garde.extraction.extract_entities', return_value=mock_entities):
        result = extract_from_source(
            source_id='test:123',
            full_text='Working on Acme OAuth integration',
            glossary=mock_glossary,
            db=mock_db,
        )

    assert result.entities_found == 2
    assert result.matched == 2
    assert result.pending == 0

    # Verify entities were stored in database
    stored = mock_db.get_entities_for_source('test:123')
    assert len(stored) == 2
    entity_ids = {e['entity_id'] for e in stored}
    assert 'acme' in entity_ids
    assert 'oauth' in entity_ids


# When LLM returns unknown entities, they should be queued as pending
def test_extraction_queues_unknown_entities(mock_glossary, mock_db):
    mock_entities = [
        {'mention': 'FooBar', 'confidence': 'medium', 'suggested_canonical': None, 'reasoning': 'Unknown thing'},
    ]

    with patch('garde.extraction.extract_entities', return_value=mock_entities):
        result = extract_from_source(
            source_id='test:456',
            full_text='Working with FooBar',
            glossary=mock_glossary,
            db=mock_db,
        )

    assert result.entities_found == 1
    assert result.matched == 0
    assert result.pending == 1

    # Verify entity is in pending queue
    pending = mock_db.get_pending_entities()
    assert len(pending) == 1
    assert pending[0]['mention_text'] == 'FooBar'


# When LLM suggests a canonical name that matches glossary, use that
def test_extraction_uses_suggested_canonical(mock_glossary, mock_db):
    mock_entities = [
        {'mention': 'oauth 2.0', 'confidence': 'high', 'suggested_canonical': 'OAuth', 'reasoning': 'Auth version'},
    ]

    with patch('garde.extraction.extract_entities', return_value=mock_entities):
        result = extract_from_source(
            source_id='test:789',
            full_text='Using oauth 2.0 for auth',
            glossary=mock_glossary,
            db=mock_db,
        )

    assert result.matched == 1
    assert result.pending == 0

    stored = mock_db.get_entities_for_source('test:789')
    assert len(stored) == 1
    assert stored[0]['entity_id'] == 'oauth'
    assert stored[0]['mention_text'] == 'oauth 2.0'


# When LLM returns empty results, handle gracefully
def test_extraction_handles_no_entities(mock_glossary, mock_db):
    with patch('garde.extraction.extract_entities', return_value=[]):
        result = extract_from_source(
            source_id='test:empty',
            full_text='Just some text',
            glossary=mock_glossary,
            db=mock_db,
        )

    assert result.entities_found == 0
    assert result.matched == 0
    assert result.pending == 0
