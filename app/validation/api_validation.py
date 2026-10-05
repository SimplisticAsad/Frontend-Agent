"""API contract coverage: the frontend must be able to supply every required request field (spec 43)."""
from __future__ import annotations

from app.domain.models.errors import ErrorKind, Issue
from app.domain.models.graph import GraphPackage

SUPPLIED_SOURCES = {"path", "query", "input", "session.user_id", "session.role", "constant"}


def check_api_coverage(g: GraphPackage) -> list[Issue]:
    """Return GRAPH_IMPLEMENTATION_CONFLICT issues when a required request field has no UI/data source."""
    issues: list[Issue] = []
    for wf in g.workflows:
        api = g.get(wf["api"])
        if not api:
            continue
        form_fields = set(wf.get("form_fields", []))
        for rf in (api.get("request") or {}).get("fields", []):
            if not rf.get("required"):
                continue
            src = rf.get("source", "form")
            if src == "form" and rf["name"] not in form_fields:
                issues.append(
                    Issue(
                        ErrorKind.GRAPH_IMPLEMENTATION_CONFLICT,
                        "request_field_unsupplied",
                        f"{api['id']} requires '{rf['name']}' but {wf['id']} form does not supply it and the graph names no other source",
                        [api["id"], wf["id"]],
                    )
                )
            elif src not in SUPPLIED_SOURCES and src != "form":
                issues.append(Issue(ErrorKind.GRAPH_ERROR, "unknown_source", f"{api['id']}.{rf['name']}: unknown source '{src}'", [api["id"]]))
        # every form field must be accepted by the API (no invented fields)
        accepted = {f["name"] for f in (api.get("request") or {}).get("fields", [])}
        for fname in form_fields:
            if fname not in accepted:
                issues.append(
                    Issue(ErrorKind.GRAPH_IMPLEMENTATION_CONFLICT, "form_field_not_in_api", f"{wf['id']} form field '{fname}' is not accepted by {api['id']}", [wf["id"], api["id"]])
                )
        # ref fields in forms need a list API on the form screen to populate options
        scr = g.get(wf["screen"]) if wf.get("screen") else None
        if scr:
            for fname in form_fields:
                fld = g.entity_field(wf["entity"], fname) or {}
                if fld.get("type") == "ref":
                    needed = list_api_for_entity(g, fld["ref"])
                    if needed is None or needed["id"] not in scr.get("data_sources", []):
                        issues.append(
                            Issue(
                                ErrorKind.GRAPH_IMPLEMENTATION_CONFLICT,
                                "ref_options_unavailable",
                                f"{scr['id']} must list the list-API of {fld['ref']} in data_sources to populate '{fname}'",
                                [scr["id"], fld["ref"]],
                            )
                        )
    return issues


def list_api_for_entity(g: GraphPackage, entity_ref: str) -> dict | None:
    return next(
        (a for a in g.apis if a["operation"] == "list" and (a.get("response") or {}).get("entity") == entity_ref),
        None,
    )
