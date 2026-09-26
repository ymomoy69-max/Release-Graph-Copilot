"""Disable Groq during unit/integration tests — engine + safety gate still run."""
import os
from pathlib import Path

os.environ["RG_AI_DISABLE"] = "1"
os.environ["GROQ_API_KEY"] = ""
_root = Path(__file__).resolve().parent.parent
os.environ.setdefault(
    "RELEASEGRAPH_WORKSPACE",
    str(_root / "demo" / "ecommerce"),
)
