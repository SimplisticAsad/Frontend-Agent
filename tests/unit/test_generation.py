"""Planning + generation structure, using the mock LLM (no npm): routes, API mapping, components, manifests,
permissions, workflows and traceability."""
from __future__ import annotations

import json
import re

import pytest

from app.domain.models.errors import LLMError
from app.generation.symbols import build_api_bindings, seed_data
from app.llm.mock import MockLLMProvider
from app.validation.permission_validation import check_permissions, role_permissions
from app.validation.route_validation import check_routes
from tests.conftest import edit_graph, make_agent, node


def read(agent, path: str) -> str:
    return agent.ctx.workspace.read(path)


# ----------------------------------------------------------------------------- routes
def test_every_graph_screen_has_a_spec_and_a_route(generated):
    ctx = generated.ctx
    assert {s.screen_ref for s in ctx.screen_specs} == {s["id"] for s in ctx.g.screens}
    router = read(generated, "src/app/router.tsx")
    for s in ctx.g.screens:
        assert f"path: '{s['route']}'" in router
    assert check_routes(ctx.g, [s.model_dump() for s in ctx.screen_specs], [s["route"] for s in ctx.g.screens]) == []
    assert (ctx.artifacts.root / "screen_specs" / "screen.project.list.json").exists()


def test_orphan_and_missing_routes_are_detected(generated):
    ctx = generated.ctx
    specs = [s.model_dump() for s in ctx.screen_specs]
    assert any(i.code == "missing_route" for i in check_routes(ctx.g, specs[1:]))
    orphan = dict(specs[0], screen_ref="screen.invented")
    assert any(i.code == "orphan_route" for i in check_routes(ctx.g, specs + [orphan]))
    assert any(i.code == "orphan_route" for i in check_routes(ctx.g, specs, [s["route"] for s in ctx.g.screens] + ["/invented"]))
    wrong = [dict(specs[0], route="/other")] + specs[1:]
    assert any(i.code == "route_mismatch" for i in check_routes(ctx.g, wrong))


def test_page_planning_rejects_llm_changes_to_graph_owned_fields(project):
    class Rogue(MockLLMProvider):
        def _stage_page_planning(self, c):
            out = super()._stage_page_planning(c)
            out["route"] = "/invented"
            return out

    agent = make_agent(project, llm=Rogue())
    agent._prepare_workspace()
    with pytest.raises(LLMError, match="graph-owned"):
        agent.plan_and_generate()


def test_page_planning_cannot_add_components(project):
    class Rogue(MockLLMProvider):
        def _stage_page_planning(self, c):
            out = super()._stage_page_planning(c)
            out["components"] = out["components"] + ["component.task.table"] if out["screen_ref"] == "screen.dashboard" else out["components"]
            return out

    agent = make_agent(project, llm=Rogue())
    agent._prepare_workspace()
    with pytest.raises(LLMError, match="reordering"):
        agent.plan_and_generate()


# ----------------------------------------------------------------------------- API mapping
def test_api_functions_match_the_graph_exactly(generated):
    ctx = generated.ctx
    bindings = {b.id: b for b in build_api_bindings(ctx.g)}
    assert bindings["api.project.list"].function == "getProjects"
    assert bindings["api.project.get"].function == "getProject"
    assert bindings["api.project.create"].function == "createProject"
    assert bindings["api.project.delete"].function == "deleteProject"
    assert bindings["api.task.update_status"].function == "updateTaskStatus"
    projects = read(generated, "src/lib/api/projects.ts")
    assert "method: 'GET', path: '/projects'" in projects
    assert "method: 'POST', path: '/projects'" in projects
    assert "path: `/projects/${encodeURIComponent(id)}`" in projects and "method: 'DELETE'" in projects
    tasks = read(generated, "src/lib/api/tasks.ts")
    assert "method: 'PATCH', path: `/tasks/${encodeURIComponent(id)}/status`" in tasks
    assert "query: params" in tasks  # api.task.list declares a project_id query field


