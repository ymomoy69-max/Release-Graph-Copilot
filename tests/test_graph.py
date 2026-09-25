"""Tests for rgc/graph.py and rgc/catalog.py."""
import time
import pytest
from rgc.graph import load_graph, detect_cycle, compute_closure, topological_sort
from rgc.catalog import load_catalog


GRAPH_PATH = "fixtures/graph/deploy-graph.yaml"
CYCLIC_PATH = "fixtures/graph/cyclic-graph.yaml"
CATALOG_PATH = "fixtures/catalog/repos.json"

SIX_NODES = [
    "meridian-gateway",
    "prompt-backend",
    "user-stack-ansible",
    "meridian-ui",
    "workflow-service",
    "nc-enterprise-ai-platform-etl-jobs",
]


# ---------------------------------------------------------------------------
# Graph loading
# ---------------------------------------------------------------------------

def test_load_graph_nodes():
    g = load_graph(GRAPH_PATH)
    ids = {n.id for n in g.nodes}
    assert ids == set(SIX_NODES)


def test_load_graph_edges():
    g = load_graph(GRAPH_PATH)
    assert len(g.edges) == 5


def test_cyclic_graph_has_cycle():
    g = load_graph(CYCLIC_PATH)
    assert detect_cycle(g) is True


def test_deploy_graph_no_cycle():
    g = load_graph(GRAPH_PATH)
    assert detect_cycle(g) is False


def test_self_edge_is_cycle():
    """A graph with a self-edge is a cycle."""
    import yaml, tempfile, os
    data = {
        "nodes": [{"id": "a", "role": "test"}],
        "edges": [{"from": "a", "to": "a", "relation": "x"}],
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(data, f)
        path = f.name
    try:
        g = load_graph(path)
        assert detect_cycle(g) is True
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# Closure
# ---------------------------------------------------------------------------

def test_closure_meridian_gateway():
    """Naming only meridian-gateway closes over all six nodes."""
    g = load_graph(GRAPH_PATH)
    closure = compute_closure(g, ["meridian-gateway"])
    assert closure == frozenset(SIX_NODES)


def test_closure_prompt_backend():
    """Closure of prompt-backend is all six graph nodes."""
    g = load_graph(GRAPH_PATH)
    closure = compute_closure(g, ["prompt-backend"])
    assert closure == frozenset(SIX_NODES)


def test_closure_excludes_non_graph_repos():
    """bitbucket-db-migration is not in the graph."""
    g = load_graph(GRAPH_PATH)
    closure = compute_closure(g, ["prompt-backend"])
    assert "bitbucket-db-migration" not in closure
    assert "repo-0008" not in closure


# ---------------------------------------------------------------------------
# Topological sort
# ---------------------------------------------------------------------------

def test_topological_sort_full_graph():
    g = load_graph(GRAPH_PATH)
    closure = compute_closure(g, ["meridian-gateway"])
    order = topological_sort(g, closure)
    assert order == [
        "meridian-gateway",
        "prompt-backend",
        "user-stack-ansible",
        "meridian-ui",
        "workflow-service",
        "nc-enterprise-ai-platform-etl-jobs",
    ]


def test_topological_sort_subset():
    g = load_graph(GRAPH_PATH)
    # Only meridian-gateway and prompt-backend (direct edge)
    closure = frozenset(["meridian-gateway", "prompt-backend"])
    order = topological_sort(g, closure)
    assert order == ["meridian-gateway", "prompt-backend"]


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

def test_catalog_length():
    cat = load_catalog(CATALOG_PATH)
    assert len(cat) == 1130


def test_catalog_unique():
    import json
    with open(CATALOG_PATH) as f:
        lst = json.load(f)
    assert len(lst) == len(set(lst))


def test_catalog_first_seven():
    import json
    with open(CATALOG_PATH) as f:
        lst = json.load(f)
    expected = [
        "meridian-gateway",
        "prompt-backend",
        "user-stack-ansible",
        "meridian-ui",
        "workflow-service",
        "nc-enterprise-ai-platform-etl-jobs",
        "bitbucket-db-migration",
    ]
    assert lst[:7] == expected


def test_catalog_last_id():
    import json
    with open(CATALOG_PATH) as f:
        lst = json.load(f)
    assert lst[-1] == "repo-1130"


def test_catalog_and_closure_under_one_second():
    start = time.monotonic()
    cat = load_catalog(CATALOG_PATH)
    g = load_graph(GRAPH_PATH)
    closure = compute_closure(g, ["prompt-backend"])
    elapsed = time.monotonic() - start
    assert elapsed < 1.0
