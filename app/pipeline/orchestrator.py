"""The Python-controlled lifecycle (spec 66-67). The LLM works *inside* stages; it never decides what runs next."""
from __future__ import annotations

import shutil
from pathlib import Path

from app.artifacts.repository import ArtifactRepository
from app.config.settings import Limits, Settings
from app.domain.models.errors import AgentError, ErrorKind, GraphError, Issue
from app.domain.models.state import PipelineState, PipelineStatus
from app.execution.browser_runner import BrowserRunner, PlaywrightBrowserRunner
from app.execution.command_runner import CommandRunner, SubprocessCommandRunner
from app.generation.file_generator import FileWorkspace
from app.graph.context_builder import ContextBuilder
from app.graph.loader import load_graph_package
from app.llm.base import LLMProvider
from app.observability import EventLog
from app.pipeline import (
    analysis, api_integration, architecture, browser_testing, build, code_generation, code_review, component_planning, design_system,
    final_review, page_planning, state_management, visual_testing,
)
from app.pipeline.context import RunContext
from app.pipeline.stage import PromptLibrary, StageRunner
from app.validation.api_validation import check_api_coverage
from app.validation.graph_validation import assert_valid
from app.validation.permission_validation import check_permissions

FRONTEND_DIR = "frontend"
ARTIFACTS_DIR = "frontend-artifacts"
LOGS_DIR = "logs"


