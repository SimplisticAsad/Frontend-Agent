"""Structural + referential validation of the graph package. Any error => GRAPH_ERROR => STOP."""
from __future__ import annotations

from collections import Counter

from app.domain.models.errors import ErrorKind, GraphError, Issue
from app.domain.models.graph import GraphPackage

FIELD_TYPES = {"string", "text", "integer", "number", "boolean", "date", "datetime", "enum", "ref", "email", "password"}
REQUIRED_KEYS = {
    "project": ["name"],
    "actors": ["name"],
    "roles": ["key", "name", "permissions"],
    "entities": ["name", "fields"],
    "relationships": ["from", "to"],
    "capabilities": ["name"],
    "requirements": ["text"],
    "screens": ["name", "route", "layout", "kind"],
    "components": ["name", "kind"],
    "workflows": ["name", "kind", "entity", "api"],
    "api": ["method", "path", "operation"],
    "permissions": ["action", "resource", "roles"],
    "validations": ["entity", "field", "rules"],
    "state_machines": ["entity", "field", "states", "initial", "transitions"],
    "dependencies": ["from", "to"],
    "acceptance_criteria": ["title", "workflow", "type"],
    "assumptions": ["text"],
    "questions": ["text"],
}
ID_PREFIX = {
    "project": "project.", "actors": "actor.", "roles": "role.", "entities": "entity.", "relationships": "rel.",
    "capabilities": "capability.", "requirements": "req.", "screens": "screen.", "components": "component.",
    "workflows": "workflow.", "api": "api.", "permissions": "permission.", "validations": "validation.",
    "state_machines": "sm.", "dependencies": "dep.", "acceptance_criteria": "ac.", "assumptions": "assumption.",
    "questions": "question.",
}
LAYOUTS = {"public", "authenticated"}
SCREEN_KINDS = {"login", "dashboard", "list", "form", "details"}
COMPONENT_KINDS = {"page_header", "form", "stats", "table", "status_badge", "status_control"}
WORKFLOW_KINDS = {"login", "create", "delete", "transition"}
API_OPS = {"login", "list", "get", "create", "delete", "transition"}
AC_TYPES = {"workflow_success", "validation_failure", "workflow_denied", "transition_allowed", "transition_denied"}


class _Collector:
    def __init__(self, g: GraphPackage):
        self.g = g
        self.issues: list[Issue] = []

    def err(self, code: str, msg: str, refs: list[str] | None = None, loc: str | None = None) -> None:
        self.issues.append(Issue(ErrorKind.GRAPH_ERROR, code, msg, refs or [], loc))

    def warn(self, code: str, msg: str, refs: list[str] | None = None) -> None:
        self.issues.append(Issue(ErrorKind.GRAPH_ERROR, code, msg, refs or [], None, "warning"))

    def ref(self, owner: str, ref: object, graph: str | None, what: str) -> None:
        """Assert `ref` exists (and is in `graph` when given)."""
        if not isinstance(ref, str) or not self.g.has(ref, graph):
            self.err("dangling_ref", f"{owner}: {what} '{ref}' does not exist" + (f" in {graph}" if graph else ""), [owner, str(ref)])


def validate_graph(g: GraphPackage) -> list[Issue]:
    c = _Collector(g)
    _structure(c)
    if not any(i.severity == "error" for i in c.issues):
        _references(c)
        _semantics(c)
    return c.issues


def assert_valid(g: GraphPackage) -> list[Issue]:
    """Raise GraphError on errors; return warnings."""
    issues = validate_graph(g)
    errors = [i for i in issues if i.severity == "error"]
    if errors:
        raise GraphError(errors)
    return issues


def _structure(c: _Collector) -> None:
    g = c.g
    ids: Counter[str] = Counter()
    for gname, nodes in g.graphs.items():
        for n in nodes:
            nid = n.get("id")
            if not isinstance(nid, str) or not nid.startswith(ID_PREFIX[gname]):
                c.err("bad_id", f"{gname}: node id '{nid}' must start with '{ID_PREFIX[gname]}'", [str(nid)])
                continue
            ids[nid] += 1
            for key in REQUIRED_KEYS[gname]:
                if key not in n:
                    c.err("missing_key", f"{nid}: missing required key '{key}'", [nid])
    for nid, count in ids.items():
        if count > 1:
            c.err("duplicate_id", f"Duplicate node id '{nid}'", [nid])
    for must in ("screens", "workflows", "api", "entities", "roles", "permissions"):
        if not g.nodes(must):
            c.err("empty_graph", f"Graph '{must}' has no nodes")


