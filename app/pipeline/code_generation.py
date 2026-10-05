"""Stage 8 - Incremental code generation.

Deterministic modules (types, API clients, zod schemas, permissions, routes, ...) are written by Python first.
The LLM then writes feature code in small *units* (hooks, one component, one page, one test file) in dependency
order. Each unit has a fixed set of allowed output paths, a deterministic source-ref list and its own cache key,
so a single page or component can be regenerated without touching anything else.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from app.domain.models.errors import AgentError, ErrorKind
from app.domain.models.naming import slug, tail
from app.domain.specifications.specs import FileRecord, TestRecord
from app.generation.catalog import build_catalog
from app.generation.project_generator import ProjectGenerator
from app.generation.symbols import seed_data
from app.pipeline.context import RunContext
from app.validation.frontend_validation import check_generated_source

COMPONENT_ORDER = {"page_header": 0, "status_badge": 1, "status_control": 2, "table": 3, "form": 4, "stats": 5}
UNIT_TESTED_KINDS = {"form", "table", "status_badge", "status_control"}


@dataclass
class Unit:
    id: str
    type: str  # hooks | component | page | unit_test | e2e | visual
    title: str
    expected_paths: list[str]
    source_refs: list[str]
    spec: dict = field(default_factory=dict)
    test: TestRecord | None = None


def closure_refs(ctx: RunContext, seeds: list[str]) -> list[str]:
    """Seeds plus everything they transitively depend on in the graph (roles are noise for traceability)."""
    clos = ctx.contexts.closure([s for s in seeds if s])
    refs = [n["id"] for nodes in clos.values() for n in nodes if not n["id"].startswith("role.")]
    return list(dict.fromkeys([s for s in seeds if s] + refs))


def plan_units(ctx: RunContext) -> list[Unit]:
    g = ctx.g
    units: list[Unit] = []
    # 1. hooks per resource
    by_res: dict[str, list] = {}
    for b in ctx.bindings:
        by_res.setdefault(b.resource, []).append(b)
    for res, bs in by_res.items():
        units.append(Unit(f"hooks:{res}", "hooks", f"Query/mutation hooks for {res}", [f"src/hooks/queries/{res}.ts"],
                          [b.id for b in bs] + [b.entity_ref for b in bs if b.entity_ref], {"resource": res}))
    # 2. components: shared first, simple before composite
    for c in sorted(ctx.component_specs, key=lambda c: (c.scope != "shared", COMPONENT_ORDER.get(c.kind, 9), c.name)):
        refs = closure_refs(ctx, [c.component_ref]) if c.component_ref else []
        units.append(Unit(f"component:{c.component_ref}", "component", f"Component {c.name}", [c.path], refs, {"component_ref": c.component_ref}))
    # 3. pages
    for s in ctx.screen_specs:
        refs = closure_refs(ctx, [s.screen_ref, *s.actions, *s.data_sources, *s.permissions, *s.components])
        units.append(Unit(f"page:{s.screen_ref}", "page", f"Page {s.page_component}", [s.page_path], refs, {"screen_ref": s.screen_ref}))
    # 4. unit tests
    for c in ctx.component_specs:
        if c.kind in UNIT_TESTED_KINDS:
            path = f"tests/unit/{c.name}.test.tsx"
            rec = TestRecord(id=f"test.unit.{slug(c.name)}", type="unit", path=path, source_refs=[c.component_ref, *c.workflow_refs, *c.entity_refs], description=f"{c.name} renders, validates and respects its contract")
            units.append(Unit(f"unit_test:{c.component_ref}", "unit_test", f"Unit test for {c.name}", [path], rec.source_refs, {"component_ref": c.component_ref}, rec))
    for s in ctx.screen_specs:
        if s.kind in ("list", "dashboard"):
            path = f"tests/unit/{s.page_component}.test.tsx"
            rec = TestRecord(id=f"test.unit.{slug(s.page_component)}", type="unit", path=path, source_refs=[s.screen_ref, *s.data_sources, *s.actions], description=f"{s.page_component} loading/empty/error/success states")
            units.append(Unit(f"unit_test:{s.screen_ref}", "unit_test", f"Unit test for {s.page_component}", [path], rec.source_refs, {"screen_ref": s.screen_ref}, rec))
    # 4b. integration tests: page + hooks + API client + fetch, one per create workflow
    for w in g.workflows:
        if w["kind"] == "create":
            path = f"tests/integration/{slug(w['id'])}.test.tsx"
            rec = TestRecord(id=f"test.integration.{slug(w['id'])}", type="integration", path=path, source_refs=[w["id"], w["api"], w["entity"], w["screen"]], description=f"{w['name']} through the real page, hooks and API client")
            units.append(Unit(f"integration:{w['id']}", "integration_test", f"Integration test for {w['id']}", [path], rec.source_refs, {"workflow_ref": w["id"]}, rec))
    # 5. e2e
    ac = g.nodes("acceptance_criteria")
    nav_refs = [s.screen_ref for s in ctx.screen_specs]
    e2e = [("navigation", "test.e2e.navigation", nav_refs, {"kind": "navigation"})]
    for w in g.workflows:
        refs = [w["id"], w["api"], w["entity"]] + [a["id"] for a in ac if a["workflow"] == w["id"]] + [x for x in (w.get("screen"), (w.get("trigger") or {}).get("screen")) if x]
        e2e.append((slug(w["id"]), f"test.{tail(w['id'])}", refs, {"kind": "workflow", "workflow_ref": w["id"]}))
    data_screens = [s.screen_ref for s in ctx.screen_specs if s.data_sources]
    e2e.append(("states", "test.e2e.states", data_screens, {"kind": "states"}))
    e2e.append(("permissions", "test.e2e.permissions", [p["id"] for p in g.permissions] + [w["id"] for w in g.workflows], {"kind": "permissions"}))
    e2e.append(("accessibility", "test.e2e.accessibility", nav_refs, {"kind": "accessibility"}))
    for name, tid, refs, spec in e2e:
        path = f"tests/e2e/{name}.spec.ts"
        rec = TestRecord(id=tid, type="e2e", path=path, source_refs=list(dict.fromkeys(refs)), description=f"Browser test: {name}")
        units.append(Unit(f"e2e:{name}", "e2e", f"E2E {name}", [path], rec.source_refs, spec, rec))
    rec = TestRecord(id="test.visual.screens", type="visual", path="tests/visual/screens.spec.ts", source_refs=nav_refs, description="Screenshots + layout metrics for every screen at desktop/tablet/mobile")
    units.append(Unit("visual:screens", "visual", "Visual capture", [rec.path], nav_refs, {"viewports": VIEWPORTS}, rec))
    paths = [p for u in units for p in u.expected_paths]
    dupes = sorted({p for p in paths if paths.count(p) > 1})
    if dupes:  # two units writing the same file would silently overwrite each other
        raise AgentError(ErrorKind.BUILD_ERROR, f"code-generation units collide on output paths: {dupes}")
    return units


VIEWPORTS = {"desktop": {"width": 1280, "height": 800}, "tablet": {"width": 820, "height": 1180}, "mobile": {"width": 390, "height": 844}}


def unit_context(ctx: RunContext, u: Unit) -> dict:
    g = ctx.g
    cb = ctx.contexts
    base = {
        "unit": {"id": u.id, "type": u.type, "title": u.title, "allowed_output_paths": u.expected_paths},
        "catalog": build_catalog(g, ctx.bindings, ctx.design_system),
    }
    if u.type == "hooks":
        base["bindings"] = [b.api for b in ctx.bindings if b.resource == u.spec["resource"]]
        base["state_plan"] = {k: [x for x in ctx.state_plan.get(k, []) if x.get("api_ref") in {b.id for b in ctx.bindings if b.resource == u.spec["resource"]}] for k in ("queries", "mutations")}
    elif u.type in ("component", "unit_test") and u.spec.get("component_ref"):
        spec = ctx.component_spec(u.spec["component_ref"])
        base.update(cb.for_component(spec.component_ref))
        base["component_spec"] = spec.model_dump()
        base["unit"] = {**base["unit"], "id": u.id, "type": u.type, "title": u.title, "allowed_output_paths": u.expected_paths}
        if u.type == "unit_test":
            base["source_under_test"] = {"path": spec.path, "content": ctx.workspace.read(spec.path)}
    elif u.type in ("page", "unit_test") and u.spec.get("screen_ref"):
        spec = ctx.screen_spec(u.spec["screen_ref"])
        base.update(cb.for_screen(spec.screen_ref))
        base["screen_spec"] = spec.model_dump()
        base["component_specs"] = [ctx.component_spec(c).model_dump() for c in spec.components]
        base["unit"] = {"id": u.id, "type": u.type, "title": u.title, "allowed_output_paths": u.expected_paths}
        if u.type == "unit_test":
            base["source_under_test"] = {"path": spec.page_path, "content": ctx.workspace.read(spec.page_path)}
    else:  # integration / e2e / visual
        base.update(cb.for_refs(u.source_refs))
        base["screens"] = [s.model_dump() for s in ctx.screen_specs]
        seed = seed_data(g)
        base["seed"] = {"collections": seed.collections, "users": [{"email": c["email"], "role": c["role"], "user_id": c["user_id"]} for c in seed.credentials], "test_password_fixture": "Password123!"}
        base["test_support"] = {
            "imports": "import { test, expect, loginAs } from './support/fixtures'; import { installMockApi } from './support/mockApi';",
            "mockApi": "installMockApi(page, { db?, failures?: Record<apiId,status|0>, delays?: Record<apiId,ms> }) -> { db, calls }",
            "loginAs": "await loginAs(page, '<role key>') before page.goto()",
        }
        base["spec"] = u.spec
    return base


def _validate_unit(ctx: RunContext, u: Unit):
    allowed = set(u.expected_paths)

    def validate(out: object) -> list[str]:
        files = out.get("files") if isinstance(out, dict) else None
        if not isinstance(files, list) or not files:
            return ['output must be {"files": [{"path", "purpose", "content"}]}']
        p: list[str] = []
        got = set()
        for f in files:
            if not isinstance(f, dict) or not isinstance(f.get("path"), str) or not isinstance(f.get("content"), str):
                p.append("each file needs string 'path' and 'content'")
                continue
            got.add(f["path"])
            if f["path"] not in allowed:
                p.append(f"path {f['path']!r} is not allowed for this unit (allowed: {sorted(allowed)})")
                continue
            try:
                ctx.workspace.check_llm_path(f["path"])
            except AgentError as e:
                p.append(str(e))
            p += check_generated_source(f["path"], f["content"])
        if got != allowed:
            p.append(f"must write exactly {sorted(allowed)}")
        return p

    return validate


def _hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


def write_unit(ctx: RunContext, u: Unit, files: list[dict], generator: str = "llm") -> list[FileRecord]:
    recs = []
    for f in files:
        ctx.workspace.write(f["path"], f["content"], from_llm=True)
        recs.append(FileRecord(path=f["path"], purpose=str(f.get("purpose") or u.title)[:300], source_refs=sorted(set(r for r in u.source_refs if r)), generator=generator,
                               digest=ctx.workspace.digest(f["content"])))
    ctx.add_files(recs)
    return recs


def run(ctx: RunContext) -> None:
    gen = ProjectGenerator(ctx.g, ctx.workspace)
    ctx.generator = gen
    ctx.bindings = gen.bindings
    # Deterministic layer first (project setup, dependencies, design system, graph-derived modules).
    gen.write_scaffold()
    gen.write_design_system(ctx.design_system)
    gen.write_graph_modules(ctx.screen_specs)
    ctx.add_files(gen.records)
    ctx.events.emit("deterministic_files", count=len(gen.records))

    cache = ctx.artifacts.load("unit_cache.json", {}) if ctx.incremental else {}
    units = plan_units(ctx)
    tests: list[TestRecord] = []
    for u in units:
        context = unit_context(ctx, u)
        key = _hash([context, ctx.llm.name])
        if ctx.incremental and cache.get(u.id) == key and all(ctx.workspace.exists(p) for p in u.expected_paths):
            ctx.events.emit("unit_cached", unit=u.id)
            for pth in u.expected_paths:
                ctx.add_files([FileRecord(path=pth, purpose=u.title, source_refs=sorted(set(r for r in u.source_refs if r)), generator="llm", digest=ctx.workspace.digest(ctx.workspace.read(pth)))])
        else:
            out = ctx.runner.call("code_generation", context, _validate_unit(ctx, u), unit=u.id)
            recs = write_unit(ctx, u, out["files"])
            ctx.events.emit("unit_generated", unit=u.id, files=[r.path for r in recs])
            cache[u.id] = key
        if u.test:
            tests.append(u.test)
    ctx.tests = tests
    ctx.artifacts.save("unit_cache.json", cache)
    ctx.artifacts.save_file_manifest(list(ctx.files.values()))
    ctx.artifacts.save_test_manifest(tests)
