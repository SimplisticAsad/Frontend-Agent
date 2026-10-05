"""In-memory representation of a validated project graph package."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

# Graph files the frontend pipeline consumes (spec section 5). backend.json etc. are never loaded.
FRONTEND_GRAPHS = (
    "project",
    "actors",
    "roles",
    "entities",
    "relationships",
    "capabilities",
    "requirements",
    "screens",
    "components",
    "workflows",
    "api",
    "permissions",
    "validations",
    "state_machines",
    "dependencies",
    "acceptance_criteria",
    "assumptions",
    "questions",
)

Node = dict[str, Any]


@dataclass
class GraphPackage:
    root: str
    manifest: dict[str, Any]
    graphs: dict[str, list[Node]]
    index: dict[str, tuple[str, Node]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for gname, nodes in self.graphs.items():
            for n in nodes:
                nid = n.get("id")
                if isinstance(nid, str):
                    self.index.setdefault(nid, (gname, n))

    # ---- accessors ----
    @property
    def project_id(self) -> str:
        return self.manifest.get("project_id", "project")

    @property
    def graph_version(self) -> str:
        return str(self.manifest.get("graph_version", "unknown"))

    def nodes(self, graph: str) -> list[Node]:
        return self.graphs.get(graph, [])

    def get(self, ref: str) -> Node | None:
        hit = self.index.get(ref)
        return hit[1] if hit else None

    def kind_of(self, ref: str) -> str | None:
        hit = self.index.get(ref)
        return hit[0] if hit else None

    def has(self, ref: str, graph: str | None = None) -> bool:
        hit = self.index.get(ref)
        return bool(hit) and (graph is None or hit[0] == graph)

    def require(self, ref: str) -> Node:
        n = self.get(ref)
        if n is None:
            raise KeyError(ref)
        return n

    def many(self, refs: Iterable[str]) -> list[Node]:
        return [n for r in refs if (n := self.get(r)) is not None]

    # ---- convenience views ----
    @property
    def screens(self) -> list[Node]:
        return self.nodes("screens")

    @property
    def workflows(self) -> list[Node]:
        return self.nodes("workflows")

    @property
    def apis(self) -> list[Node]:
        return self.nodes("api")

    @property
    def entities(self) -> list[Node]:
        return self.nodes("entities")

    @property
    def roles(self) -> list[Node]:
        return self.nodes("roles")

    @property
    def permissions(self) -> list[Node]:
        return self.nodes("permissions")

    def entity_field(self, entity_ref: str, name: str) -> Node | None:
        ent = self.get(entity_ref)
        if not ent:
            return None
        return next((f for f in ent.get("fields", []) if f.get("name") == name), None)

    def validations_for(self, entity_ref: str, field_name: str) -> list[Node]:
        return [
            v
            for v in self.nodes("validations")
            if v.get("entity") == entity_ref and v.get("field") == field_name
        ]

    def workflows_for_screen(self, screen_ref: str) -> list[Node]:
        scr = self.get(screen_ref) or {}
        return self.many(scr.get("actions", []))

    def api_ids_for_workflow(self, wf: Node) -> list[str]:
        return [a for a in [wf.get("api")] if a]
