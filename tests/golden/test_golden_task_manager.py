"""Golden test: task_manager graphs -> generated frontend. Asserts structural invariants (never exact source text)."""
from __future__ import annotations

import json
import re
import shutil

import pytest

from app.generation.symbols import seed_data
from tests.conftest import TASK_MANAGER, make_agent


@pytest.fixture(scope="module")
def tm(tmp_path_factory):
    root = tmp_path_factory.mktemp("golden") / "task_manager"
    shutil.copytree(TASK_MANAGER / "graphs", root / "graphs")
    agent = make_agent(root)
    agent._prepare_workspace()
    agent.plan_and_generate()
    return agent


def src(tm, path):
    return tm.ctx.workspace.read(path)


def all_src(tm):
    ws = tm.ctx.workspace
    return {p: ws.read(p) for p in ws.list_files() if p.endswith((".ts", ".tsx"))}


def test_project_layout_matches_the_spec(tm):
    files = set(tm.ctx.workspace.list_files())
    for must in ("package.json", "vite.config.ts", "tsconfig.json", "index.html", "playwright.config.ts", "eslint.config.js", "tailwind.config.ts", "src/main.tsx",
                 "src/app/App.tsx", "src/app/router.tsx", "src/app/providers.tsx", "public/favicon.svg"):
        assert must in files
    for d in ("src/app/", "src/components/", "src/features/", "src/hooks/", "src/layouts/", "src/lib/", "src/types/", "tests/unit/", "tests/integration/", "tests/e2e/", "tests/visual/"):
        assert any(f.startswith(d) for f in files), d
    arts = {p.name for p in tm.ctx.artifacts.root.iterdir()}
    assert {"frontend_analysis.json", "frontend_architecture.json", "design_system.json", "screen_specs", "component_specs", "file_manifest.json", "test_manifest.json"} <= arts
    pkg = json.loads(src(tm, "package.json"))
    assert {"build", "dev", "test", "lint", "typecheck", "test:e2e", "test:visual"} <= set(pkg["scripts"])
    for dep in ("react", "react-router-dom", "@tanstack/react-query", "react-hook-form", "zod"):
        assert dep in pkg["dependencies"]
    for dep in ("vitest", "@testing-library/react", "@playwright/test", "tailwindcss", "typescript", "vite"):
        assert dep in pkg["devDependencies"]


def test_routes_exist_for_every_screen_and_only_for_screens(tm):
    router = src(tm, "src/app/router.tsx")
    declared = set(re.findall(r"path: '([^']+)'", router)) - {"/", "*"}
    assert declared == {s["route"] for s in tm.ctx.g.screens}


def test_dashboard_project_list_creation_and_task_screens_exist(tm):
    for page in ("features/dashboard/pages/DashboardPage", "features/projects/pages/ProjectListPage", "features/projects/pages/ProjectCreatePage",
                 "features/projects/pages/ProjectDetailsPage", "features/tasks/pages/TaskListPage", "features/tasks/pages/TaskCreatePage", "features/tasks/pages/TaskDetailsPage",
                 "features/auth/pages/LoginPage"):
        assert tm.ctx.workspace.exists(f"src/{page}.tsx"), page
    assert "ProjectForm" in src(tm, "src/features/projects/pages/ProjectCreatePage.tsx")
    assert "TaskStatusControl" in src(tm, "src/features/tasks/pages/TaskDetailsPage.tsx")


def test_api_integration_exists_for_every_endpoint(tm):
    code = "\n".join(src(tm, p) for p in tm.ctx.workspace.list_files("src/lib/api"))
    for a in tm.ctx.g.apis:
        assert f"method: '{a['method']}'" in code and a["path"].split("{")[0] in code, a["id"]
    hooks = "\n".join(src(tm, p) for p in tm.ctx.workspace.list_files("src/hooks/queries"))
    for fn in ("useProjects", "useProject", "useCreateProject", "useDeleteProject", "useTasks", "useTask", "useCreateTask", "useUpdateTaskStatus", "useLogin", "useUsers"):
        assert f"export function {fn}(" in hooks
    client = src(tm, "src/lib/api/client.ts")
    for status in (400, 401, 403, 404, 409, 429):
        assert f"status === {status}" in client or f"{status}" in client
    assert "timeout" in client and "network" in client and "status >= 500" in client


def test_permissions_are_reflected_in_the_ui(tm):
    perms = src(tm, "src/lib/permissions.ts")
    assert "permission.project.create" in perms and "ROLE_PERMISSIONS" in perms
    assert "can('permission.project.create')" in src(tm, "src/features/projects/pages/ProjectListPage.tsx")
    assert "RequirePermission permissions={['permission.task.create']}" in src(tm, "src/app/router.tsx")
    assert "usePermissions" in src(tm, "src/layouts/AppLayout.tsx")  # navigation filtered by permission


def test_loading_empty_error_states_everywhere_data_is_fetched(tm):
    for p, content in all_src(tm).items():
        if p.endswith("Page.tsx") and any(h in content for h in ("useProjects(", "useTasks(", "useProject(", "useTask(")) and not p.startswith("tests/"):
            assert "LoadingState" in content, p
            assert "ErrorState" in content, p
    for p in ("ProjectListPage", "TaskListPage", "DashboardPage"):
        content = next(c for k, c in all_src(tm).items() if k.endswith(p + ".tsx"))
        assert "EmptyState" in content


