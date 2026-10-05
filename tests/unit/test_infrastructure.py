"""Safety (files, commands), LLM providers, retries, observability, parsing helpers, state machine, prompts."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import httpx
import pytest

from app.config.settings import LLMSettings, Limits, Settings
from app.domain.models.errors import LLMError, SafetyError
from app.domain.models.state import InvalidTransition, PipelineState, PipelineStatus
from app.execution.browser_runner import parse_playwright_report
from app.execution.command_runner import Cmd, SubprocessCommandRunner
from app.generation.design_defaults import contrast_ratio, default_design_system, validate_design_system
from app.generation.file_generator import FileWorkspace
from app.llm.base import LLMRequest, LLMResponse, extract_json
from app.llm.factory import create_provider
from app.llm.mock import MockLLMProvider
from app.llm.ollama import OllamaProvider
from app.llm.openai_compatible import OpenAICompatibleProvider
from app.observability import EventLog, redact
from app.pipeline.stage import PROMPTS_DIR, PromptLibrary, StageRunner
from app.pipeline.visual_testing import issues_from_metrics, parse_issues
from app.validation.frontend_validation import check_generated_source
from tests.conftest import write_capture

REPO = Path(__file__).resolve().parents[2]


# ----------------------------------------------------------------------------- file safety (spec 53)
@pytest.mark.parametrize("bad", ["../escape.ts", "/etc/passwd", "src/../../x.ts", "src/.env", "node_modules/x/index.ts", "src\\x.ts", ".git/config"])
def test_workspace_rejects_unsafe_paths(tmp_path, bad):
    ws = FileWorkspace(tmp_path / "fe")
    with pytest.raises(SafetyError):
        ws.write(bad, "x")
    assert not (tmp_path / "escape.ts").exists()


@pytest.mark.parametrize("path", ["package.json", "vite.config.ts", "scripts/run.sh", "src/evil.sh", "src/x.exe", "tests/x.py"])
def test_llm_may_only_write_source_and_test_files(tmp_path, path):
    ws = FileWorkspace(tmp_path / "fe")
    with pytest.raises(SafetyError):
        ws.write(path, "x", from_llm=True)


def test_workspace_accepts_normal_generated_files(tmp_path):
    ws = FileWorkspace(tmp_path / "fe")
    ws.write("src/features/a/B.tsx", "export const B = 1;", from_llm=True)
    assert ws.read("src/features/a/B.tsx").endswith("\n") and ws.list_files() == ["src/features/a/B.tsx"]


def test_oversized_files_are_rejected(tmp_path):
    with pytest.raises(SafetyError):
        FileWorkspace(tmp_path).write("src/a.ts", "x" * 500_000)


def test_generated_source_rules():
    assert check_generated_source("src/a.tsx", "export const A = () => <div dangerouslySetInnerHTML={{ __html: x }} />;")
    assert check_generated_source("src/a.tsx", "export const A = () => { eval('1'); return null; };")
    assert check_generated_source("src/features/a/B.tsx", "export const B = () => { void fetch('/x'); return null; };")  # raw HTTP outside lib/api
    assert not check_generated_source("src/lib/api/a.ts", "export const a = () => fetch('/x');")
    assert check_generated_source("src/a.tsx", "export const a = (")  # unbalanced
    assert check_generated_source("src/a.tsx", "")
    assert check_generated_source("src/a.ts", "export const key = { password: 'hunter2hunter2' };")


# ----------------------------------------------------------------------------- command safety (spec 54)
def test_only_predefined_commands_exist():
    assert {c.name for c in Cmd} == {"INSTALL", "BUILD", "TYPECHECK", "LINT", "TEST", "TEST_E2E", "TEST_VISUAL", "DEV"}
    assert Cmd.BUILD.argv == ["npm", "run", "build"] and Cmd.INSTALL.argv[:2] == ["npm", "install"]


def test_runner_refuses_arbitrary_commands(tmp_path):
    r = SubprocessCommandRunner()
    with pytest.raises(SafetyError):
        r.run("rm -rf /", tmp_path)  # type: ignore[arg-type]
    with pytest.raises(SafetyError):
        r.run(["npm", "run", "evil"], tmp_path)  # type: ignore[arg-type]
    with pytest.raises(SafetyError):
        r.run(Cmd.DEV, tmp_path)


def test_runner_passes_only_whitelisted_env_and_fixed_argv(tmp_path, monkeypatch):
    seen = {}

    def fake_run(argv, cwd, env, capture_output, text, timeout):
        seen.update(argv=argv, cwd=cwd, env=env, timeout=timeout)
        return subprocess.CompletedProcess(argv, 0, "out", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    res = SubprocessCommandRunner(timeout_s=7).run(Cmd.BUILD, tmp_path, {"PW_JSON_OUT": "r.json", "LD_PRELOAD": "evil.so", "SCREENSHOT_DIR": "/x"})
    assert res.ok and seen["argv"] == ["npm", "run", "build"] and seen["timeout"] == 7
    assert seen["env"]["PW_JSON_OUT"] == "r.json" and seen["env"].get("LD_PRELOAD") != "evil.so"


def test_runner_reports_timeouts_and_missing_binaries(tmp_path, monkeypatch):
    def timeout(*a, **k):
        raise subprocess.TimeoutExpired(a[0], 1, output=b"partial")

    monkeypatch.setattr(subprocess, "run", timeout)
    r = SubprocessCommandRunner().run(Cmd.TEST, tmp_path)
    assert r.timed_out and not r.ok and r.exit_code == 124

    def missing(*a, **k):
        raise FileNotFoundError(2, "no", "npm")

    monkeypatch.setattr(subprocess, "run", missing)
    assert SubprocessCommandRunner().run(Cmd.TEST, tmp_path).exit_code == 127


# ----------------------------------------------------------------------------- LLM providers (spec 48-49)
def transport(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_ollama_provider_request_and_response(tmp_path):
    seen = {}

    def handler(req: httpx.Request):
        seen["url"], seen["body"] = str(req.url), json.loads(req.content)
        return httpx.Response(200, json={"message": {"content": '{"ok": true}'}, "prompt_eval_count": 11, "eval_count": 5})

    p = OllamaProvider(LLMSettings(provider="ollama", model="m", vision_model="vm", base_url="http://llm:11434/"), transport(handler))
    img = tmp_path / "a.png"
    img.write_bytes(b"png")
    r = p.generate(LLMRequest("s", "hello", system="sys", images=[img]))
    assert seen["url"] == "http://llm:11434/api/chat" and seen["body"]["model"] == "vm" and seen["body"]["format"] == "json"
    assert seen["body"]["messages"][0] == {"role": "system", "content": "sys"} and seen["body"]["messages"][1]["images"]
    assert r.json() == {"ok": True} and (r.prompt_tokens, r.completion_tokens) == (11, 5)


def test_openai_compatible_provider_sends_key_and_never_leaks_it(tmp_path):
    seen = {}

    def ok(req: httpx.Request):
        seen["auth"], seen["body"], seen["url"] = req.headers.get("authorization"), json.loads(req.content), str(req.url)
        return httpx.Response(200, json={"choices": [{"message": {"content": "```json\n{\"a\": 1}\n```"}}], "usage": {"prompt_tokens": 3, "completion_tokens": 4}})

    s = LLMSettings(provider="openai", model="gpt", base_url="http://x/v1", api_key="sk-secret-secret-secret")
    p = OpenAICompatibleProvider(s, transport(ok))
    img = tmp_path / "a.png"
    img.write_bytes(b"png")
    r = p.generate(LLMRequest("s", "hi", images=[img]))
    assert seen["auth"] == "Bearer sk-secret-secret-secret" and seen["url"] == "http://x/v1/chat/completions"
    assert seen["body"]["response_format"] == {"type": "json_object"} and seen["body"]["messages"][0]["content"][1]["type"] == "image_url"
    assert r.json() == {"a": 1} and r.prompt_tokens == 3

    bad = OpenAICompatibleProvider(s, transport(lambda req: httpx.Response(500, text="boom sk-secret-secret-secret")))
    with pytest.raises(LLMError) as e:
        bad.generate(LLMRequest("s", "hi"))
    assert "sk-secret" not in str(e.value)


def test_provider_factory_and_env_configuration(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_MODEL", "my-model")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:1234/v1")
    monkeypatch.setenv("LLM_API_KEY", "abc")
    s = LLMSettings.from_env()
    assert (s.provider, s.model, s.base_url, s.api_key) == ("openai", "my-model", "http://localhost:1234/v1", "abc")
    assert "abc" not in repr(s)  # secrets are not printed
    assert isinstance(create_provider(s), OpenAICompatibleProvider)
    assert isinstance(create_provider(LLMSettings(provider="ollama", model="m")), OllamaProvider)
    assert isinstance(create_provider(s, mock=True), MockLLMProvider)
    with pytest.raises(LLMError):
        create_provider(LLMSettings(provider="carrier-pigeon", model="m"))
    with pytest.raises(LLMError):
        create_provider(LLMSettings(provider="ollama", model=""))


def test_limits_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("MAX_BUILD_CORRECTION_ATTEMPTS", "5")
    monkeypatch.setenv("MAX_VISUAL_CORRECTION_ATTEMPTS", "not-a-number")
    lim = Limits.from_env()
    assert lim.max_build_correction_attempts == 5 and lim.max_visual_correction_attempts == 3 and Settings().limits.max_functional_correction_attempts == 3


def test_extract_json_tolerates_fences_and_prose():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('Sure!\n```json\n{"a": [1, 2]}\n```\nbye') == {"a": [1, 2]}
    assert extract_json('prefix {"a": {"b": 2}} suffix') == {"a": {"b": 2}}
    with pytest.raises(LLMError):
        extract_json("no json here")


# ----------------------------------------------------------------------------- stage runner + retry limits
class Scripted:
    name = "scripted"

    def __init__(self, replies):
        self.replies, self.calls, self.prompts = list(replies), 0, []

    def generate(self, req):
        self.calls += 1
        self.prompts.append(req.prompt)
        r = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return LLMResponse(r)


def runner(llm, retries=2):
    return StageRunner(llm, EventLog(), PromptLibrary(), retries)


def test_llm_output_retries_are_bounded():
    llm = Scripted(["not json"])
    with pytest.raises(LLMError, match="failed validation after 3 attempts"):
        runner(llm, retries=2).call("graph_analysis", {"x": 1})
    assert llm.calls == 3


def test_invalid_structured_output_is_fed_back_and_retried_once_valid():
    llm = Scripted(['{"summary": ""}', '{"summary": "ok", "risks": [], "implementation_notes": []}'])
    from app.pipeline.analysis import _validate

    out = runner(llm).call("graph_analysis", {"x": 1}, _validate)
    assert out["summary"] == "ok" and llm.calls == 2
    assert "Problems with your previous answer" in llm.prompts[1] and "summary" in llm.prompts[1]


def test_context_is_rendered_into_the_prompt_file():
    llm = Scripted(['{"a": 1}'])
    runner(llm).call("graph_analysis", {"marker_value": "XYZ-123"})
    assert "XYZ-123" in llm.prompts[0] and "{{CONTEXT}}" not in llm.prompts[0]


# ----------------------------------------------------------------------------- prompts (spec 7)
STAGES = ["graph_analysis", "frontend_architecture", "design_system", "page_planning", "component_planning", "api_integration", "state_management", "code_generation", "code_review",
          "build_error_correction", "browser_error_analysis", "visual_analysis", "correction", "final_review"]


def test_every_llm_stage_has_its_own_prompt_file():
    assert set(STAGES) <= set(PromptLibrary().names())
    for s in STAGES:
        text = (PROMPTS_DIR / f"{s}.md").read_text()
        assert "{{CONTEXT}}" in text and "# Output" in text and len(text) > 400


def test_all_called_stages_have_prompts_and_no_prompts_live_in_python():
    called = set()
    for p in (REPO / "app").rglob("*.py"):
        called |= set(re.findall(r'\.call\(\s*"([a-z_]+)"', p.read_text()))
        if "mock_fixtures" not in p.parts:
            assert "# Role" not in p.read_text() and "You are a senior" not in p.read_text(), p
    assert called and called <= set(PromptLibrary().names())


# ----------------------------------------------------------------------------- pipeline state machine
def test_pipeline_state_machine_enforces_order():
    st = PipelineStatus()
    with pytest.raises(InvalidTransition):
        st.advance(PipelineState.BUILT)
    for s in ("LOADING_GRAPHS", "GRAPHS_VALIDATED", "ANALYZED"):
        st.advance(PipelineState(s))
    with pytest.raises(InvalidTransition):
        st.advance(PipelineState.GENERATED)
    st.advance(PipelineState.FAILED, "x")  # FAILED is reachable from anywhere
    assert st.state is PipelineState.FAILED and st.to_dict()["history"][-1]["status"] == "failed"
    with pytest.raises(InvalidTransition):
        st.advance(PipelineState.ARCHITECTED)


def test_state_is_persisted_after_every_transition(project):
    from tests.conftest import make_agent

    agent = make_agent(project)
    agent._prepare_workspace()
    agent.plan_and_generate()
    saved = json.loads((project / "frontend-artifacts" / "pipeline_state.json").read_text())
    assert saved["state"] == "GENERATED" and [h["state"] for h in saved["history"]][-1] == "GENERATED"


# ----------------------------------------------------------------------------- observability (spec 63)
def test_secrets_are_redacted_from_logs(tmp_path):
    log = EventLog(tmp_path / "l.jsonl", secrets=("topsecretvalue",))
    log.emit("x", api_key="sk-abcdefghijklmnop", password="p", note="Bearer abc.def.ghi and topsecretvalue", nested={"token": "t", "ok": 1})
    line = (tmp_path / "l.jsonl").read_text()
    for leak in ("sk-abcdefghijklmnop", "abc.def.ghi", "topsecretvalue", '"p"', '"t"'):
        assert leak not in line
    assert json.loads(line)["nested"]["ok"] == 1
    assert redact({"Authorization": "x"}) == {"Authorization": "***"}


def test_stage_events_record_duration_and_llm_calls(project):
    from tests.conftest import make_agent

    agent = make_agent(project)
    agent._prepare_workspace()
    agent.plan_and_generate()
    kinds = {e["event"] for e in agent.ctx.events.events}
    assert {"stage_start", "stage_done", "llm_call", "unit_generated", "deterministic_files"} <= kinds
    done = next(e for e in agent.ctx.events.events if e["event"] == "stage_done")
    assert "duration_s" in done
    assert (project / "logs" / "agent.jsonl").exists()


# ----------------------------------------------------------------------------- playwright report + visual parsing
SAMPLE_REPORT = {"suites": [{"title": "a.spec.ts", "file": "a.spec.ts", "specs": [], "suites": [{"title": "group", "specs": [
    {"title": "passes", "file": "a.spec.ts", "tests": [{"status": "expected", "results": [{"status": "passed", "duration": 12}]}]},
    {"title": "fails", "file": "a.spec.ts", "tests": [{"status": "unexpected", "results": [{"status": "failed", "duration": 5, "errors": [{"message": "\x1b[31mboom\x1b[0m"}]}]}]},
    {"title": "skipped", "file": "a.spec.ts", "tests": [{"status": "skipped", "results": [{"status": "skipped"}]}]}]}]}]}


def test_playwright_report_parsing():
    tests = parse_playwright_report(SAMPLE_REPORT)
    assert [(t.title, t.status) for t in tests] == [("group > passes", "passed"), ("group > fails", "failed"), ("group > skipped", "skipped")]
    assert tests[1].error == "boom" and tests[1].failed and not tests[2].failed


def test_visual_issue_parsing_is_strict():
    good = {"issues": [{"severity": "HIGH", "type": "layout", "description": "d", "location": "ProjectListPage", "recommended_fix": "f", "viewport": "mobile"}]}
    (issue,) = parse_issues(good, "screen.x")
    assert issue.blocking and issue.severity == "high" and issue.screen == "screen.x" and issue.viewport == "mobile" and issue.source == "vision"
    assert parse_issues({"issues": []}) == []
    for bad in ({"issues": "none"}, [], {"issues": [{"severity": "catastrophic"}]}, {"issues": ["x"]}):
        with pytest.raises(LLMError):
            parse_issues(bad)
    assert parse_issues({"issues": [{"severity": "low", "type": "weird"}]})[0].type == "other"


def test_layout_metrics_become_structured_defects(tmp_path):
    base = dict(viewport={"width": 390, "height": 800}, horizontalOverflow=False, documentWidth=390, overflowingElements=[], clippedText=[], smallTargets=[], overlappingControls=[],
                h1Count=1, mainTextLength=10, dialog=None, tables=[])
    assert issues_from_metrics("s", "mobile", base) == []
    over = issues_from_metrics("s", "mobile", {**base, "horizontalOverflow": True, "documentWidth": 900, "overflowingElements": [{"selector": "table", "right": 900, "width": 900}]})
    assert over[0].type == "overflow" and over[0].blocking and over[0].location == "table" and "900" in over[0].description
    assert any(i.type == "overlap" and i.blocking for i in issues_from_metrics("s", "desktop", {**base, "overlappingControls": [{"a": "a", "b": "b"}]}))
    assert any(i.type == "modal" for i in issues_from_metrics("s", "mobile", {**base, "dialog": {"insideViewport": False}}))
    assert any(i.type == "blank_area" for i in issues_from_metrics("s", "mobile", {**base, "mainTextLength": 0}))
    small = issues_from_metrics("s", "mobile", {**base, "smallTargets": [{"selector": "a", "width": 10, "height": 10}]})
    assert small and not small[0].blocking and issues_from_metrics("s", "desktop", {**base, "smallTargets": [{"selector": "a", "width": 10, "height": 10}]}) == []
    assert any(i.type == "table" for i in issues_from_metrics("s", "mobile", {**base, "tables": [{"selector": "t", "overflows": True}]}))
    from app.pipeline.visual_testing import load_captures

    write_capture(tmp_path / "shots", "screen.a", "mobile")
    (cap,) = load_captures(tmp_path / "shots")
    assert cap.screen == "screen.a" and cap.viewport == "mobile" and cap.png.exists()


# ----------------------------------------------------------------------------- design system
def test_default_design_system_is_valid_and_accessible():
    ds = default_design_system()
    assert validate_design_system(ds) == []
    assert contrast_ratio("#000000", "#ffffff") == pytest.approx(21)
    for k in ("typography", "spacing", "colors", "borders", "radius", "shadows", "components", "responsive"):
        assert k in ds
    assert set(ds["components"]) >= {"buttons", "inputs", "forms", "cards", "tables", "dialogs", "badges", "alerts", "navigation", "tabs", "dropdowns", "loading", "empty_states", "error_states"}


def test_design_system_validation_catches_problems():
    ds = default_design_system()
    ds["colors"]["primary"] = "#93c5fd"
    ds["colors"]["background"] = "blue"
    del ds["components"]["tables"]
    problems = " | ".join(validate_design_system(ds))
    assert "components.tables" in problems or "hex" in problems
    ds2 = default_design_system()
    ds2["colors"]["primary"] = "#93c5fd"
    assert any("contrast onPrimary on primary" in p for p in validate_design_system(ds2))
