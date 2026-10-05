"""Stage 4 - Page planning: one ScreenSpec per graph screen (graph-owned fields are never LLM-controlled)."""
from __future__ import annotations

from app.domain.models.graph import GraphPackage
from app.domain.models.naming import slug
from app.domain.specifications.specs import ScreenSpec
from app.generation.symbols import page_component_name, page_path
from app.pipeline.context import RunContext
from app.validation.route_validation import check_routes

DATA_DRIVEN = {"list", "dashboard", "details"}
ALL_STATES = ["loading", "empty", "error", "success"]


def baseline_states(screen: dict, g: GraphPackage | None = None) -> list[str]:
    if screen["kind"] == "details":
        # a single item has no "empty" state (a missing item is an error); related lists shown on the page do
        related = g is not None and any((c := g.get(r)) and c["kind"] == "table" and c.get("entity") != screen.get("entity") for r in screen.get("components", []))
        return ["loading", "empty", "error", "success"] if related else ["loading", "error", "success"]
    if screen["kind"] in DATA_DRIVEN:
        return list(ALL_STATES)
    return ["loading", "error", "success"] if screen.get("data_sources") else ["error", "success"]


def baseline_responsive(screen: dict) -> dict[str, str]:
    kind = screen["kind"]
    tables = any(True for _ in screen.get("components", []))
    return {
        "desktop": "Content within a 6xl container next to the sidebar; tables show all columns" if kind != "login" else "Centered 28rem card",
        "tablet": "Sidebar stays; grids collapse to two columns; table padding tightens" if kind != "login" else "Centered card",
        "mobile": "Top bar with menu button; single column; tables render as stacked labelled cards; 44px touch targets" if tables and kind != "login" else "Single column full-width card",
    }


def build_screen_spec(g: GraphPackage, screen: dict, ctx: RunContext) -> ScreenSpec:
    clos = ctx.contexts.closure([screen["id"]])
    return ScreenSpec(
        screen_ref=screen["id"], route=screen["route"], layout=screen["layout"], kind=screen["kind"],
        feature=slug(screen.get("feature") or "app"), page_component=page_component_name(screen), page_path=page_path(screen),
        components=list(screen.get("components", [])), data_sources=list(screen.get("data_sources", [])),
        actions=list(screen.get("actions", [])), permissions=list(screen.get("permissions", [])),
        entity_refs=[e["id"] for e in clos.get("entities", [])], states=baseline_states(screen, g),
        responsive=baseline_responsive(screen), notes="",
    )


def _validator(base: ScreenSpec):
    def validate(out: object) -> list[str]:
        if not isinstance(out, dict):
            return ["output must be a JSON object"]
        p: list[str] = []
        if out.get("screen_ref") != base.screen_ref:
            p.append(f"screen_ref must be '{base.screen_ref}'")
        if out.get("route", base.route) != base.route:
            p.append(f"route is graph-owned and must stay '{base.route}'")
        comps = out.get("components", base.components)
        if not isinstance(comps, list) or sorted(comps) != sorted(base.components):
            p.append(f"components must be a reordering of exactly {base.components} (adding/removing components changes the product spec)")
        states = out.get("states", base.states)
        if not isinstance(states, list) or not set(base.states) <= set(states):
            p.append(f"states must include {base.states}")
        elif not set(states) <= set(ALL_STATES) | {"submitting", "forbidden"}:
            p.append(f"unknown states {sorted(set(states) - set(ALL_STATES))}")
        resp = out.get("responsive", base.responsive)
        if not isinstance(resp, dict) or not {"desktop", "tablet", "mobile"} <= set(resp):
            p.append("responsive needs desktop, tablet and mobile")
        for k in ("data_sources", "actions", "permissions"):
            if k in out and sorted(out[k]) != sorted(getattr(base, k)):
                p.append(f"'{k}' is graph-owned and must equal {getattr(base, k)}")
        return p

    return validate


def run(ctx: RunContext) -> list[ScreenSpec]:
    specs: list[ScreenSpec] = []
    for screen in ctx.g.screens:
        base = build_screen_spec(ctx.g, screen, ctx)
        context = {**ctx.contexts.for_screen(screen["id"]), "baseline_spec": base.model_dump(),
                   "architecture": {"layouts": ctx.architecture["layouts"], "feature": base.feature}}
        out = ctx.runner.call("page_planning", context, _validator(base), unit=screen["id"])
        merged = base.model_copy(update={
            "components": out.get("components", base.components),
            "states": list(dict.fromkeys(out.get("states", base.states))),
            "responsive": {**base.responsive, **out.get("responsive", {})},
            "notes": str(out.get("notes", ""))[:1000],
        })
        specs.append(merged)
    issues = check_routes(ctx.g, [s.model_dump() for s in specs])
    if issues:
        from app.domain.models.errors import AgentError, ErrorKind

        raise AgentError(ErrorKind.GRAPH_IMPLEMENTATION_CONFLICT, "; ".join(i.message for i in issues), issues)
    ctx.screen_specs = specs
    ctx.artifacts.save_screen_specs(specs)
    return specs