def _references(c: _Collector) -> None:
    g = c.g
    for r in g.nodes("roles"):
        for p in r["permissions"]:
            c.ref(r["id"], p, "permissions", "permission")
    for p in g.nodes("permissions"):
        for r in p["roles"]:
            c.ref(p["id"], r, "roles", "role")
    for e in g.nodes("entities"):
        for f in e["fields"]:
            if f.get("type") not in FIELD_TYPES:
                c.err("bad_field_type", f"{e['id']}.{f.get('name')}: unknown type '{f.get('type')}'", [e["id"]])
            if f.get("type") == "ref":
                c.ref(e["id"], f.get("ref"), "entities", f"field '{f.get('name')}' ref")
            if f.get("type") == "enum" and not f.get("values"):
                c.err("enum_values", f"{e['id']}.{f.get('name')}: enum needs 'values'", [e["id"]])
        if e.get("state_machine"):
            c.ref(e["id"], e["state_machine"], "state_machines", "state_machine")
    for rel in g.nodes("relationships"):
        c.ref(rel["id"], rel["from"], "entities", "from")
        c.ref(rel["id"], rel["to"], "entities", "to")
    for cap in g.nodes("capabilities"):
        for r in cap.get("roles", []):
            c.ref(cap["id"], r, "roles", "role")
        if cap.get("workflow"):
            c.ref(cap["id"], cap["workflow"], "workflows", "workflow")
    for rq in g.nodes("requirements"):
        for cap in rq.get("capabilities", []):
            c.ref(rq["id"], cap, "capabilities", "capability")
    for s in g.nodes("screens"):
        sid = s["id"]
        if s.get("entity"):
            c.ref(sid, s["entity"], "entities", "entity")
        for x in s.get("components", []):
            c.ref(sid, x, "components", "component")
        for x in s.get("data_sources", []):
            c.ref(sid, x, "api", "data source")
        for x in s.get("actions", []):
            c.ref(sid, x, "workflows", "workflow")
        for x in s.get("permissions", []):
            c.ref(sid, x, "permissions", "permission")
    for comp in g.nodes("components"):
        for key, gr in (("entity", "entities"), ("workflow", "workflows"), ("state_machine", "state_machines"), ("link_to", "screens")):
            if comp.get(key):
                c.ref(comp["id"], comp[key], gr, key)
        for x in comp.get("entities", []):
            c.ref(comp["id"], x, "entities", "entity")
        for x in comp.get("row_actions", []):
            c.ref(comp["id"], x, "workflows", "row action")
    for w in g.nodes("workflows"):
        wid = w["id"]
        c.ref(wid, w["entity"], "entities", "entity")
        c.ref(wid, w["api"], "api", "api")
        if w.get("permission"):
            c.ref(wid, w["permission"], "permissions", "permission")
        if w.get("screen"):
            c.ref(wid, w["screen"], "screens", "screen")
        if w.get("state_machine"):
            c.ref(wid, w["state_machine"], "state_machines", "state_machine")
        trig = w.get("trigger") or {}
        if trig.get("screen"):
            c.ref(wid, trig["screen"], "screens", "trigger screen")
        nav = (w.get("success") or {}).get("navigate")
        if nav:
            c.ref(wid, nav, "screens", "success navigation target")
        for fname in w.get("form_fields", []):
            if g.get(w["entity"]) and not g.entity_field(w["entity"], fname):
                c.err("unknown_field", f"{wid}: form field '{fname}' is not a field of {w['entity']}", [wid, w["entity"]])
    for a in g.nodes("api"):
        aid = a["id"]
        if a.get("permission"):
            c.ref(aid, a["permission"], "permissions", "permission")
        ent = (a.get("response") or {}).get("entity")
        if ent:
            c.ref(aid, ent, "entities", "response entity")
        if (a.get("request") or {}).get("entity"):
            c.ref(aid, a["request"]["entity"], "entities", "request entity")
    for v in g.nodes("validations"):
        c.ref(v["id"], v["entity"], "entities", "entity")
        if g.get(v["entity"]) and not g.entity_field(v["entity"], v["field"]):
            c.err("unknown_field", f"{v['id']}: field '{v['field']}' not on {v['entity']}", [v["id"]])
    for sm in g.nodes("state_machines"):
        c.ref(sm["id"], sm["entity"], "entities", "entity")
        for t in sm["transitions"]:
            for end in ("from", "to"):
                if t.get(end) not in sm["states"]:
                    c.err("bad_transition", f"{sm['id']}: transition state '{t.get(end)}' not in states", [sm["id"]])
            if t.get("permission"):
                c.ref(sm["id"], t["permission"], "permissions", "transition permission")
        if sm["initial"] not in sm["states"]:
            c.err("bad_initial", f"{sm['id']}: initial state not in states", [sm["id"]])
    for d in g.nodes("dependencies"):
        c.ref(d["id"], d["from"], None, "from")
        c.ref(d["id"], d["to"], None, "to")
    for ac in g.nodes("acceptance_criteria"):
        c.ref(ac["id"], ac["workflow"], "workflows", "workflow")
        if ac.get("role"):
            c.ref(ac["id"], ac["role"], "roles", "role")