def test_no_endpoint_outside_api_json(generated):
    ctx = generated.ctx
    used = set()
    for p in ctx.workspace.list_files("src/lib/api"):
        for m in re.finditer(r"path: [`'](/[^`']*)[`']", read(generated, p)):
            used.add(re.sub(r"\$\{[^}]*\}", "{id}", m.group(1)))
    assert used and {u.replace("{id}", "{id}") for u in used} <= {a["path"].replace("{id}", "{id}") for a in ctx.g.apis}


def test_session_sourced_request_fields_are_injected_by_the_api_layer_not_the_form(generated):
    projects = read(generated, "src/lib/api/projects.ts")
    assert "owner_id: getSession()?.user.id" in projects
    types = read(generated, "src/types/project.ts")
    assert "export interface CreateProjectInput" in types
    body = types.split("export interface CreateProjectInput")[1].split("}")[0]
    assert "name: string" in body and "owner_id" not in body
    schema = read(generated, "src/lib/validation/projectCreate.ts")
    assert "owner_id" not in schema  # no invented form fields


def test_request_types_and_zod_schema_follow_validations(generated):
    schema = read(generated, "src/lib/validation/projectCreate.ts")
    assert "z.string().trim().min(1, \"Name is required\").min(3, \"Name must be at least 3 characters\").max(80" in schema
    assert "description: z.string().trim().max(500" in schema and ".optional().or(z.literal(''))" in schema
    login = read(generated, "src/lib/validation/authLogin.ts")
    assert ".email('Enter a valid email address')" in login and "Password must be at least 8 characters" in login
    task = read(generated, "src/lib/validation/taskCreate.ts")
    assert "Select a project" in task  # validation.task.project custom message


def test_api_integration_plan_cannot_rename_endpoints(project):
    class Rogue(MockLLMProvider):
        def _stage_api_integration(self, c):
            out = super()._stage_api_integration(c)
            out["apis"][0]["path"] = "/invented"
            return out

    agent = make_agent(project, llm=Rogue())
    agent._prepare_workspace()
    with pytest.raises(LLMError, match="fixed by api.json"):
        agent.plan_and_generate()


# ----------------------------------------------------------------------------- component planning
def test_component_specs_cover_graph_components_with_contract_props(generated):
    ctx = generated.ctx
    by_ref = {c.component_ref: c for c in ctx.component_specs}
    assert set(by_ref) == {c["id"] for c in ctx.g.nodes("components")}
    assert by_ref["component.project.table"].path == "src/features/projects/components/ProjectTable.tsx"
    assert by_ref["component.page_header"].path == "src/components/shared/PageHeader.tsx"
    assert {"items", "onDelete", "deletingId"} <= set(by_ref["component.project.table"].props)
    assert {"onSubmit", "onCancel", "refOptions"} <= set(by_ref["component.task.form"].props)
    assert "onCancel" not in by_ref["component.login.form"].props
    assert by_ref["component.task.status_badge"].props == {"status": "TaskStatus"}


def test_component_planning_must_keep_contract_props(project):
    class Rogue(MockLLMProvider):
        def _stage_component_planning(self, c):
            out = super()._stage_component_planning(c)
            out["components"][0]["props"] = {}
            return out

    agent = make_agent(project, llm=Rogue())
    agent._prepare_workspace()
    with pytest.raises(LLMError, match="contract props"):
        agent.plan_and_generate()


def test_design_system_with_low_contrast_is_rejected(project):
    class Rogue(MockLLMProvider):
        def _stage_design_system(self, c):
            ds = c["baseline"]
            ds["colors"]["textMuted"] = "#cccccc"
            return ds

    agent = make_agent(project, llm=Rogue())
    agent._prepare_workspace()
    with pytest.raises(LLMError, match="contrast"):
        agent.plan_and_generate()


