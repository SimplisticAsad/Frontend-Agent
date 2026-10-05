"""Graph loading, validation (GRAPH_ERROR negatives), conflict detection and context building."""
from __future__ import annotations

import json

import pytest

from app.domain.models.errors import ErrorKind, GraphError
from app.graph.context_builder import ContextBuilder
from app.graph.loader import load_graph_package
from app.llm.mock import MockLLMProvider
from app.validation.api_validation import check_api_coverage
from app.validation.graph_validation import assert_valid, validate_graph
from tests.conftest import edit_graph, make_agent, node


# ----------------------------------------------------------------------------- loading
def test_loads_only_frontend_graphs(project):
    manifest = json.loads((project / "graphs" / "graph_manifest.json").read_text())
    manifest["files"]["backend"] = "backend.json"  # exists in the manifest but is not a frontend input and not on disk
    (project / "graphs" / "graph_manifest.json").write_text(json.dumps(manifest))
    g = load_graph_package(project)
    assert "backend" not in g.graphs
    assert {"screens", "api", "workflows", "permissions", "state_machines"} <= set(g.graphs)
    assert g.project_id == "task_manager" and g.graph_version == "1.0.0"
    assert g.get("screen.project.list")["route"] == "/projects"


def test_missing_manifest_is_a_graph_error(tmp_path):
    (tmp_path / "graphs").mkdir()
    with pytest.raises(GraphError) as e:
        load_graph_package(tmp_path)
    assert e.value.kind is ErrorKind.GRAPH_ERROR


def test_missing_graph_file_is_a_graph_error(project):
    (project / "graphs" / "screens.json").unlink()
    with pytest.raises(GraphError) as e:
        load_graph_package(project)
    assert any(i.code == "file_missing" for i in e.value.issues)


def test_invalid_json_is_a_graph_error(project):
    (project / "graphs" / "api.json").write_text("{not json")
    with pytest.raises(GraphError) as e:
        load_graph_package(project)
    assert any(i.code == "invalid_json" for i in e.value.issues)


def test_manifest_entry_missing(project):
    m = json.loads((project / "graphs" / "graph_manifest.json").read_text())
    del m["files"]["screens"]
    (project / "graphs" / "graph_manifest.json").write_text(json.dumps(m))
    with pytest.raises(GraphError) as e:
        load_graph_package(project)
    assert any(i.code == "manifest_entry_missing" for i in e.value.issues)


# ----------------------------------------------------------------------------- validation
def test_golden_graph_is_valid(project):
    g = load_graph_package(project)
    assert [i for i in validate_graph(g) if i.severity == "error"] == []
    assert check_api_coverage(g) == []


def _errors(project):
    return [i for i in validate_graph(load_graph_package(project)) if i.severity == "error"]


@pytest.mark.parametrize(
    "graph,mutate,code",
    [
        ("screens", lambda ns: node(ns, "screen.project.list")["data_sources"].append("api.does.not.exist"), "dangling_ref"),  # invalid API reference
        ("workflows", lambda ns: node(ns, "workflow.project.create").__setitem__("permission", "permission.nope"), "dangling_ref"),  # missing permission
        ("screens", lambda ns: node(ns, "screen.project.list").__setitem__("entity", "entity.nope"), "dangling_ref"),  # missing entity
        ("screens", lambda ns: node(ns, "screen.project.list")["actions"].append("workflow.nope"), "dangling_ref"),  # invalid workflow
        ("workflows", lambda ns: node(ns, "workflow.project.create").__setitem__("kind", "teleport"), "bad_workflow_kind"),
        ("workflows", lambda ns: node(ns, "workflow.project.create").__setitem__("form_fields", ["name", "ghost"]), "unknown_field"),
        ("screens", lambda ns: node(ns, "screen.task.list").__setitem__("route", "/projects"), "duplicate_route"),
        ("screens", lambda ns: node(ns, "screen.task.list").__setitem__("route", "tasks"), "bad_route"),
        ("state_machines", lambda ns: node(ns, "sm.task.status")["transitions"].append({"from": "TODO", "to": "NOPE"}), "bad_transition"),
        ("questions", lambda ns: ns.append({"id": "question.blocker", "text": "?", "status": "open", "blocking": True}), "blocking_question"),
        ("api", lambda ns: node(ns, "api.project.list").pop("permission"), "api_no_permission"),
        ("roles", lambda ns: node(ns, "role.manager")["permissions"].append("permission.ghost"), "dangling_ref"),
        ("entities", lambda ns: ns.append({"id": "entity.project", "name": "Dup", "fields": []}), "duplicate_id"),
        ("components", lambda ns: node(ns, "component.project.table").__setitem__("kind", "hologram"), "bad_component_kind"),
    ],
)
def test_negative_graphs_are_graph_errors(project, graph, mutate, code):
    edit_graph(project, graph, mutate)
    errs = _errors(project)
    assert any(i.code == code for i in errs), [i.code for i in errs]
    assert all(i.kind is ErrorKind.GRAPH_ERROR for i in errs)
    with pytest.raises(GraphError):
        assert_valid(load_graph_package(project))


