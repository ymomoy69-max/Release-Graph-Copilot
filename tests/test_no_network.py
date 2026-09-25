"""
tests/test_no_network.py — verify no network imports in product code.
"""
import ast
import os

BANNED_IMPORTS = {
    "requests",
    "httpx",
    "openai",
    "boto3",
    "urllib.request",
}


def _get_imports(filepath: str) -> set[str]:
    """Extract all import module names from a Python file."""
    with open(filepath, "r", encoding="utf-8") as fh:
        source = fh.read()

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()

    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)
    return imports


def test_no_network_imports():
    """Every *.py file under rgc/ must not import banned network libraries."""
    violations: list[str] = []

    for root, _dirs, files in os.walk("rgc"):
        for fname in files:
            if not fname.endswith(".py"):
                continue
            path = os.path.join(root, fname)
            imports = _get_imports(path)
            for banned in BANNED_IMPORTS:
                if banned in imports:
                    violations.append(f"{path}: imports {banned}")

    assert violations == [], "Network imports found:\n" + "\n".join(violations)
