"""Functional + accessibility browser testing with Playwright, with bounded correction (spec 34-36, 40)."""
from __future__ import annotations

from app.domain.models.state import PipelineState
from app.execution.browser_runner import BrowserRunResult
from app.pipeline.build import QUICK_STEPS, run_checks
from app.pipeline.context import RunContext
from app.pipeline.failures import Failure, failure_from_browser
from app.pipeline.loop import LoopOutcome, correction_loop


def summarise(res: BrowserRunResult) -> dict:
    a11y = [t for t in res.tests if t.title.split(" > ")[-1].startswith("[a11y]")]
    func = [t for t in res.tests if t not in a11y]
    st = lambda ts: "passed" if ts and not any(t.failed for t in ts) else ("failed" if any(t.failed for t in ts) else "not_run")
    return {"e2e_tests": st(func), "accessibility_tests": st(a11y), "total": len(res.tests), "passed": res.passed, "failed": len(res.failures)}


def detect_once(ctx: RunContext) -> Failure | None:
    """Static sanity first (a correction may have broken compilation), then the real browser."""
    f = run_checks(ctx, QUICK_STEPS)
    if f:
        return f
    res = ctx.browser.run_e2e(ctx.workspace.root)
    ctx.results.update(summarise(res))
    ctx.results["e2e_report"] = [{"title": t.title, "status": t.status} for t in res.tests]
    if res.infrastructure_error:
        ctx.results["e2e_tests"] = "failed"
        from app.domain.models.errors import ErrorKind

        return Failure(ErrorKind.RUNTIME_ERROR, "e2e", "Playwright could not run", res.infrastructure_error)
    if not res.tests:
        from app.domain.models.errors import ErrorKind

        return Failure(ErrorKind.FUNCTIONAL_TEST_ERROR, "e2e", "no browser tests were discovered")
    if res.failures:
        return failure_from_browser(res.failures)
    return None


def run(ctx: RunContext) -> LoopOutcome:
    outcome = correction_loop(ctx, "functional", ctx.limits.max_functional_correction_attempts, lambda: detect_once(ctx))
    if outcome.passed:
        ctx.status.advance(PipelineState.BROWSER_TESTED)
    return outcome
