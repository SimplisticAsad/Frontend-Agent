"""Component prop contracts per component kind. Planning may *add* props; it may never rename or drop these,
because pages, tests and the generated code all rely on them."""
from __future__ import annotations

from app.domain.models.graph import GraphPackage
from app.domain.models.naming import camel
from app.generation.symbols import entity_name, entity_plural, enum_type_name

KIND_PRIMITIVES = {
    "page_header": [],
    "table": ["Table", "Badge", "Pagination", "Button"],
    "form": ["Input", "Textarea", "Select", "Button", "Alert"],
    "stats": ["Card"],
    "status_badge": ["Badge"],
    "status_control": ["Select", "Button", "Alert"],
}
KIND_STATES = {
    "page_header": [],
    "table": ["empty-capable", "paginated"],
    "form": ["idle", "submitting", "validation-error", "server-error"],
    "stats": ["zero-values"],
    "status_badge": [],
    "status_control": ["idle", "pending", "error", "no-transitions"],
}
KIND_A11Y = {
    "page_header": ["single h1 per page"],
    "table": ["semantic table roles", "labelled stacked cards on mobile", "links for row navigation", "buttons for row actions"],
    "form": ["visible labels linked to controls", "errors announced with role=alert", "required fields marked", "submit/cancel are buttons"],
    "stats": ["definition list semantics for label/value pairs"],
    "status_badge": ["text label, never colour only"],
    "status_control": ["labelled select", "disabled while pending"],
}


def component_props(g: GraphPackage, comp: dict) -> dict[str, str]:
    kind = comp["kind"]
    ent = comp.get("entity")
    if kind == "page_header":
        return {"title": "string", "description": "string | undefined", "actions": "ReactNode | undefined"}
    if kind == "table":
        e, props = entity_name(ent), {}
        props["items"] = f"{e}[]"
        props["lookups"] = "Lookups | undefined"
        if comp.get("row_actions"):
            props["onDelete"] = f"((item: {e}) => void) | undefined"
            props["deletingId"] = "string | null | undefined"
        return props
    if kind == "form":
        wf = g.get(comp["workflow"])
        props = {"onSubmit": "(values: Values) => void", "isSubmitting": "boolean", "serverError": "string | null", "fieldErrors": "Record<string, string>"}
        if wf["kind"] != "login":
            props["onCancel"] = "() => void"
        if any((g.entity_field(wf["entity"], f) or {}).get("type") == "ref" for f in wf.get("form_fields", [])):
            props["refOptions"] = "Record<string, SelectOption[]>"
        return props
    if kind == "stats":
        return {stats_prop(e): f"{entity_name(e)}[]" for e in comp.get("entities", [])}
    if kind == "status_badge":
        sm = g.get(comp["state_machine"])
        return {"status": enum_type_name(sm["entity"], sm["field"])}
    if kind == "status_control":
        sm = g.get(comp["state_machine"])
        e = entity_name(sm["entity"])
        t = enum_type_name(sm["entity"], sm["field"])
        return {camel(sm["entity"]): e, "allowed": f"{t}[]", "onTransition": f"(to: {t}) => void", "isPending": "boolean", "error": "string | null"}
    return {}


def stats_prop(entity_ref: str) -> str:
    p = entity_plural(entity_ref)
    return p[:1].lower() + p[1:]
