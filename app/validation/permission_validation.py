"""Permission model checks: the frontend only reflects graph-defined permissions."""
from __future__ import annotations

from app.domain.models.errors import ErrorKind, Issue
from app.domain.models.graph import GraphPackage


def role_permissions(g: GraphPackage) -> dict[str, set[str]]:
    """role key -> permission ids, from both roles.permissions and permissions.roles."""
    out: dict[str, set[str]] = {}
    by_id = {r["id"]: r["key"] for r in g.roles}
    for r in g.roles:
        out.setdefault(r["key"], set()).update(r["permissions"])
    for p in g.permissions:
        for rid in p["roles"]:
            if rid in by_id:
                out[by_id[rid]].add(p["id"])
    return out


def check_permissions(g: GraphPackage) -> list[Issue]:
    issues: list[Issue] = []
    by_id = {r["id"]: r for r in g.roles}
    for p in g.permissions:
        for rid in p["roles"]:
            role = by_id.get(rid)
            if role and p["id"] not in role["permissions"]:
                issues.append(
                    Issue(ErrorKind.GRAPH_ERROR, "permission_asymmetry", f"{p['id']} lists {rid} but the role does not list the permission", [p["id"], rid], severity="warning")
                )
    for wf in g.workflows:
        perm = wf.get("permission")
        if perm and not g.has(perm, "permissions"):
            issues.append(Issue(ErrorKind.GRAPH_ERROR, "missing_permission", f"{wf['id']} references unknown permission {perm}", [wf["id"], perm]))
    return issues
