"""Build / browser / visual correction loops, retry limits, error classification and the requirement guard."""
from __future__ import annotations

import pytest

from app.config.settings import Limits
from app.domain.models.errors import AgentError, ErrorKind, LLMError
from app.domain.models.state import PipelineState
from app.execution.browser_runner import BrowserRunResult
from app.execution.command_runner import Cmd
from app.llm.mock import MockLLMProvider
from app.pipeline import browser_testing, build, visual_testing
from app.pipeline.failures import classify_browser_failure, failure_from_command
from tests.conftest import ScriptedBrowser, ScriptedCommands, failing, make_agent, outcome, passing, write_capture

BADGE = "src/features/tasks/components/TaskStatusBadge.tsx"
TS_ERROR = f"{BADGE}(15,14): error TS2322: Type 'string' is not assignable to type 'number'."


class FixingLLM(MockLLMProvider):
    """Correction stages append a harmless comment to the first offered file (a real, applicable change)."""

    def __init__(self, decision="fix_implementation", edit=None, **kw):
        super().__init__(**kw)
        self.decision = decision
        self.edit = edit
        self.n = 0

    def _fix(self, c):
        if self.decision == "graph_conflict":
            return {"decision": "graph_conflict", "explanation": "api requires a field no screen supplies", "graph_conflict": {"description": "x", "refs": ["api.project.create"]}}
        self.n += 1
        f = c["files"][0]
        content = self.edit(f) if self.edit else f["content"] + f"\n// fix attempt {self.n}\n"
        return {"decision": "fix_implementation", "explanation": f"attempt {self.n}", "files": [{"path": f["path"], "content": content}]}

    _stage_build_error_correction = lambda self, c: self._fix(c)  # noqa: E731
    _stage_correction = lambda self, c: self._fix(c)  # noqa: E731

    def _stage_browser_error_analysis(self, c):
        if self.decision == "graph_conflict":
            return {"decision": "graph_conflict", "root_cause": "inconsistent graph", "files_to_change": [], "plan": [], "graph_conflict": {"description": "inconsistent", "refs": []}}
        return super()._stage_browser_error_analysis(c)


PATH = ["GENERATED", "STATIC_VALIDATION", "BUILT", "BROWSER_TESTED"]


def agent_with(project, llm=None, commands=None, browser=None, at="GENERATED", **kw):
    """Agent that already ran planning + generation, positioned at pipeline state `at` (the state machine is enforced)."""
    a = make_agent(project, llm=llm or FixingLLM(), commands=commands, browser=browser, **kw)
    a._prepare_workspace()
    a.plan_and_generate()
    for st in PATH[1 : PATH.index(at) + 1]:
        a.ctx.status.advance(PipelineState(st))
    return a


# ----------------------------------------------------------------------------- build loop
def test_broken_typescript_is_a_build_error_and_triggers_a_correction(project):
    cmds = ScriptedCommands({Cmd.BUILD: [failing(Cmd.BUILD, TS_ERROR), passing(Cmd.BUILD)]})
    agent = agent_with(project, commands=cmds)
    out = build.run(agent.ctx)
    assert out.passed and out.attempts == 1
    assert out.history[0]["kind"] == "BUILD_ERROR" and out.history[0]["applied"] == [BADGE]
    assert agent.ctx.workspace.read(BADGE).rstrip().endswith("// fix attempt 1")
    assert agent.ctx.attempts["build"] == 1 and agent.ctx.status.state.value == "BUILT"


def test_fails_twice_then_succeeds_counts_two_attempts(project):
    cmds = ScriptedCommands({Cmd.BUILD: [failing(Cmd.BUILD, TS_ERROR), failing(Cmd.BUILD, TS_ERROR), passing(Cmd.BUILD)]})
    agent = agent_with(project, commands=cmds)
    out = build.run(agent.ctx)
    assert out.passed and out.attempts == 2 == agent.ctx.attempts["build"]
    assert cmds.count(Cmd.BUILD) == 3


def test_persistent_failure_stops_after_max_attempts_and_never_loops_forever(project):
    cmds = ScriptedCommands({Cmd.BUILD: [failing(Cmd.BUILD, TS_ERROR)]})  # always fails
    agent = agent_with(project, commands=cmds)
    out = build.run(agent.ctx)
    assert not out.passed and out.attempts == 3 == agent.ctx.attempts["build"]
    assert cmds.count(Cmd.BUILD) == 4  # initial run + 3 corrections, then FAILED
    assert "limit reached" in out.reason and out.last_failure.kind is ErrorKind.BUILD_ERROR


