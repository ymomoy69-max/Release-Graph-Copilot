"""Catalog-specific tests (also run by test_graph.py)."""
from rgc.catalog import load_catalog

CATALOG_PATH = "fixtures/catalog/repos.json"


def test_catalog_is_frozenset():
    cat = load_catalog(CATALOG_PATH)
    assert isinstance(cat, frozenset)


def test_catalog_known_repos():
    cat = load_catalog(CATALOG_PATH)
    assert "meridian-gateway" in cat
    assert "bitbucket-db-migration" in cat
    assert "repo-0008" in cat
    assert "repo-1130" in cat


def test_catalog_unknown_repos():
    cat = load_catalog(CATALOG_PATH)
    assert "a" not in cat
    assert "b" not in cat
    assert "not-a-real-repo" not in cat
