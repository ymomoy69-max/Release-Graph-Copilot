"""
Workspace view — presents files with overlay support.
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rgc.manifest import Release


class WorkspaceView:
    """Read-only view of the workspace with overlay support."""

    def __init__(self, release: "Release") -> None:
        self._workspace_root = release.workspace_root
        # Build overlay map: last overlay wins
        self._overlays: dict[str, str] = {}
        for overlay in release.overlays:
            self._overlays[overlay.path] = overlay.content

    def read_text(self, relative_path: str) -> str:
        """Return overlay content if present, otherwise read from workspace_root.

        Raises FileNotFoundError if neither is available.
        """
        if relative_path in self._overlays:
            return self._overlays[relative_path]

        full_path = os.path.join(self._workspace_root, relative_path)
        try:
            with open(full_path, "r", encoding="utf-8") as fh:
                return fh.read()
        except OSError as exc:
            raise FileNotFoundError(
                f"File not found in workspace: {relative_path}"
            ) from exc

    def list_files(self, relative_dir: str) -> list[str]:
        """Return file paths relative to workspace_root.

        Includes overlay paths inside the directory even if the file doesn't exist on disk.
        Overlay replaces a baseline file with the same path (no duplicates).
        """
        dir_prefix = relative_dir.rstrip("/") + "/"
        baseline: list[str] = []

        full_dir = os.path.join(self._workspace_root, relative_dir)
        if os.path.isdir(full_dir):
            for root, _dirs, files in os.walk(full_dir):
                for fname in files:
                    abs_path = os.path.join(root, fname)
                    rel = os.path.relpath(abs_path, self._workspace_root)
                    # Normalize to forward slashes
                    rel = rel.replace(os.sep, "/")
                    baseline.append(rel)

        # Merge overlays: overlays override baseline, add new overlay-only files
        result_set: dict[str, str] = {p: p for p in baseline}
        for opath in self._overlays:
            if opath.startswith(dir_prefix) or opath == relative_dir:
                result_set[opath] = opath

        return sorted(result_set.values())

    def get_snippet(self, relative_path: str, line: int, context: int = 2) -> str | None:
        """Return up to `context` lines before and after `line` (1-based).

        Returns None if the file cannot be read.
        """
        try:
            text = self.read_text(relative_path)
        except FileNotFoundError:
            return None
        lines = text.splitlines()
        start = max(0, line - 1 - context)
        end = min(len(lines), line - 1 + context + 1)
        return "\n".join(lines[start:end])