# ----------------------------------------------------------------------------- layered output / reusable primitives
def test_design_primitives_exist_and_pages_compose_them(generated):
    files = set(generated.ctx.workspace.list_files("src/components/ui"))
    for name in ("Button", "Field", "Card", "Table", "Modal", "Badge", "Alert", "Pagination", "Tabs", "Dropdown", "States"):
        assert f"src/components/ui/{name}.tsx" in files
    page = read(generated, "src/features/projects/pages/ProjectListPage.tsx")
    assert "components/ui/States" in page and "ProjectTable" in page and "components/shared/PageHeader" in page
    design = json.loads((generated.ctx.artifacts.root / "design_system.json").read_text())
    assert {"typography", "spacing", "colors", "borders", "radius", "shadows", "components", "responsive"} <= set(design)
    assert "colors" in read(generated, "tailwind.config.ts")


# ----------------------------------------------------------------------------- manifests + traceability
def test_file_manifest_traces_pages_back_to_the_graph(generated):
    manifest = {r.path: r for r in generated.ctx.artifacts.load_file_manifest()}
    page = manifest["src/features/projects/pages/ProjectListPage.tsx"]
    assert {"screen.project.list", "workflow.project.create", "api.project.list", "entity.project"} <= set(page.source_refs)
    assert page.generator == "llm" and page.digest and page.purpose
    table = manifest["src/features/projects/components/ProjectTable.tsx"]
    assert {"component.project.table", "entity.project", "workflow.project.delete"} <= set(table.source_refs)
    api = manifest["src/lib/api/projects.ts"]
    assert {"api.project.list", "api.project.create", "entity.project"} <= set(api.source_refs) and api.generator == "graph"
    details = manifest["src/features/tasks/pages/TaskDetailsPage.tsx"]
    assert {"screen.task.details", "workflow.task.update_status", "sm.task.status", "permission.task.update_status"} <= set(details.source_refs)


def test_every_generated_file_is_in_the_manifest_and_on_disk(generated):
    manifest = generated.ctx.artifacts.load_file_manifest()
    on_disk = set(generated.ctx.workspace.list_files())
    assert {r.path for r in manifest} <= on_disk
    llm_files = {p for p in on_disk if p.startswith(("src/", "tests/"))}
    assert llm_files <= {r.path for r in manifest}


def test_test_manifest_traces_tests_to_workflows_and_criteria(generated):
    tests = {t.id: t for t in generated.ctx.artifacts.load_test_manifest()}
    create = tests["test.project.create"]
    assert create.type == "e2e" and create.path == "tests/e2e/project-create.spec.ts"
    assert {"workflow.project.create", "ac.project.create", "api.project.create"} <= set(create.source_refs)
    assert tests["test.task.create"].path == "tests/e2e/task-create.spec.ts"  # distinct file per workflow
    assert {t.type for t in tests.values()} == {"unit", "integration", "e2e", "visual"}
    paths = [t.path for t in tests.values()]
    assert len(paths) == len(set(paths))
    for t in tests.values():
        assert generated.ctx.workspace.exists(t.path)


# ----------------------------------------------------------------------------- permissions
def test_permission_mapping_reflects_the_graph(generated):
    g = generated.ctx.g
    rp = role_permissions(g)
    assert "permission.project.create" in rp["manager"] and "permission.project.create" not in rp["employee"]
    perms = read(generated, "src/lib/permissions.ts")
    assert re.search(r'"manager": \[[^\]]*"permission\.project\.create"', perms)
    employee = re.search(r'"employee": \[([^\]]*)\]', perms).group(1)
    assert "permission.project.create" not in employee and "permission.task.update_status" in employee
    assert '"role.employee": {' not in perms and '"employee": {' in perms and '"field": "assignee_id"' in perms  # assigned-only condition
    assert not set(re.findall(r"permission\.[a-z_.]+", perms)) - {p["id"] for p in g.permissions}  # nothing invented
    router = read(generated, "src/app/router.tsx")
    assert "<RequirePermission permissions={['permission.project.create']}>" in router


