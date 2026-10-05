"""Stage 1 - Graph Analysis. Deterministic extraction of everything the frontend needs, with graph refs;
the LLM adds risks and implementation notes but cannot change the refs."""
from __future__ import annotations

from app.domain.models.graph import GraphPackage
from app.domain.models.naming import slug
from app.graph.context_builder import ContextBuilder
from app.pipeline.context import RunContext


def build_analysis(g: GraphPackage) -> dict:
    cb = ContextBuilder(g)
    features: dict[str, list[str]] = {}
    for s in g.screens:
        features.setdefault(slug(s.get("feature") or "app"), []).append(s["id"])
    trace = {}
    for s in g.screens:
        c = cb.closure([s["id"]])
        trace[s["id"]] = {
            "workflows": [x["id"] for x in c.get("workflows", [])],
            "apis": [x["id"] for x in c.get("apis", [])],
            "entities": [x["id"] for x in c.get("entities", [])],
            "permissions": [x["id"] for x in c.get("permissions", [])],
            "components": [x["id"] for x in c.get("components", [])],
        }
    return {
        "project": g.project_id,
        "graph_version": g.graph_version,
        "routes": [s["route"] for s in g.screens],
        "screens": [s["id"] for s in g.screens],
        "screen_routes": {s["id"]: s["route"] for s in g.screens},
        "workflow_refs": [w["id"] for w in g.workflows],
        "component_refs": [c["id"] for c in g.nodes("components")],
        "api_refs": [a["id"] for a in g.apis],
        "entity_refs": [e["id"] for e in g.entities],
        "permission_refs": [p["id"] for p in g.permissions],
        "state_machine_refs": [s["id"] for s in g.nodes("state_machines")],
        "validation_refs": [v["id"] for v in g.nodes("validations")],
        "role_refs": [r["id"] for r in g.roles],
        "acceptance_criteria_refs": [a["id"] for a in g.nodes("acceptance_criteria")],
        "features": features,
        "traceability": trace,
    }


def _validate(out: object) -> list[str]:
    if not isinstance(out, dict):
        return ["output must be a JSON object"]
    p = []
    if not isinstance(out.get("summary"), str) or not out["summary"].strip():
        p.append("'summary' must be a non-empty string")
    for k in ("risks", "implementation_notes"):
        if not isinstance(out.get(k), list) or not all(isinstance(x, str) for x in out[k]):
            p.append(f"'{k}' must be a list of strings")
    return p


def run(ctx: RunContext) -> dict:
    g = ctx.g
    baseline = build_analysis(g)
    context = {**ctx.contexts.for_analysis(), "extracted": {k: v for k, v in baseline.items() if k not in ("traceability", "screen_routes")}}
    review = ctx.runner.call("graph_analysis", context, _validate)
    analysis = {**baseline, "llm_review": {k: review[k] for k in ("summary", "risks", "implementation_notes")}}
    ctx.analysis = analysis
    ctx.artifacts.save("frontend_analysis.json", analysis)
    return analysis
