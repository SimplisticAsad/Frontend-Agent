"""graph screen -> frontend screen spec -> React route must be 1:1 (spec 15)."""
from __future__ import annotations

from app.domain.models.errors import ErrorKind, Issue
from app.domain.models.graph import GraphPackage


def check_routes(g: GraphPackage, screen_specs: list[dict], router_routes: list[str] | None = None) -> list[Issue]:
    issues: list[Issue] = []
    graph_routes = {s["id"]: s["route"] for s in g.screens}
    spec_routes = {sp["screen_ref"]: sp["route"] for sp in screen_specs}
    for sid, route in graph_routes.items():
        if sid not in spec_routes:
            issues.append(Issue(ErrorKind.GRAPH_IMPLEMENTATION_CONFLICT, "missing_route", f"Screen {sid} has no frontend screen specification", [sid]))
        elif spec_routes[sid] != route:
            issues.append(Issue(ErrorKind.GRAPH_IMPLEMENTATION_CONFLICT, "route_mismatch", f"{sid}: spec route {spec_routes[sid]} != graph route {route}", [sid]))
    for sid in spec_routes:
        if sid not in graph_routes:
            issues.append(Issue(ErrorKind.GRAPH_IMPLEMENTATION_CONFLICT, "orphan_route", f"Screen spec {sid} has no graph screen", [sid]))
    if router_routes is not None:
        expected = set(graph_routes.values())
        for r in set(router_routes) - expected - {"*", "/"}:
            issues.append(Issue(ErrorKind.GRAPH_IMPLEMENTATION_CONFLICT, "orphan_route", f"Router route {r} maps to no graph screen", [r]))
        for r in expected - set(router_routes):
            issues.append(Issue(ErrorKind.GRAPH_IMPLEMENTATION_CONFLICT, "missing_route", f"Graph route {r} is not registered in the router", [r]))
    return issues
