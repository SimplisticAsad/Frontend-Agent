"""CLI behaviour (spec 62) and incremental regeneration (spec 52)."""
from __future__ import annotations

import json


from app.main import main
from app.llm.mock import MockLLMProvider
from app.pipeline.orchestrator import FrontendAgent
from app.config.settings import Settings
from tests.conftest import ScriptedBrowser, ScriptedCommands, edit_graph, node


def test_cli_validate_ok(project, capsys):
    assert main(["validate", "--project", str(project)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "valid" and out["project"] == "task_manager"


def test_cli_validate_reports_graph_error(project, capsys):
    edit_graph(project, "screens", lambda ns: node(ns, "screen.project.list")["data_sources"].append("api.ghost"))
    assert main(["validate", "--project", str(project)]) == 2
    err = json.loads(capsys.readouterr().err)
    assert err["status"] == "GRAPH_ERROR" and "api.ghost" in err["message"]


def test_cli_generate_stops_on_invalid_graph(project, capsys):
    edit_graph(project, "workflows", lambda ns: node(ns, "workflow.project.create").__setitem__("permission", "permission.nope"))
    assert main(["generate", "--project", str(project), "--mock"]) == 1
    out = json.loads(capsys.readouterr().out.split("\n\nFrontend:")[0])
    assert out["status"] == "failed" and out["errors"][0]["kind"] == "GRAPH_ERROR"
    assert not list((project / "frontend").rglob("*.tsx"))


def test_cli_rejects_unknown_mock_faults(project, capsys):
    assert main(["generate", "--project", str(project), "--mock", "--mock-faults", "explode"]) == 2
    assert "USAGE_ERROR" in capsys.readouterr().err


def test_cli_test_command_requires_a_generated_frontend(project, capsys):
    assert main(["test", "--project", str(project), "--mock"]) == 2
    assert "Run `generate` first" in capsys.readouterr().err


def test_python_dash_m_frontend_agent_alias(project):
    import subprocess, sys
    from tests.conftest import REPO

    r = subprocess.run([sys.executable, "-m", "frontend_agent", "validate", "--project", str(project)], cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0 and '"valid"' in r.stdout


def test_test_and_browser_test_commands_run_against_existing_output(project):
    from tests.conftest import make_agent

    gen = make_agent(project)
    gen._prepare_workspace()
    gen.plan_and_generate()
    cmds = ScriptedCommands()
    agent = FrontendAgent(project, MockLLMProvider(), settings=Settings(), commands=cmds, browser=ScriptedBrowser())
    res = agent.test()
    assert res["passed"] and res["results"] == {"typescript": "passed", "lint": "passed", "build": "passed", "unit_tests": "passed"}
    from app.execution.command_runner import Cmd

    assert [c for c in cmds.calls if c is not Cmd.INSTALL] == [Cmd.TYPECHECK, Cmd.LINT, Cmd.BUILD, Cmd.TEST]
    bt = FrontendAgent(project, MockLLMProvider(), settings=Settings(), commands=ScriptedCommands(), browser=ScriptedBrowser()).browser_test(visual=False)
    assert bt["passed"] and bt["e2e"]["e2e_tests"] == "passed"


def test_incremental_run_reuses_unchanged_units_and_regenerates_only_changed_ones(project):
    def run(incremental):
        llm = MockLLMProvider()
        a = FrontendAgent(project, llm, settings=Settings(), commands=ScriptedCommands(), browser=ScriptedBrowser(), incremental=incremental)
        if not incremental:
            a._prepare_workspace()
        a.plan_and_generate()
        return a, llm

    _, first = run(False)
    gen_calls_first = sum(1 for s, _ in first.calls if s == "code_generation")
    _, second = run(True)
    assert sum(1 for s, _ in second.calls if s == "code_generation") == 0  # nothing changed -> nothing regenerated
    assert gen_calls_first > 30

    # change one page's graph input: only the units that depend on it are regenerated
    edit_graph(project, "screens", lambda ns: node(ns, "screen.dashboard").__setitem__("name", "Overview"))
    _, third = run(True)
    regenerated = [u for s, u in third.calls if s == "code_generation"]
    assert regenerated and len(regenerated) < gen_calls_first / 3
    assert "page:screen.dashboard" in regenerated and "page:screen.task.list" not in regenerated