def _semantics(c: _Collector) -> None:
    g = c.g
    routes: Counter[str] = Counter()
    for s in g.nodes("screens"):
        if not str(s["route"]).startswith("/"):
            c.err("bad_route", f"{s['id']}: route must start with '/'", [s["id"]])
        routes[s["route"]] += 1
        if s["layout"] not in LAYOUTS:
            c.err("bad_layout", f"{s['id']}: unknown layout '{s['layout']}'", [s["id"]])
        if s["kind"] not in SCREEN_KINDS:
            c.err("bad_screen_kind", f"{s['id']}: unsupported screen kind '{s['kind']}'", [s["id"]])
    for r, n in routes.items():
        if n > 1:
            c.err("duplicate_route", f"Route '{r}' used by {n} screens")
    for comp in g.nodes("components"):
        if comp["kind"] not in COMPONENT_KINDS:
            c.err("bad_component_kind", f"{comp['id']}: unsupported component kind '{comp['kind']}'", [comp["id"]])
    for w in g.nodes("workflows"):
        if w["kind"] not in WORKFLOW_KINDS:
            c.err("bad_workflow_kind", f"{w['id']}: unsupported workflow kind '{w['kind']}'", [w["id"]])
        if w["kind"] in ("create", "login") and not w.get("form_fields"):
            c.err("workflow_no_form", f"{w['id']}: {w['kind']} workflow needs form_fields", [w["id"]])
        if w["kind"] == "create" and not (w.get("screen") and (w.get("trigger") or {}).get("screen")):
            c.err("workflow_no_screen", f"{w['id']}: create workflow needs 'screen' and 'trigger.screen'", [w["id"]])
        if w["kind"] != "login" and not w.get("permission"):
            c.err("workflow_no_permission", f"{w['id']}: workflow must reference a permission", [w["id"]])
        if w["kind"] == "transition" and not (w.get("state_machine") and w.get("field")):
            c.err("workflow_no_sm", f"{w['id']}: transition workflow needs state_machine and field", [w["id"]])
    for a in g.nodes("api"):
        if a["operation"] not in API_OPS:
            c.err("bad_api_op", f"{a['id']}: unsupported operation '{a['operation']}'", [a["id"]])
        if a.get("auth", True) and not a.get("permission"):
            c.err("api_no_permission", f"{a['id']}: authenticated API needs a permission reference", [a["id"]])
    for ac in g.nodes("acceptance_criteria"):
        if ac["type"] not in AC_TYPES:
            c.err("bad_ac_type", f"{ac['id']}: unsupported acceptance type '{ac['type']}'", [ac["id"]])
    # every workflow must be reachable from a screen (trigger screen, form screen, or listed action)
    reachable = {a for s in g.nodes("screens") for a in s.get("actions", [])}
    for w in g.nodes("workflows"):
        if w["id"] not in reachable:
            c.err("workflow_unreachable", f"{w['id']} is not an action of any screen", [w["id"]])
    for q in g.nodes("questions"):
        if q.get("blocking") and q.get("status", "open") == "open":
            c.err("blocking_question", f"{q['id']}: blocking question is still open", [q["id"]])
        elif q.get("status", "open") == "open":
            c.warn("open_question", f"{q['id']}: open question: {q['text']}", [q["id"]])
