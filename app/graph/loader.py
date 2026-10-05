"""Deterministic graph loading. Reads graph_manifest.json then only the frontend-relevant files."""
from __future__ import annotations

import json
from pathlib import Path

from app.domain.models.errors import ErrorKind, GraphError, Issue
from app.domain.models.graph import FRONTEND_GRAPHS, GraphPackage

MANIFEST = "graph_manifest.json"


def _read_json(path: Path, issues: list[Issue]) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        issues.append(Issue(ErrorKind.GRAPH_ERROR, "file_missing", f"Missing graph file: {path.name}", location=str(path)))
    except json.JSONDecodeError as e:
        issues.append(Issue(ErrorKind.GRAPH_ERROR, "invalid_json", f"{path.name} is not valid JSON: {e}", location=str(path)))
    return None


def resolve_graph_dir(project_dir: str | Path) -> Path:
    p = Path(project_dir)
    return p / "graphs" if (p / "graphs").is_dir() else p


def load_graph_package(project_dir: str | Path) -> GraphPackage:
    """Load the package; raises GraphError on structural problems (missing/unparseable files)."""
    gdir = resolve_graph_dir(project_dir)
    issues: list[Issue] = []
    manifest = _read_json(gdir / MANIFEST, issues)
    if not isinstance(manifest, dict):
        if manifest is not None:
            issues.append(Issue(ErrorKind.GRAPH_ERROR, "manifest_shape", "graph_manifest.json must be an object"))
        raise GraphError(issues)

    files: dict[str, str] = manifest.get("files", {})
    graphs: dict[str, list] = {}
    for name in FRONTEND_GRAPHS:
        rel = files.get(name)
        if not rel:
            issues.append(Issue(ErrorKind.GRAPH_ERROR, "manifest_entry_missing", f"graph_manifest.json has no entry for '{name}'", location=MANIFEST))
            continue
        data = _read_json(gdir / rel, issues)
        if data is None:
            continue
        nodes = data.get("nodes") if isinstance(data, dict) else None
        if not isinstance(nodes, list) or not all(isinstance(n, dict) for n in nodes):
            issues.append(Issue(ErrorKind.GRAPH_ERROR, "nodes_shape", f"{rel}: expected an object with a 'nodes' list of objects", location=rel))
            continue
        graphs[name] = nodes
    if issues:
        raise GraphError(issues)
    return GraphPackage(root=str(gdir), manifest=manifest, graphs=graphs)
