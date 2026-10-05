"""Deterministic context selection (spec 50-51): each prompt gets only the graph slice it needs.

`closure(refs)` walks typed edges from the seed refs; it never walks "upwards" (a workflow does not pull in
every screen that mentions it), which keeps the context small and stable.
"""
from __future__ import annotations

from typing import Any, Iterable

from app.domain.models.conventions import UI_CONVENTIONS
from app.domain.models.graph import GraphPackage

# graph name -> key in the context dict
_BUCKET = {
    "screens": "screens", "components": "components", "workflows": "workflows", "api": "apis", "entities": "entities",
    "permissions": "permissions", "validations": "validations", "state_machines": "state_machines",
    "roles": "roles", "acceptance_criteria": "acceptance_criteria",
}


class ContextBuilder:
    def __init__(self, g: GraphPackage, design_system: dict | None = None):
        self.g = g
        self.design_system = design_system

    # ---- edges ----
    def _edges(self, node: dict, kind: str) -> list[str]:
        g = self.g
        out: list[str] = []
        if kind == "screens":
            out += [node.get("entity")] + node.get("components", []) + node.get("data_sources", []) + node.get("actions", []) + node.get("permissions", [])
        elif kind == "workflows":
            out += [node.get("entity"), node.get("api"), node.get("permission"), node.get("state_machine")]
        elif kind == "components":
            out += [node.get("entity"), node.get("workflow"), node.get("state_machine")] + node.get("entities", []) + node.get("row_actions", [])
        elif kind == "api":
            out += [node.get("permission"), (node.get("response") or {}).get("entity"), (node.get("request") or {}).get("entity")]
        elif kind == "entities":
            out += [node.get("state_machine")]
            out += [v["id"] for v in g.nodes("validations") if v["entity"] == node["id"]]
        elif kind == "state_machines":
            out += [node.get("entity")] + [t.get("permission") for t in node["transitions"]]
        elif kind == "acceptance_criteria":
            out += [node.get("workflow"), node.get("role")]
        elif kind == "permissions":
            out += list(node.get("roles", []))
        return [r for r in out if r]

    def closure(self, refs: Iterable[str], max_depth: int = 3) -> dict[str, list[dict]]:
        seen: dict[str, int] = {}
        order: list[str] = []
        frontier = [(r, 0) for r in refs]
        while frontier:
            ref, depth = frontier.pop(0)
            if ref in seen or not self.g.has(ref):
                continue
            seen[ref] = depth
            order.append(ref)
            kind = self.g.kind_of(ref)
            if depth < max_depth and kind in ("screens", "workflows", "components", "api", "entities", "state_machines", "acceptance_criteria", "permissions"):
                # screens only fan out one level (to their own components/apis/workflows), not into the components' dependencies' screens
                for e in self._edges(self.g.require(ref), kind):
                    frontier.append((e, depth + 1))
        buckets: dict[str, list[dict]] = {}
        for ref in order:
            kind = self.g.kind_of(ref)
            if kind in _BUCKET:
                buckets.setdefault(_BUCKET[kind], []).append(self._slim(self.g.require(ref), kind))
        return buckets

    def _slim(self, node: dict, kind: str) -> dict:
        if kind == "roles":
            return {"id": node["id"], "key": node["key"], "permissions": node["permissions"]}
        return node

    # ---- context views ----
    def base(self) -> dict[str, Any]:
        proj = self.g.nodes("project")[0]
        return {"project": {"id": proj["id"], "name": proj["name"], "description": proj.get("description", "")}, "graph_version": self.g.graph_version}

    def for_analysis(self) -> dict[str, Any]:
        """Compact overview: ids + names only; the analysis stage must not need full nodes."""
        g = self.g
        return {
            **self.base(),
            "roles": [{"id": r["id"], "key": r["key"]} for r in g.roles],
            "screens": [{"id": s["id"], "route": s["route"], "layout": s["layout"], "kind": s["kind"], "name": s["name"]} for s in g.screens],
            "workflows": [{"id": w["id"], "kind": w["kind"], "api": w["api"], "entity": w["entity"]} for w in g.workflows],
            "apis": [{"id": a["id"], "method": a["method"], "path": a["path"]} for a in g.apis],
            "entities": [{"id": e["id"], "fields": [f["name"] for f in e["fields"]]} for e in g.entities],
            "components": [{"id": c["id"], "kind": c["kind"]} for c in g.nodes("components")],
            "requirements": [{"id": r["id"], "text": r["text"]} for r in g.nodes("requirements")],
            "assumptions": [a["text"] for a in g.nodes("assumptions")],
            "open_questions": [q["text"] for q in g.nodes("questions") if q.get("status", "open") != "resolved"],
        }

    def for_architecture(self, analysis: dict) -> dict[str, Any]:
        return {**self.base(), "analysis": {k: analysis[k] for k in ("routes", "features", "screens", "component_refs", "api_refs", "state_machine_refs", "role_refs")}}

    def for_screen(self, screen_ref: str) -> dict[str, Any]:
        ctx = {**self.base(), "target": screen_ref, **self.closure([screen_ref])}
        ctx["acceptance_criteria"] = [a for a in self.g.nodes("acceptance_criteria") if a["workflow"] in {w["id"] for w in ctx.get("workflows", [])}]
        ctx["roles"] = [{"id": r["id"], "key": r["key"], "permissions": r["permissions"]} for r in self.g.roles]
        if self.design_system:
            ctx["design_system_summary"] = design_summary(self.design_system)
        ctx["ui_conventions"] = UI_CONVENTIONS
        return ctx

    def for_component(self, component_ref: str) -> dict[str, Any]:
        ctx = {**self.base(), "target": component_ref, **self.closure([component_ref])}
        if self.design_system:
            ctx["design_system_summary"] = design_summary(self.design_system)
        ctx["ui_conventions"] = UI_CONVENTIONS
        return ctx

    def for_refs(self, refs: Iterable[str]) -> dict[str, Any]:
        """Used by corrections/tests: the slice of the graph behind a set of source refs."""
        return {**self.base(), **self.closure(list(refs))}

    def for_workflow(self, workflow_ref: str) -> dict[str, Any]:
        ctx = {**self.base(), "target": workflow_ref, **self.closure([workflow_ref])}
        ctx["acceptance_criteria"] = [a for a in self.g.nodes("acceptance_criteria") if a["workflow"] == workflow_ref]
        ctx["ui_conventions"] = UI_CONVENTIONS
        return ctx


def design_summary(ds: dict) -> dict:
    return {
        "colors": {k: v for k, v in ds["colors"].items() if isinstance(v, str)},
        "primitives": ds.get("primitives", []),
        "breakpoints": ds.get("breakpoints", {}),
        "responsive": ds.get("responsive", {}),
    }
