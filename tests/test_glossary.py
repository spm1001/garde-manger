"""Tests for glossary loading and resolution."""

import pytest

from garde.glossary import Glossary


@pytest.fixture
def sample_glossary():
    """Create a sample glossary for testing."""
    data = {
        'version': 1,
        'entities': {
            'region_lift': {
                'name': 'Region:Lift',
                'type': 'product',
                'parent': 'mit',
                'aliases': ['GeoX', 'regional holdout'],
                'description': 'Regional measurement'
            },
            'mit': {
                'name': 'MIT',
                'type': 'organization',
                'parent': 'csp',
                'aliases': ['Measurement Innovation Team'],
                'description': 'Measurement team'
            },
            'csp': {
                'name': 'CS&P',
                'type': 'organization',
                'aliases': ['Client Strategy & Planning'],
                'description': 'Strategy division'
            },
        },
        'auto_mappings': {
            'geo experiment': 'region_lift'
        }
    }
    return Glossary(data)


def test_resolve_canonical_name(sample_glossary):
    """Resolve canonical name."""
    assert sample_glossary.resolve('Region:Lift') == 'region_lift'
    assert sample_glossary.resolve('MIT') == 'mit'


def test_resolve_alias(sample_glossary):
    """Resolve alias to entity key."""
    assert sample_glossary.resolve('GeoX') == 'region_lift'
    assert sample_glossary.resolve('regional holdout') == 'region_lift'


def test_resolve_case_insensitive(sample_glossary):
    """Resolution is case-insensitive."""
    assert sample_glossary.resolve('geox') == 'region_lift'
    assert sample_glossary.resolve('GEOX') == 'region_lift'


def test_resolve_auto_mapping(sample_glossary):
    """Resolve auto-mapping."""
    assert sample_glossary.resolve('geo experiment') == 'region_lift'


def test_resolve_unknown(sample_glossary):
    """Unknown terms return None."""
    assert sample_glossary.resolve('unknown thing') is None


def test_get_name(sample_glossary):
    """Get canonical name from key."""
    assert sample_glossary.get_name('region_lift') == 'Region:Lift'
    assert sample_glossary.get_name('unknown') is None


def test_get_parent(sample_glossary):
    """Get parent entity key."""
    assert sample_glossary.get_parent('region_lift') == 'mit'
    assert sample_glossary.get_parent('mit') == 'csp'
    assert sample_glossary.get_parent('csp') is None


def test_get_ancestors(sample_glossary):
    """Get ancestor chain."""
    ancestors = sample_glossary.get_ancestors('region_lift')
    assert ancestors == ['mit', 'csp']


def test_list_by_type(sample_glossary):
    """List entities by type."""
    products = sample_glossary.list_by_type('product')
    assert 'region_lift' in products

    orgs = sample_glossary.list_by_type('organization')
    assert 'mit' in orgs
    assert 'csp' in orgs


def test_list_children(sample_glossary):
    """List children of entity."""
    mit_children = sample_glossary.list_children('mit')
    assert 'region_lift' in mit_children