def test_attempt_limit_is_configurable(project):
    cmds = ScriptedCommands({Cmd.BUILD: [failing(Cmd.BUILD, TS_ERROR)]})
    agent = agent_with(project, commands=cmds, limits=Limits(max_build_correction_attempts=1))
    out = build.run(agent.ctx)
    assert out.attempts == 1 and cmds.count(Cmd.BUILD) == 2 and not out.passed


def test_pipeline_reports_failed_when_build_never_succeeds(project):
    cmds = ScriptedCommands({Cmd.BUILD: [failing(Cmd.BUILD, TS_ERROR)]})
    agent = make_agent(project, llm=FixingLLM(), commands=cmds)
    report = agent.generate()
    assert report["status"] == "failed" and report["errors"][-1]["kind"] == "BUILD_ERROR"
    assert report["correction_attempts"]["build"] == 3
    assert agent.ctx.status.state.value == "FAILED"
    assert report["browser_test_result"]["e2e_tests"] == "not_run"  # later gates never ran


def test_a_correction_that_changes_nothing_ends_the_loop(project):
    llm = FixingLLM(edit=lambda f: f["content"])
    cmds = ScriptedCommands({Cmd.BUILD: [failing(Cmd.BUILD, TS_ERROR)]})
    agent = agent_with(project, llm=llm, commands=cmds)
    out = build.run(agent.ctx)
    assert not out.passed and out.attempts == 1 and "no applicable change" in out.reason
    assert cmds.count(Cmd.BUILD) == 1


def test_graph_conflict_is_reported_not_silently_fixed(project):
    cmds = ScriptedCommands({Cmd.BUILD: [failing(Cmd.BUILD, TS_ERROR)]})
    agent = agent_with(project, llm=FixingLLM(decision="graph_conflict"), commands=cmds)
    before = agent.ctx.workspace.read(BADGE)
    with pytest.raises(AgentError) as e:
        build.run(agent.ctx)
    assert e.value.kind is ErrorKind.GRAPH_CONFLICT
    assert agent.ctx.workspace.read(BADGE) == before  # nothing edited
    report = make_agent(project, llm=FixingLLM(decision="graph_conflict"), commands=cmds).generate()
    assert report["errors"][-1]["kind"] == "GRAPH_CONFLICT"


def test_corrections_may_not_remove_required_form_fields(project):
    # the "fix" compiles but drops the graph-defined 'name' field from the form
    llm = FixingLLM(edit=lambda f: f["content"].replace("'name'", "'nom'"))
    form = "src/features/projects/components/ProjectForm.tsx"
    cmds = ScriptedCommands({Cmd.BUILD: [failing(Cmd.BUILD, f"{form}(10,1): error TS2304: Cannot find name 'x'.")]})
    agent = agent_with(project, llm=llm, commands=cmds)
    before = agent.ctx.workspace.read(form)
    out = build.run(agent.ctx)
    assert not out.passed
    assert agent.ctx.workspace.read(form) == before  # reverted
    assert any("form_field_removed" in h or "required form field" in " ".join(h["rejected"]) for h in out.history) or "no applicable change" in out.reason
    assert "violate the graph" in " ".join(out.history[0]["rejected"])


def test_corrections_cannot_weaken_tests(project):
    spec = "tests/e2e/project-create.spec.ts"
    llm = FixingLLM(edit=lambda f: f["content"].replace("expect(", "void (").replace("test(", "void ("))
    browser = ScriptedBrowser(e2e=[BrowserRunResult(None, [outcome("x", "failed", "boom", spec)])])
    agent = agent_with(project, llm=llm, browser=browser, at="BUILT")
    before = agent.ctx.workspace.read(spec)
    out = browser_testing.run(agent.ctx)
    assert not out.passed
    assert agent.ctx.workspace.read(spec) == before
    assert "removes" in " ".join(out.history[0]["rejected"])


def test_correction_cannot_touch_files_that_were_not_offered(project):
    llm = FixingLLM()
    llm._fix = lambda c: {"decision": "fix_implementation", "explanation": "", "files": [{"path": "src/lib/permissions.ts", "content": "export {}"}]}
    cmds = ScriptedCommands({Cmd.BUILD: [failing(Cmd.BUILD, TS_ERROR)]})
    agent = agent_with(project, llm=llm, commands=cmds)
    with pytest.raises(LLMError, match="not offered"):
        build.run(agent.ctx)