def test_permission_asymmetry_is_reported_as_a_warning(project):
    edit_graph(project, "roles", lambda ns: node(ns, "role.employee")["permissions"].remove("permission.project.view"))
    from app.graph.loader import load_graph_package

    issues = check_permissions(load_graph_package(project))
    assert any(i.code == "permission_asymmetry" and i.severity == "warning" for i in issues)


def test_pages_hide_actions_the_role_lacks(generated):
    page = read(generated, "src/features/projects/pages/ProjectListPage.tsx")
    assert "can('permission.project.create')" in page and "can('permission.project.delete')" in page
    assert "canCreate ? (" in page and "onDelete={canDelete ?" in page
    details = read(generated, "src/features/tasks/pages/TaskDetailsPage.tsx")
    assert "allowedTransitions('sm.task.status'" in details and "can(p, task)" in details


# ----------------------------------------------------------------------------- workflows + states + forms
def test_every_workflow_maps_to_frontend_behaviour(generated):
    g = generated.ctx.g
    ws = generated.ctx.workspace
    all_src = "\n".join(ws.read(p) for p in ws.list_files("src") if p.endswith(".tsx"))
    for wf in g.workflows:
        if wf["kind"] in ("create", "delete"):
            assert f"workflow-{wf['id'].split('.', 1)[1].replace('.', '-').replace('_', '-')}" in all_src, wf["id"]
        if wf.get("form_fields"):
            camel = wf["id"].split(".", 1)[1].split(".")
            fname = camel[0] + "".join(w.capitalize() for w in camel[1:])
            schema = read(generated, f"src/lib/validation/{fname}.ts")
            for f in wf["form_fields"]:
                assert f"  {f}:" in schema


def test_forms_render_exactly_the_graph_fields_with_react_hook_form_and_zod(generated):
    form = read(generated, "src/features/projects/components/ProjectForm.tsx")
    assert "zodResolver(projectCreateSchema)" in form and "register('name')" in form and "register('description')" in form
    assert "owner_id" not in form and "register('id')" not in form
    assert "onCancel" in form and "reset()" in form and "serverError" in form and "fieldErrors" in form
    task_form = read(generated, "src/features/tasks/components/TaskForm.tsx")
    for f in ("title", "description", "project_id", "assignee_id", "due_date"):
        assert f"register('{f}')" in task_form
    assert "<Select" in task_form and "refOptions['project_id']" in task_form


def test_loading_empty_error_states_and_responsive_behaviour_exist(generated):
    for p in ("ProjectListPage", "TaskListPage"):
        page = next(x for x in generated.ctx.workspace.list_files("src/features") if x.endswith(f"{p}.tsx"))
        src = read(generated, page)
        assert "LoadingState" in src and "EmptyState" in src and "ErrorState" in src and "refetch" in src
    assert "md:table-cell" in read(generated, "src/components/ui/Table.tsx")
    layout = read(generated, "src/layouts/AppLayout.tsx")
    assert "md:flex" in layout and "md:hidden" in layout and "aria-expanded" in layout
    specs = {s.screen_ref: s for s in generated.ctx.screen_specs}
    assert {"loading", "empty", "error", "success"} <= set(specs["screen.project.list"].states)
    assert set(specs["screen.project.list"].responsive) == {"desktop", "tablet", "mobile"}


def test_state_machine_table_matches_the_graph(generated):
    sm = read(generated, "src/lib/stateMachines.ts")
    for t in generated.ctx.g.get("sm.task.status")["transitions"]:
        assert f'"from": "{t["from"]}"' in sm and f'"to": "{t["to"]}"' in sm
    assert '"COMPLETED"' in sm and "allowedTransitions" in sm


def test_seed_data_is_consistent_with_entities(project):
    from app.graph.loader import load_graph_package

    g = load_graph_package(project)
    s = seed_data(g)
    users = {u["id"] for u in s.collections["users"]}
    assert all(t["assignee_id"] in users for t in s.collections["tasks"])
    assert {t["status"] for t in s.collections["tasks"]} == {"TODO", "IN_PROGRESS", "COMPLETED"}
    assert [c["role"] for c in s.credentials] == ["manager", "employee", "employee"]