def test_responsive_behaviour_exists(tm):
    assert "md:table-cell" in src(tm, "src/components/ui/Table.tsx") and "before:content-[attr(data-label)]" in src(tm, "src/components/ui/Table.tsx")
    assert "sm:max-w-lg" in src(tm, "src/components/ui/Modal.tsx") and "items-end" in src(tm, "src/components/ui/Modal.tsx")
    layout = src(tm, "src/layouts/AppLayout.tsx")
    assert "md:flex" in layout and "md:hidden" in layout and 'aria-label="Menu"' in layout
    assert "min-h-[44px]" in src(tm, "src/components/ui/Button.tsx")
    ds = json.loads((tm.ctx.artifacts.root / "design_system.json").read_text())
    assert {"desktop", "tablet", "mobile"} <= set(ds["responsive"])


def test_accessibility_primitives(tm):
    modal = src(tm, "src/components/ui/Modal.tsx")
    for needle in ('role="dialog"', 'aria-modal="true"', "aria-labelledby", "Escape", "previouslyFocused"):
        assert needle in modal
    assert 'htmlFor={id}' in src(tm, "src/components/ui/Field.tsx") and 'role="alert"' in src(tm, "src/components/ui/Field.tsx")
    assert "focus-visible" in src(tm, "src/components/ui/Button.tsx")
    page_sources = [c for p, c in all_src(tm).items() if p.endswith("Page.tsx") and p.startswith("src/")]
    assert page_sources and not any(re.search(r"<div[^>]*onClick", c) for c in page_sources)  # buttons, not clickable divs


def test_tests_exist_for_every_layer_and_trace_to_the_graph(tm):
    tests = tm.ctx.artifacts.load_test_manifest()
    by_type = {t.type for t in tests}
    assert by_type == {"unit", "integration", "e2e", "visual"}
    wf_ids = {w["id"] for w in tm.ctx.g.workflows}
    covered = {r for t in tests if t.type == "e2e" for r in t.source_refs}
    assert wf_ids <= covered  # every workflow has a browser test
    ac_ids = {a["id"] for a in tm.ctx.g.nodes("acceptance_criteria")}
    assert ac_ids <= covered
    for t in tests:
        content = src(tm, t.path)
        assert "test(" in content or "it(" in content, t.path
        assert t.source_refs
    e2e = src(tm, "tests/e2e/project-create.spec.ts")
    assert "installMockApi" in e2e and "loginAs" in e2e and "workflow-project-create" in e2e
    assert "[a11y]" in src(tm, "tests/e2e/accessibility.spec.ts") and "AxeBuilder" in src(tm, "tests/e2e/accessibility.spec.ts")
    visual = src(tm, "tests/visual/screens.spec.ts")
    assert all(v in visual for v in ("desktop", "tablet", "mobile")) and "page.screenshot" in visual


def test_state_machine_only_permits_graph_transitions(tm):
    sm = tm.ctx.g.get("sm.task.status")
    allowed = {(t["from"], t["to"]) for t in sm["transitions"]}
    machine = json.loads(re.search(r"STATE_MACHINES = (\{.*?\}) as unknown", src(tm, "src/lib/stateMachines.ts"), re.S).group(1))["sm.task.status"]
    assert {(t["from"], t["to"]) for t in machine["transitions"]} == allowed
    tests = src(tm, "tests/e2e/task-update-status.spec.ts")
    assert "MATRIX" in tests and "task-2" in tests


def test_workflows_forms_validation_are_present(tm):
    for wf in tm.ctx.g.workflows:
        assert wf["id"] in json.dumps([r.model_dump() for r in tm.ctx.artifacts.load_file_manifest()])
    assert "zodResolver" in src(tm, "src/features/projects/components/ProjectForm.tsx")
    assert "Password must be at least 8 characters" in src(tm, "src/lib/validation/authLogin.ts")


def test_e2e_mock_api_is_derived_from_the_graph(tm):
    data = src(tm, "tests/e2e/support/data.ts")
    for a in tm.ctx.g.apis:
        assert f'"id": "{a["id"]}"' in data
    seed = seed_data(tm.ctx.g)
    assert all(c["email"] in data for c in seed.credentials)


def test_generation_is_deterministic(tm, tmp_path):
    root = tmp_path / "again"
    shutil.copytree(TASK_MANAGER / "graphs", root / "graphs")
    other = make_agent(root)
    other._prepare_workspace()
    other.plan_and_generate()
    a = {r.path: r.digest for r in tm.ctx.artifacts.load_file_manifest()}
    b = {r.path: r.digest for r in other.ctx.artifacts.load_file_manifest()}
    assert a == b and len(a) > 80


def test_no_secrets_in_generated_code(tm):
    for p, c in all_src(tm).items():
        if p.startswith("tests/"):
            continue
        assert not re.search(r"(?i)(api[_-]?key|secret)\s*[:=]\s*['\"]\w{8,}", c), p