def test_each_tool_failure_has_its_own_error_kind():
    mk = lambda cmd, out: failure_from_command({Cmd.TYPECHECK: "typescript", Cmd.LINT: "lint", Cmd.BUILD: "build", Cmd.TEST: "unit_tests"}[cmd], failing(cmd, out))
    assert mk(Cmd.TYPECHECK, TS_ERROR).kind is ErrorKind.TYPE_ERROR
    assert mk(Cmd.LINT, "src/a.tsx\n  3:1  error  'x' is defined but never used").kind is ErrorKind.LINT_ERROR
    assert mk(Cmd.BUILD, TS_ERROR).kind is ErrorKind.BUILD_ERROR
    f = mk(Cmd.TEST, "FAIL  tests/unit/ProjectForm.test.tsx > ProjectForm > submits\nAssertionError")
    assert f.kind is ErrorKind.FUNCTIONAL_TEST_ERROR and f.files == ["tests/unit/ProjectForm.test.tsx"]
    assert mk(Cmd.TYPECHECK, TS_ERROR).files == [BADGE]


# ----------------------------------------------------------------------------- browser loop
E2E_FILE = "tests/e2e/project-create.spec.ts"


def test_browser_failure_is_a_functional_test_error_and_triggers_a_correction(project):
    bad = BrowserRunResult(None, [outcome("ac.project.create", "failed", "expect(locator).toBeVisible() failed", E2E_FILE), outcome("other")])
    ok = BrowserRunResult(None, [outcome("ac.project.create"), outcome("other")])
    browser = ScriptedBrowser(e2e=[bad, ok])
    agent = agent_with(project, browser=browser, at="BUILT")
    out = browser_testing.run(agent.ctx)
    assert out.passed and out.attempts == 1 and browser.e2e_calls == 2
    assert out.history[0]["kind"] == "FUNCTIONAL_TEST_ERROR"
    assert agent.ctx.attempts["functional"] == 1 and agent.ctx.dirty
    assert agent.ctx.status.state.value == "BROWSER_TESTED"
    assert agent.ctx.results["e2e_tests"] == "passed"


def test_browser_loop_is_bounded(project):
    bad = BrowserRunResult(None, [outcome("t", "failed", "nope", E2E_FILE)])
    browser = ScriptedBrowser(e2e=[bad])
    agent = agent_with(project, browser=browser, at="BUILT")
    out = browser_testing.run(agent.ctx)
    assert not out.passed and out.attempts == 3 and browser.e2e_calls == 4


def test_browser_graph_conflict_is_reported(project):
    bad = BrowserRunResult(None, [outcome("t", "failed", "nope", E2E_FILE)])
    agent = agent_with(project, llm=FixingLLM(decision="graph_conflict"), browser=ScriptedBrowser(e2e=[bad]), at="BUILT")
    with pytest.raises(AgentError) as e:
        browser_testing.run(agent.ctx)
    assert e.value.kind is ErrorKind.GRAPH_CONFLICT


@pytest.mark.parametrize(
    "title,error,kind",
    [
        ("a", "expect(received).toEqual(expected)", ErrorKind.FUNCTIONAL_TEST_ERROR),
        ("a", "RUNTIME_ERROR: uncaught errors in the page", ErrorKind.RUNTIME_ERROR),
        ("a", "API_CONTRACT_ERROR: requests to endpoints missing from api.json", ErrorKind.API_CONTRACT_ERROR),
        ("a", "page.goto: net::ERR_CONNECTION_REFUSED", ErrorKind.NETWORK_ERROR),
        ("x > [a11y] screen.login has no violations", "", ErrorKind.ACCESSIBILITY_ERROR),
        ("a", "ACCESSIBILITY_ERROR: color-contrast", ErrorKind.ACCESSIBILITY_ERROR),
    ],
)
def test_browser_failures_are_classified(title, error, kind):
    assert classify_browser_failure(outcome(title, "failed", error)) is kind


def test_unavailable_browser_is_reported_not_ignored(project):
    browser = ScriptedBrowser(e2e=[BrowserRunResult(None, [], infrastructure_error="chromium missing")])
    agent = agent_with(project, browser=browser, limits=Limits(max_functional_correction_attempts=0), at="BUILT")
    out = browser_testing.run(agent.ctx)
    assert not out.passed and out.last_failure.kind is ErrorKind.RUNTIME_ERROR and agent.ctx.results["e2e_tests"] == "failed"


# ----------------------------------------------------------------------------- visual loop
def captures(overflow_on: set[tuple[str, str]] = frozenset()):
    def run(shot_dir):
        for s in ("screen.project.list", "screen.dashboard"):
            for vp in ("desktop", "tablet", "mobile"):
                bad = (s, vp) in overflow_on
                write_capture(shot_dir, s, vp, horizontalOverflow=bad, documentWidth=1500 if bad else 390,
                              overflowingElements=[{"selector": "table", "right": 1500, "width": 1500}] if bad else [])
        return BrowserRunResult(None, [outcome("captured")])

    return run


