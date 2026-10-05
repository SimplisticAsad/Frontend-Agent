"""Stage 2 - Frontend Architecture (no code)."""
from __future__ import annotations

from app.domain.models.graph import GraphPackage
from app.domain.models.naming import slug
from app.pipeline.context import RunContext

STATE_STRATEGIES = {"react_query_plus_local_state", "local_state_only", "react_query_plus_context"}


def build_architecture_baseline(g: GraphPackage, analysis: dict) -> dict:
    modules = []
    for feat, screens in analysis["features"].items():
        comps: list[str] = []
        apis: list[str] = []
        wfs: list[str] = []
        for sref in screens:
            s = g.require(sref)
            comps += [c for c in s.get("components", []) if not (g.get(c) or {}).get("shared")]
            apis += s.get("data_sources", [])
            wfs += s.get("actions", [])
        uniq = lambda xs: list(dict.fromkeys(xs))
        modules.append({"name": feat, "screens": screens, "components": uniq(comps), "api_refs": uniq(apis), "workflow_refs": uniq(wfs)})
    return {
        "application": {
            "router": "react-router", "state_strategy": "react_query_plus_local_state", "styling": "tailwind",
            "forms": "react-hook-form + zod", "api_layer": "typed fetch client (lib/api) + react-query hooks (hooks/queries)",
            "authentication": "AuthProvider context backed by a persisted session; token sent as Bearer",
        },
        "routes": [{"path": s["route"], "screen_ref": s["id"], "layout": s["layout"], "feature": slug(s.get("feature") or "app")} for s in g.screens],
        "layouts": [
            {"name": "PublicLayout", "applies_to": "public", "description": "Centered card for unauthenticated screens"},
            {"name": "AppLayout", "applies_to": "authenticated", "description": "Sidebar navigation from md up; top bar with collapsible menu on mobile"},
        ],
        "providers": ["ErrorBoundary", "QueryClientProvider", "AuthProvider", "NotificationProvider", "RouterProvider"],
        "feature_modules": modules,
        "shared_components": [c["id"] for c in g.nodes("components") if c.get("shared")],
        "error_boundaries": ["Root ErrorBoundary renders a recoverable error state without stack traces"],
        "loading_architecture": "Route-level pages render LoadingState skeletons while queries are pending; mutations disable submit buttons and show spinners",
    }


def _validator(g: GraphPackage, analysis: dict):
    layouts_needed = {s["layout"] for s in g.screens}

    def validate(out: object) -> list[str]:
        if not isinstance(out, dict):
            return ["output must be a JSON object"]
        p: list[str] = []
        app = out.get("application")
        if not isinstance(app, dict) or app.get("router") != "react-router":
            p.append("application.router must be 'react-router'")
        elif app.get("state_strategy") not in STATE_STRATEGIES:
            p.append(f"application.state_strategy must be one of {sorted(STATE_STRATEGIES)}")
        mods = out.get("feature_modules")
        if not isinstance(mods, list) or not mods:
            return p + ["feature_modules must be a non-empty list"]
        assigned: list[str] = []
        for m in mods:
            if not isinstance(m, dict) or not isinstance(m.get("name"), str) or m["name"] != slug(m["name"]):
                p.append("each feature module needs a kebab-case 'name'")
                continue
            assigned += m.get("screens", [])
        want = set(analysis["screens"])
        if set(assigned) != want or len(assigned) != len(want):
            p.append(f"every screen must belong to exactly one feature module (missing={sorted(want - set(assigned))}, extra/duplicate={sorted(set(assigned) - want) or 'duplicates'})")
        applies = {l.get("applies_to") for l in out.get("layouts", []) if isinstance(l, dict)}
        if not layouts_needed <= applies:
            p.append(f"layouts must cover {sorted(layouts_needed)}")
        for key in ("providers", "shared_components"):
            if not isinstance(out.get(key), list):
                p.append(f"'{key}' must be a list")
        for ref in out.get("shared_components", []) if isinstance(out.get("shared_components"), list) else []:
            if not g.has(ref, "components"):
                p.append(f"shared component '{ref}' is not in the graph")
        return p

    return validate


def run(ctx: RunContext) -> dict:
    baseline = build_architecture_baseline(ctx.g, ctx.analysis)
    context = {**ctx.contexts.for_architecture(ctx.analysis), "baseline": baseline}
    out = ctx.runner.call("frontend_architecture", context, _validator(ctx.g, ctx.analysis))
    arch = {**baseline, **{k: v for k, v in out.items() if k in baseline and k != "routes"}}  # routes are graph-owned
    ctx.architecture = arch
    ctx.artifacts.save("frontend_architecture.json", arch)
    return arch