class FrontendAgent:
    def __init__(
        self,
        project_dir: str | Path,
        llm: LLMProvider,
        *,
        settings: Settings | None = None,
        commands: CommandRunner | None = None,
        browser: BrowserRunner | None = None,
        incremental: bool = False,
        skip_install: bool = False,
    ):
        self.settings = settings or Settings()
        project_dir = Path(project_dir).resolve()
        self.project_dir = project_dir
        limits = self.settings.limits
        self.commands = commands or SubprocessCommandRunner(timeout_s=limits.command_timeout_s)
        self.browser = browser or PlaywrightBrowserRunner(self.commands)
        events = EventLog(project_dir / LOGS_DIR / "agent.jsonl", secrets=(self.settings.llm.api_key,))
        self.ctx = RunContext(
            project_dir=project_dir, workspace=FileWorkspace(project_dir / FRONTEND_DIR), artifacts=ArtifactRepository(project_dir / ARTIFACTS_DIR),
            events=events, llm=llm, runner=StageRunner(llm, events, PromptLibrary(), limits.max_llm_output_retries), commands=self.commands,
            browser=self.browser, limits=limits, incremental=incremental, skip_install=skip_install,
        )
        self.ctx.status.listener = lambda st: self.ctx.artifacts.save("pipeline_state.json", st.to_dict())

    # ------------------------------------------------------------------ graph gate
    def load_and_validate(self) -> list[Issue]:
        ctx = self.ctx
        ctx.graph = load_graph_package(self.project_dir)
        warnings = assert_valid(ctx.graph)  # raises GraphError
        conflicts = check_api_coverage(ctx.graph)
        hard = [i for i in conflicts if i.kind in (ErrorKind.GRAPH_IMPLEMENTATION_CONFLICT, ErrorKind.GRAPH_ERROR)]
        if hard:
            raise AgentError(ErrorKind.GRAPH_IMPLEMENTATION_CONFLICT, "The graphs cannot be implemented as specified: " + "; ".join(i.message for i in hard), hard)
        perm_issues = [i for i in check_permissions(ctx.graph) if i.severity == "error"]
        if perm_issues:
            raise GraphError(perm_issues)
        ctx.contexts = ContextBuilder(ctx.graph)
        if hasattr(ctx.llm, "bind_graph"):
            ctx.llm.bind_graph(ctx.graph)  # offline mock needs the graph to synthesise fixtures
        ctx.results["graph_validation"] = "passed"
        ctx.warnings += [i.message for i in warnings]
        return warnings

    def validate(self) -> list[Issue]:
        return self.load_and_validate()

    # ------------------------------------------------------------------ full pipeline
    def generate(self) -> dict:
        ctx = self.ctx
        try:
            self._prepare_workspace()
            ctx.status.advance(PipelineState.LOADING_GRAPHS)
            with ctx.events.stage("load_and_validate_graphs"):
                self.load_and_validate()
            ctx.status.advance(PipelineState.GRAPHS_VALIDATED)

            with ctx.events.stage("analysis"):
                analysis.run(ctx)
            ctx.status.advance(PipelineState.ANALYZED)
            with ctx.events.stage("architecture"):
                architecture.run(ctx)
            ctx.status.advance(PipelineState.ARCHITECTED)
            with ctx.events.stage("design_system"):
                design_system.run(ctx)
            ctx.status.advance(PipelineState.DESIGN_GENERATED)
            with ctx.events.stage("planning"):
                from app.generation.symbols import build_api_bindings

                ctx.bindings = build_api_bindings(ctx.g)
                page_planning.run(ctx)
                component_planning.run(ctx)
                api_integration.run(ctx)
                state_management.run(ctx)
            ctx.status.advance(PipelineState.PLANNED)
            with ctx.events.stage("code_generation") as extra:
                code_generation.run(ctx)
                extra["files"] = len(ctx.files)
            ctx.status.advance(PipelineState.GENERATED)
            with ctx.events.stage("code_review"):
                code_review.run(ctx)

            with ctx.events.stage("build") as extra:
                out = build.run(ctx)
                extra["attempts"] = out.attempts
            if not out.passed:
                return self._fail(out.last_failure.kind if out.last_failure else ErrorKind.BUILD_ERROR, out.reason, out)
            with ctx.events.stage("browser_tests") as extra:
                out = browser_testing.run(ctx)
                extra["attempts"] = out.attempts
            if not out.passed:
                return self._fail(out.last_failure.kind if out.last_failure else ErrorKind.FUNCTIONAL_TEST_ERROR, out.reason, out)
            with ctx.events.stage("visual_tests") as extra:
                out = visual_testing.run(ctx)
                extra["attempts"] = out.attempts
            if not out.passed:
                return self._fail(out.last_failure.kind if out.last_failure else ErrorKind.VISUAL_ERROR, out.reason, out)
            with ctx.events.stage("final_validation"):
                final_review.run(ctx)
            return final_review.write_report(ctx, "passed")
        except AgentError as e:
            return self._fail(e.kind, str(e), None, e.issues)

    def _fail(self, kind: ErrorKind, message: str, outcome=None, issues: list[Issue] | None = None) -> dict:
        ctx = self.ctx
        err = {"kind": kind.value, "message": message[:2000]}
        if outcome is not None and outcome.last_failure is not None:
            err["failure"] = outcome.last_failure.to_dict()
            err["correction_history"] = outcome.history
        if issues:
            err["issues"] = [i.to_dict() for i in issues][:40]
        ctx.errors.append(err)
        ctx.status.failure = err
        if ctx.status.state is not PipelineState.FAILED:
            ctx.status.advance(PipelineState.FAILED, message[:300])
        ctx.events.emit("pipeline_failed", **{k: v for k, v in err.items() if k in ("kind", "message")})
        ctx.artifacts.save("frontend_validation_report.json", {**final_review.validation_report(ctx, "failed"), "error": err})
        return final_review.write_report(ctx, "failed")

    def _prepare_workspace(self) -> None:
        """Fresh generation replaces the previous output (keeping node_modules); incremental runs keep it."""
        if self.ctx.incremental:
            return
        root = self.ctx.workspace.root
        for child in root.iterdir():
            if child.name == "node_modules":
                continue
            shutil.rmtree(child) if child.is_dir() else child.unlink()
        arts = self.ctx.artifacts.root
        for child in arts.iterdir():
            shutil.rmtree(child) if child.is_dir() else child.unlink()

    # ------------------------------------------------------------------ partial commands
    def _load_existing(self) -> None:
        ctx = self.ctx
        self.load_and_validate()
        ctx.screen_specs = ctx.artifacts.load_screen_specs()
        ctx.component_specs = ctx.artifacts.load_component_specs()
        if not ctx.screen_specs or not ctx.workspace.exists("package.json"):
            raise AgentError(ErrorKind.BUILD_ERROR, f"No generated frontend found in {ctx.workspace.root}. Run `generate` first.")
        for rec in ctx.artifacts.load_file_manifest():
            ctx.files[rec.path] = rec
        ctx.tests = ctx.artifacts.load_test_manifest()
        ctx.design_system = ctx.artifacts.load("design_system.json")
        ctx.contexts.design_system = ctx.design_system
        from app.generation.symbols import build_api_bindings

        ctx.bindings = build_api_bindings(ctx.g)

    def test(self) -> dict:
        """Static validation + build + unit tests of an already generated frontend (no corrections)."""
        ctx = self.ctx
        self._load_existing()
        build.install_dependencies(ctx)
        failure = build.run_checks(ctx)
        return {"passed": failure is None, "results": {k: ctx.results.get(k, "not_run") for k in ("typescript", "lint", "build", "unit_tests")}, "failure": failure.to_dict() if failure else None}

    def browser_test(self, visual: bool = True) -> dict:
        """Run Playwright e2e (+ visual capture/analysis) against the generated frontend (no corrections)."""
        ctx = self.ctx
        self._load_existing()
        build.install_dependencies(ctx)
        res = ctx.browser.run_e2e(ctx.workspace.root)
        ctx.results.update(browser_testing.summarise(res))
        out = {"e2e": browser_testing.summarise(res), "failures": [{"title": t.title, "error": t.error[:500]} for t in res.failures], "infrastructure_error": res.infrastructure_error or None}
        if visual:
            caps, fail = visual_testing.capture_all(ctx)
            if fail:
                out["visual"] = {"status": "failed", "failure": fail.to_dict()}
            else:
                issues = visual_testing.analyse(ctx, caps)
                out["visual"] = {"status": "failed" if any(i.blocking for i in issues) else "passed", "screenshots": len(caps), "issues": [i.to_dict() for i in issues]}
        out["passed"] = res.ok and (not visual or out["visual"]["status"] == "passed")
        return out