def test_visual_defect_is_a_visual_error_and_triggers_a_correction(project):
    browser = ScriptedBrowser(visual=[captures({("screen.project.list", "mobile")}), captures()])
    agent = agent_with(project, browser=browser, at="BROWSER_TESTED")
    out = visual_testing.run(agent.ctx)
    assert out.passed and out.attempts == 1 and browser.visual_calls == 2
    h = out.history[0]
    assert h["kind"] == "VISUAL_ERROR" and any("ProjectListPage" in p or "ProjectTable" in p for p in h["applied"])
    assert agent.ctx.attempts["visual"] == 1 and agent.ctx.results["visual_tests"] == "passed"
    assert agent.ctx.status.state.value == "VISUALLY_TESTED"


def test_visual_loop_is_bounded(project):
    browser = ScriptedBrowser(visual=[captures({("screen.project.list", "mobile")})])
    agent = agent_with(project, browser=browser, at="BROWSER_TESTED")
    out = visual_testing.run(agent.ctx)
    assert not out.passed and out.attempts == 3 and browser.visual_calls == 4
    assert out.last_failure.issues[0]["type"] == "overflow" and agent.ctx.results["visual_tests"] == "failed"


def test_vision_model_issues_are_merged_with_metric_issues(project):
    class Vision(FixingLLM):
        def _stage_visual_analysis(self, c):
            return {"issues": [{"severity": "high", "type": "layout", "description": "Overlapping header", "location": "AppLayout", "recommended_fix": "wrap", "viewport": "mobile"}] if c["screen"] == "screen.dashboard" else []}

    agent = agent_with(project, llm=Vision(), browser=ScriptedBrowser(visual=[captures()]), limits=Limits(max_visual_correction_attempts=0), at="BROWSER_TESTED")
    out = visual_testing.run(agent.ctx)
    assert not out.passed
    issues = agent.ctx.results["visual_issues"]
    assert issues[0]["source"] == "vision" and issues[0]["screen"] == "screen.dashboard"


def test_full_pipeline_with_scripted_tools_reaches_completed(project):
    browser = ScriptedBrowser(e2e=[BrowserRunResult(None, [outcome("ac.x"), outcome("x > [a11y] screen.login ok")])], visual=[captures()])
    agent = make_agent(project, llm=MockLLMProvider(), browser=browser)
    report = agent.generate()
    assert report["status"] == "passed", report["errors"]
    states = [h["state"] for h in report["pipeline"]["history"]]
    order = ["LOADING_GRAPHS", "GRAPHS_VALIDATED", "ANALYZED", "ARCHITECTED", "DESIGN_GENERATED", "PLANNED", "GENERATED", "STATIC_VALIDATION", "BUILT", "BROWSER_TESTED", "VISUALLY_TESTED", "FINAL_VALIDATION", "COMPLETED"]
    assert [s for s in states if s in order] == order
    val = (project / "frontend-artifacts" / "frontend_validation_report.json")
    import json

    v = json.loads(val.read_text())
    assert v["status"] == "passed" and all(c["passed"] for c in v["checklist"]) and len(v["checklist"]) == 21
    assert {k: v[k] for k in ("typescript", "lint", "build", "unit_tests", "e2e_tests", "visual_tests", "accessibility_tests")} == {k: "passed" for k in ("typescript", "lint", "build", "unit_tests", "e2e_tests", "visual_tests", "accessibility_tests")}
    assert v["correction_attempts"] == {"build": 0, "functional": 0, "visual": 0}
    rep = json.loads((project / "frontend-artifacts" / "frontend_report.json").read_text())
    assert rep["project"] == "task_manager" and rep["graph_version"] == "1.0.0" and rep["routes"] and rep["components"] and rep["api_integrations"] and rep["tests"]
    assert json.loads((project / "frontend-artifacts" / "pipeline_state.json").read_text())["state"] == "COMPLETED"


def test_final_validation_reruns_everything_after_late_corrections(project):
    browser = ScriptedBrowser(e2e=[BrowserRunResult(None, [outcome("ac.x"), outcome("x > [a11y] ok")])], visual=[captures({("screen.project.list", "mobile")}), captures()])
    cmds = ScriptedCommands()
    agent = make_agent(project, llm=FixingLLM(), commands=cmds, browser=browser)
    report = agent.generate()
    assert report["status"] == "passed" and report["correction_attempts"]["visual"] == 1
    assert cmds.count(Cmd.BUILD) >= 2  # build ran again for the final proof because files changed after the build gate
    assert browser.e2e_calls >= 2
