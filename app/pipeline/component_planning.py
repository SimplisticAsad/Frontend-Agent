"""Stage 5 - Component planning: one ComponentSpec per graph component, placed by deterministic rules."""
from __future__ import annotations

from app.domain.models.graph import GraphPackage
from app.domain.models.naming import slug
from app.domain.specifications.specs import ComponentSpec
from app.generation.component_contracts import KIND_A11Y, KIND_PRIMITIVES, KIND_STATES, component_props
from app.generation.symbols import build_api_bindings, component_path
from app.pipeline.context import RunContext


def build_component_spec(g: GraphPackage, comp: dict, ctx: RunContext) -> ComponentSpec:
    clos = ctx.contexts.closure([comp["id"]])
    wf_refs = [x for x in [comp.get("workflow")] + comp.get("row_actions", []) if x]
    api_refs = [a["id"] for a in clos.get("apis", [])] if comp["kind"] != "stats" else []
    return ComponentSpec(
        component_ref=comp["id"], name=comp["name"], kind=comp["kind"], scope="shared" if comp.get("shared") else "feature",
        feature=None if comp.get("shared") else slug(comp.get("feature") or "app"), path=component_path(comp),
        props=component_props(g, comp), primitives=KIND_PRIMITIVES.get(comp["kind"], []),
        entity_refs=[e["id"] for e in clos.get("entities", [])], workflow_refs=wf_refs, api_refs=api_refs,
        states=KIND_STATES.get(comp["kind"], []), accessibility=KIND_A11Y.get(comp["kind"], []),
    )


def _validator(baseline: dict[str, ComponentSpec], primitives: set[str]):
    def validate(out: object) -> list[str]:
        items = out.get("components") if isinstance(out, dict) else None
        if not isinstance(items, list):
            return ["output must be {\"components\": [...]}"]
        p: list[str] = []
        seen = {i.get("component_ref") for i in items if isinstance(i, dict)}
        if seen != set(baseline):
            p.append(f"must plan exactly the graph components; missing={sorted(set(baseline) - seen)} unknown={sorted(seen - set(baseline))}")
        for i in items:
            if not isinstance(i, dict) or i.get("component_ref") not in baseline:
                continue
            base = baseline[i["component_ref"]]
            props = i.get("props", base.props)
            if not isinstance(props, dict) or not set(base.props) <= set(props):
                p.append(f"{base.name}: props must keep the contract props {sorted(base.props)}")
            bad = set(i.get("primitives", [])) - primitives
            if bad:
                p.append(f"{base.name}: unknown design primitives {sorted(bad)}")
        return p

    return validate


def run(ctx: RunContext) -> list[ComponentSpec]:
    baseline = {c["id"]: build_component_spec(ctx.g, c, ctx) for c in ctx.g.nodes("components")}
    prims = set(ctx.design_system.get("primitives", [])) | {"Field", "Spinner", "Skeleton"}
    context = {**ctx.contexts.base(), "baseline_components": [b.model_dump() for b in baseline.values()],
               "design_primitives": sorted(prims), "architecture": {"feature_modules": ctx.architecture["feature_modules"]}}
    out = ctx.runner.call("component_planning", context, _validator(baseline, prims))
    specs: list[ComponentSpec] = []
    for item in out["components"]:
        base = baseline[item["component_ref"]]
        specs.append(base.model_copy(update={
            "props": {**item.get("props", {}), **base.props},
            "primitives": list(dict.fromkeys(base.primitives + item.get("primitives", []))),
            "states": list(dict.fromkeys(base.states + item.get("states", []))),
            "accessibility": list(dict.fromkeys(base.accessibility + item.get("accessibility", []))),
            "notes": str(item.get("notes", ""))[:1000],
        }))
    ctx.component_specs = sorted(specs, key=lambda s: s.name)
    ctx.artifacts.save_component_specs(ctx.component_specs)
    return ctx.component_specs