def test_missing_screen_graph_content_is_a_graph_error(project):
    edit_graph(project, "screens", lambda ns: ns.clear())
    assert any(i.code == "empty_graph" for i in _errors(project))


def test_pipeline_stops_on_invalid_graph_without_calling_the_llm(project):
    edit_graph(project, "screens", lambda ns: node(ns, "screen.project.list")["data_sources"].append("api.ghost"))
    llm = MockLLMProvider()
    agent = make_agent(project, llm=llm)
    report = agent.generate()
    assert report["status"] == "failed"
    assert report["errors"][0]["kind"] == "GRAPH_ERROR"
    assert llm.calls == []  # STOP: nothing was planned or generated
    assert not any((project / "frontend").rglob("*.tsx"))
    assert agent.ctx.status.state.value == "FAILED"


# ----------------------------------------------------------------------------- GRAPH_IMPLEMENTATION_CONFLICT (spec 43)
def test_required_api_field_without_a_source_is_an_implementation_conflict(project):
    # api.project.create requires owner_id; remove its session source and the form does not supply it either
    def drop_source(ns):
        f = next(f for f in node(ns, "api.project.create")["request"]["fields"] if f["name"] == "owner_id")
        f["source"] = "form"

    edit_graph(project, "api", drop_source)
    g = load_graph_package(project)
    conflicts = check_api_coverage(g)
    assert [c.kind for c in conflicts] == [ErrorKind.GRAPH_IMPLEMENTATION_CONFLICT]
    assert "owner_id" in conflicts[0].message

    llm = MockLLMProvider()
    report = make_agent(project, llm=llm).generate()
    assert report["status"] == "failed" and report["errors"][0]["kind"] == "GRAPH_IMPLEMENTATION_CONFLICT"
    assert llm.calls == []


def test_ref_field_needs_a_list_api_on_its_form_screen(project):
    edit_graph(project, "screens", lambda ns: node(ns, "screen.task.create")["data_sources"].remove("api.user.list"))
    conflicts = check_api_coverage(load_graph_package(project))
    assert any(c.code == "ref_options_unavailable" for c in conflicts)


# ----------------------------------------------------------------------------- context builder
def test_screen_context_contains_only_its_slice(project):
    g = load_graph_package(project)
    ctx = ContextBuilder(g).for_screen("screen.project.list")
    assert [s["id"] for s in ctx["screens"]] == ["screen.project.list"]
    ents = {e["id"] for e in ctx["entities"]}
    assert "entity.project" in ents and "entity.task" not in ents
    assert {"workflow.project.create", "workflow.project.delete"} == {w["id"] for w in ctx["workflows"]}
    assert "api.project.list" in {a["id"] for a in ctx["apis"]} and "api.task.list" not in {a["id"] for a in ctx["apis"]}
    assert "permission.project.create" in {p["id"] for p in ctx["permissions"]}
    assert {a["id"] for a in ctx["acceptance_criteria"]} >= {"ac.project.create", "ac.project.delete"}
    assert len(json.dumps(ctx)) < 0.6 * len(json.dumps({k: g.nodes(k) for k in g.graphs}))


def test_context_follows_state_machine_and_validations(project):
    ctx = ContextBuilder(load_graph_package(project)).for_screen("screen.task.details")
    assert [m["id"] for m in ctx["state_machines"]] == ["sm.task.status"]
    assert any(v["field"] == "title" for v in ctx["validations"])
    assert "workflow.task.update_status" in {w["id"] for w in ctx["workflows"]}
    assert "screen.project.list" not in {s["id"] for s in ctx["screens"]}


def test_component_context(project):
    ctx = ContextBuilder(load_graph_package(project)).for_component("component.project.form")
    assert {w["id"] for w in ctx["workflows"]} == {"workflow.project.create"}
    assert any(v["id"] == "validation.project.name" for v in ctx["validations"])
