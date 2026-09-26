__version__ = "1.0.0"

__all__ = ["__version__", "analyze_workspace", "Client"]


def __getattr__(name: str):
    if name in {"analyze_workspace", "Client"}:
        from releasegraph.sdk import Client, analyze_workspace

        mapping = {"analyze_workspace": analyze_workspace, "Client": Client}
        return mapping[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
