"""
Deploy graph loading, cycle detection, closure computation, and topological sort.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import yaml


@dataclass(frozen=True)
class GraphNode:
    id: str
    role: str


@dataclass(frozen=True)
class GraphEdge:
    from_id: str
    to_id: str
    relation: str


@dataclass(frozen=True)
class DeployGraph:
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]

    def node_ids(self) -> frozenset[str]:
        return frozenset(n.id for n in self.nodes)

    def successors(self) -> dict[str, list[str]]:
        """Map node_id → list of direct successors (to)."""
        result: dict[str, list[str]] = {n.id: [] for n in self.nodes}
        for e in self.edges:
            if e.from_id in result:
                result[e.from_id].append(e.to_id)
            else:
                result[e.from_id] = [e.to_id]
        return result

    def predecessors(self) -> dict[str, list[str]]:
        """Map node_id → list of direct predecessors (from)."""
        result: dict[str, list[str]] = {n.id: [] for n in self.nodes}
        for e in self.edges:
            if e.to_id in result:
                result[e.to_id].append(e.from_id)
            else:
                result[e.to_id] = [e.from_id]
        return result


def load_graph(path: str) -> DeployGraph:
    """Load a deploy graph from a YAML file.

    Raises ValueError on parse or structural errors.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"Cannot read graph: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("Graph YAML must be a mapping")
    if not isinstance(data.get("nodes"), list):
        raise ValueError("Graph YAML missing 'nodes' list")
    if not isinstance(data.get("edges"), list):
        raise ValueError("Graph YAML missing 'edges' list")

    nodes: list[GraphNode] = []
    for item in data["nodes"]:
        if not isinstance(item, dict):
            raise ValueError("Each node must be a mapping")
        nodes.append(GraphNode(id=str(item["id"]), role=str(item.get("role", ""))))

    edges: list[GraphEdge] = []
    for item in data["edges"]:
        if not isinstance(item, dict):
            raise ValueError("Each edge must be a mapping")
        edges.append(GraphEdge(
            from_id=str(item["from"]),
            to_id=str(item["to"]),
            relation=str(item.get("relation", "")),
        ))

    return DeployGraph(nodes=tuple(nodes), edges=tuple(edges))


def detect_cycle(graph: DeployGraph) -> bool:
    """Return True if the graph contains a cycle (including self-edges)."""
    succs = graph.successors()
    node_ids = graph.node_ids()

    # Check self-edges first
    for e in graph.edges:
        if e.from_id == e.to_id:
            return True

    # DFS over graph nodes only (do not add unknown node ids)
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {n: WHITE for n in node_ids}

    def dfs(node: str) -> bool:
        color[node] = GRAY
        for neighbor in succs.get(node, []):
            if neighbor not in color:
                # Edge to unknown node — not a cycle
                continue
            if color[neighbor] == GRAY:
                return True
            if color[neighbor] == WHITE:
                if dfs(neighbor):
                    return True
        color[node] = BLACK
        return False

    for node in sorted(node_ids):  # deterministic order
        if color[node] == WHITE:
            if dfs(node):
                return True
    return False


def compute_closure(graph: DeployGraph, named_repos: list[str]) -> frozenset[str]:
    """Compute the closure of named_repos in the graph.

    Closure = repos that exist in graph + their ancestors + their descendants.
    Named repos not in the graph are excluded from the closure.
    """
    node_ids = graph.node_ids()
    succs = graph.successors()
    preds = graph.predecessors()

    # Only named repos that are in the graph
    seeds = frozenset(r for r in named_repos if r in node_ids)
    if not seeds:
        return frozenset()

    # BFS forward for descendants, backward for ancestors
    closure: set[str] = set(seeds)

    # Forward (descendants)
    queue = list(seeds)
    while queue:
        node = queue.pop()
        for neighbor in succs.get(node, []):
            if neighbor in node_ids and neighbor not in closure:
                closure.add(neighbor)
                queue.append(neighbor)

    # Backward (ancestors)
    queue = [n for n in seeds]
    while queue:
        node = queue.pop()
        for neighbor in preds.get(node, []):
            if neighbor in node_ids and neighbor not in closure:
                closure.add(neighbor)
                queue.append(neighbor)

    return frozenset(closure)


def topological_sort(graph: DeployGraph, closure: frozenset[str]) -> list[str]:
    """Topological sort of the closure subgraph using Kahn's algorithm.

    When multiple nodes have indegree 0, pick the lexicographically smallest id.
    """
    # Build subgraph
    succs: dict[str, list[str]] = {n: [] for n in closure}
    indegree: dict[str, int] = {n: 0 for n in closure}

    for e in graph.edges:
        if e.from_id in closure and e.to_id in closure:
            succs[e.from_id].append(e.to_id)
            indegree[e.to_id] += 1

    # Kahn's
    import heapq
    heap: list[str] = [n for n in closure if indegree[n] == 0]
    heapq.heapify(heap)

    order: list[str] = []
    while heap:
        node = heapq.heappop(heap)
        order.append(node)
        for neighbor in sorted(succs[node]):
            indegree[neighbor] -= 1
            if indegree[neighbor] == 0:
                heapq.heappush(heap, neighbor)

    return order
