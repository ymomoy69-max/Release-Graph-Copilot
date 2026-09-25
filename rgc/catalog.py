"""
Repository catalog loader.
"""
from __future__ import annotations

import json
import functools

CATALOG_PATH = "fixtures/catalog/repos.json"


@functools.lru_cache(maxsize=8)
def load_catalog(path: str = CATALOG_PATH) -> frozenset[str]:
    """Return frozenset of known repository ids."""
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError("Catalog must be a JSON array")
    return frozenset(str(r) for r in data)


def is_known(repo_id: str, catalog: frozenset[str] | None = None) -> bool:
    if catalog is None:
        catalog = load_catalog()
    return repo_id in catalog
