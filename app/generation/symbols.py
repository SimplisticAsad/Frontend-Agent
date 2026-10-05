"""Deterministic symbol model: how graph ids map to TypeScript names, files and seed data.

Generators, the mock LLM fixtures and the test generators all read from here, so names never drift.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.domain.models.graph import GraphPackage
from app.domain.models.naming import camel, label_of, pascal, plural, slug, tail, words

TS_SCALAR = {
    "string": "string", "text": "string", "email": "string", "password": "string", "date": "string",
    "datetime": "string", "ref": "string", "integer": "number", "number": "number", "boolean": "boolean",
}


def entity_name(entity_ref: str) -> str:
    return pascal(entity_ref)


def entity_plural(entity_ref: str) -> str:
    return plural(entity_name(entity_ref))


def collection_of(entity_ref: str) -> str:
    return slug(plural(camel(entity_ref)))  # entity.project -> projects


def enum_type_name(entity_ref: str, field_name: str) -> str:
    return entity_name(entity_ref) + pascal(field_name)


def field_label(g: GraphPackage, entity_ref: str, name: str) -> str:
    f = g.entity_field(entity_ref, name) or {}
    base = name[:-3] if f.get("type") == "ref" and name.endswith("_id") else name
    return label_of(base)


def ts_field_type(g: GraphPackage, entity_ref: str | None, f: dict) -> str:
    if f.get("type") == "enum":
        if entity_ref and g.entity_field(entity_ref, f["name"]) and g.entity_field(entity_ref, f["name"]).get("values"):
            return enum_type_name(entity_ref, f["name"])
        return " | ".join(f"'{v}'" for v in f.get("values", [])) or "string"
    return TS_SCALAR.get(f.get("type", "string"), "string")


def state_label(state: str) -> str:
    return state.replace("_", " ").capitalize()


@dataclass
class ApiBinding:
    api: dict
    id: str
    method: str
    path: str
    operation: str
    function: str
    hook: str
    resource: str  # file stem under lib/api and hooks/queries
    entity_ref: str | None  # response entity
    request_entity_ref: str | None
    entity: str  # Pascal entity name ("" for none)
    path_params: list[str] = field(default_factory=list)
    body_fields: list[dict] = field(default_factory=list)
    query_fields: list[dict] = field(default_factory=list)
    session_fields: list[dict] = field(default_factory=list)
    shape: str = "none"
    input_type: str | None = None
    params_type: str | None = None
    keys_name: str = ""

    @property
    def returns_ts(self) -> str:
        return {"list": f"{self.entity}[]", "single": self.entity, "none": "void", "session": "Session"}[self.shape]


def _function_name(api: dict, entity: str) -> str:
    op = api["operation"]
    if op == "login":
        return "login"
    if op == "list":
        return f"get{plural(entity)}"
    if op == "get":
        return f"get{entity}"
    if op == "create":
        return f"create{entity}"
    if op == "delete":
        return f"delete{entity}"
    rest = [w for w in words(api["id"]) if w.lower() != entity.lower()]
    return (rest[0] + entity + "".join(w.capitalize() for w in rest[1:])) if rest else f"update{entity}"


def build_api_bindings(g: GraphPackage) -> list[ApiBinding]:
    out: list[ApiBinding] = []
    for a in g.apis:
        resp = a.get("response") or {}
        req = a.get("request") or {}
        ent_ref = resp.get("entity")
        req_ent = req.get("entity") or ent_ref
        if not (ent_ref or req_ent) and a["operation"] != "login":
            guess = f"entity.{words(a['id'])[0]}"  # e.g. api.project.delete -> entity.project
            req_ent = guess if g.has(guess, "entities") else None
        entity = entity_name(ent_ref or req_ent) if (ent_ref or req_ent) else ""
        func = _function_name(a, entity)
        fields = req.get("fields", [])
        path_params = re.findall(r"\{(\w+)\}", a["path"])
        b = ApiBinding(
            api=a, id=a["id"], method=a["method"].upper(), path=a["path"], operation=a["operation"], function=func,
            hook=("useLogin" if a["operation"] == "login" else "use" + (plural(entity) if a["operation"] == "list" else entity if a["operation"] == "get" else pascal(func))),
            resource="auth" if a["operation"] == "login" else collection_of(ent_ref or req_ent),
            entity_ref=ent_ref, request_entity_ref=req_ent, entity=entity, path_params=path_params,
            body_fields=[f for f in fields if f.get("source", "form") in ("form", "input")],
            query_fields=[f for f in fields if f.get("source") == "query"],
            session_fields=[f for f in fields if str(f.get("source", "")).startswith("session.")],
            shape=resp.get("shape", "none"),
        )
        if b.body_fields:
            b.input_type = "LoginInput" if a["operation"] == "login" else f"{pascal(func)[:1].upper()}{pascal(func)[1:]}Input"
        if b.query_fields:
            b.params_type = f"{entity}ListParams"
        b.keys_name = f"{camel(ent_ref or req_ent or 'auth')}Keys"
        out.append(b)
    return out


def binding_by_id(bindings: list[ApiBinding]) -> dict[str, ApiBinding]:
    return {b.id: b for b in bindings}


def list_binding_for_entity(bindings: list[ApiBinding], entity_ref: str) -> ApiBinding | None:
    return next((b for b in bindings if b.operation == "list" and b.entity_ref == entity_ref), None)


def get_binding_for_entity(bindings: list[ApiBinding], entity_ref: str) -> ApiBinding | None:
    return next((b for b in bindings if b.operation == "get" and b.entity_ref == entity_ref), None)


# ---------------- screens / components ----------------
def page_component_name(screen: dict) -> str:
    return pascal(screen["id"]) + "Page"  # screen.project.list -> ProjectListPage


def page_path(screen: dict) -> str:
    return f"src/features/{slug(screen.get('feature') or 'app')}/pages/{page_component_name(screen)}.tsx"


def component_path(comp: dict) -> str:
    if comp.get("shared"):
        return f"src/components/shared/{comp['name']}.tsx"
    return f"src/features/{slug(comp.get('feature') or 'app')}/components/{comp['name']}.tsx"


def import_path(from_file: str, to_file: str) -> str:
    """Relative TS import specifier (no extension) between two src-relative file paths."""
    a = from_file.split("/")[:-1]
    b = to_file.rsplit(".", 1)[0].split("/")
    i = 0
    while i < len(a) and i < len(b) - 1 and a[i] == b[i]:
        i += 1
    ups = len(a) - i
    rel = ["."] if ups == 0 else [".."] * ups
    return "/".join(rel + b[i:])


def workflow_schema_names(wf: dict) -> tuple[str, str, str]:
    base = camel(wf["id"])  # workflow.project.create -> projectCreate
    return f"{base}Schema", f"{pascal(wf['id'])}Values", f"{base}Defaults"


def workflow_schema_file(wf: dict) -> str:
    return f"src/lib/validation/{camel(wf['id'])}.ts"


def machine_for_entity(g: GraphPackage, entity_ref: str) -> dict | None:
    e = g.get(entity_ref) or {}
    return g.get(e["state_machine"]) if e.get("state_machine") else None


def route_path_for(screen: dict, params: dict[str, str] | None = None) -> str:
    r = screen["route"]
    for k, v in (params or {}).items():
        r = r.replace(f":{k}", v)
    return r


# ---------------- seed data (used by generated e2e mock API + tests) ----------------
SEED_NAMES = ["Alpha", "Beta", "Gamma", "Delta"]


@dataclass
class Seed:
    collections: dict[str, list[dict[str, Any]]]
    credentials: list[dict[str, str]]  # email/password/user_id/role


def seed_data(g: GraphPackage) -> Seed:
    """Deterministic fixtures: one user per role (+ a second user of the last role), 3 rows per other entity."""
    user_ent = next((e for e in g.entities if {"email", "role", "name"} <= {f["name"] for f in e["fields"]}), None)
    cols: dict[str, list[dict]] = {}
    creds: list[dict[str, str]] = []
    if user_ent:
        users = []
        keys = [r["key"] for r in g.roles]
        for key in keys + [keys[-1] + "2"]:
            role = key.rstrip("2")
            users.append({"id": f"user-{key}", "name": f"{label_of(key.rstrip('2'))} {'Two' if key.endswith('2') else 'User'}", "email": f"{key}@example.com", "role": role})
            creds.append({"email": f"{key}@example.com", "password": "Password123!", "user_id": f"user-{key}", "role": role})
        cols[collection_of(user_ent["id"])] = users
    order = [e for e in g.entities if not e.get("transient") and e is not user_ent]
    # entities referencing others come after the referenced ones
    order.sort(key=lambda e: sum(1 for f in e["fields"] if f["type"] == "ref"))
    for ent in order:
        rows = []
        for i in range(3):
            row: dict[str, Any] = {}
            for f in ent["fields"]:
                row[f["name"]] = _sample(g, ent, f, i, cols, user_ent)
            rows.append(row)
        cols[collection_of(ent["id"])] = rows
    return Seed(cols, creds)


def _sample(g: GraphPackage, ent: dict, f: dict, i: int, cols: dict, user_ent: dict | None) -> Any:
    n, t = f["name"], f["type"]
    if n == "id":
        return f"{slug(ent['id'])}-{i + 1}"
    if t == "ref":
        target = cols.get(collection_of(f["ref"]), [])
        if not target:
            return None
        if user_ent and f["ref"] == user_ent["id"]:
            if f.get("readonly"):
                return target[0]["id"]  # owner-style fields: first user (the manager)
            return target[(i + 1) % len(target)]["id"]  # assignee-style: employee, employee2, manager
        return target[i % len(target)]["id"]
    if t == "enum":
        sm = machine_for_entity(g, ent["id"])
        vals = sm["states"] if sm and sm["field"] == n else f["values"]
        return vals[i % len(vals)]
    if t == "datetime":
        return f"2030-01-0{i + 1}T09:00:00.000Z"
    if t == "date":
        return f"2030-02-0{i + 1}"
    if t == "email":
        return f"seed{i + 1}@example.com"
    if t in ("integer", "number"):
        return i + 1
    if t == "boolean":
        return i % 2 == 0
    if n == ent.get("display_field"):
        return f"{ent['name']} {SEED_NAMES[i]}"
    if t == "text":
        return f"{ent['name']} {SEED_NAMES[i]} description"
    return f"{label_of(n)} {SEED_NAMES[i]}"


# ---------------- hook signatures ----------------
def mutation_var_type(b: ApiBinding) -> str:
    """TypeScript type of the variable passed to `mutate(...)` for a mutation hook."""
    if b.path_params and b.input_type:
        fields = "; ".join([f"{p}: string" for p in b.path_params] + [f"input: {b.input_type}"])
        return "{ " + fields + " }"
    if b.path_params:
        return "string" if len(b.path_params) == 1 else "{ " + "; ".join(f"{p}: string" for p in b.path_params) + " }"
    return b.input_type or "void"


def hook_signature(b: ApiBinding) -> str:
    if b.operation == "list":
        arg = f"params?: {b.params_type}" if b.params_type else ""
        return f"{b.hook}({arg}): UseQueryResult<{b.returns_ts}, ApiError>"
    if b.operation == "get":
        return f"{b.hook}(id: string | undefined): UseQueryResult<{b.returns_ts}, ApiError>"
    return f"{b.hook}(): UseMutationResult<{b.returns_ts}, ApiError, {mutation_var_type(b)}>"


def api_signature(b: ApiBinding) -> str:
    args = [f"{p}: string" for p in b.path_params]
    if b.input_type:
        args.append(f"input: {b.input_type}")
    if b.params_type:
        args.append(f"params?: {b.params_type}")
    if b.method == "GET":
        args.append("signal?: AbortSignal")
    return f"{b.function}({', '.join(args)}): Promise<{b.returns_ts}>"
