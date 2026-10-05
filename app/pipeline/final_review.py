"""Stage 15 - final verification and reports (spec 46, 61, 68)."""
from __future__ import annotations

from datetime import datetime, timezone

from app.domain.models.state import PipelineState
from app.pipeline import browser_testing
from app.pipeline.build import STEPS, run_checks
from app.pipeline.context import RunContext
from app.validation.frontend_validation import verify_structure

STATUS_KEYS = ["typescript", "lint", "build", "unit_tests", "e2e_tests", "visual_tests", "accessibility_tests"]


def revalidate_if_dirty(ctx: RunContext) -> None:
    """Corrections after the build gate may have changed code: prove the final tree with one full, uncorrected run."""
    if not ctx.dirty:
        return
    ctx.events.emit("final_revalidation")
    f = run_checks(ctx, STEPS)
    if f is None:
        res = ctx.browser.run_e2e(ctx.workspace.root)
        ctx.results.update(browser_testing.summarise(res))
        if res.infrastructure_error or res.failures or not res.tests:
            from app.pipeline.failures import failure_from_browser
            from app.domain.models.errors import ErrorKind
            from app.pipeline.failures import Failure

            f = failure_from_browser(res.failures) if res.failures else Failure(ErrorKind.RUNTIME_ERROR, "e2e", "browser suite did not run", res.infrastructure_error)
    ctx.final_failure = f
    ctx.dirty = f is not None


def checklist(ctx: RunContext) -> list[dict]:
    r = ctx.results
    structure = verify_structure(ctx.g, ctx.workspace, ctx.screen_specs, ctx.component_specs, [t.path for t in ctx.tests])
    has = lambda kind: [i for i in structure if kind in i.code]
    ok = lambda v: v == "passed"
    states = {s: any(s in sp.states for sp in ctx.screen_specs) for s in ("loading", "empty", "error")}
    items = [
        ("Graph package valid", ctx.results.get("graph_validation") == "passed", ""),
        ("Frontend architecture generated", ctx.architecture is not None, ""),
        ("Design system generated", ctx.design_system is not None, ""),
        ("Required routes generated", not [i for i in structure if "route" in i.code], ""),
        ("Required pages generated", not [i for i in structure if i.code in ("missing_page", "missing_page_testid")], ""),
        ("Required workflows implemented", not [i for i in structure if i.code in ("missing_workflow_trigger", "transition_rule_missing", "form_field_removed")], ""),
        ("API contracts integrated", not has("api_not_integrated"), ""),
        ("Permission behaviour represented", not has("permission_not_applied"), ""),
        ("Forms validated", not [i for i in structure if i.code in ("form_field_removed", "missing_form_testid")], ""),
        ("Loading states implemented", states["loading"] and not [i for i in structure if i.code == "missing_state" and "loading" in i.message], ""),
        ("Empty states implemented", states["empty"] and not [i for i in structure if i.code == "missing_state" and "empty" in i.message], ""),
        ("Error states implemented", states["error"] and not [i for i in structure if i.code == "missing_state" and "error" in i.message], ""),
        ("TypeScript passes", ok(r.get("typescript")), ""),
        ("ESLint passes", ok(r.get("lint")), ""),
        ("Build passes", ok(r.get("build")), ""),
        ("Unit tests pass", ok(r.get("unit_tests")), ""),
        ("E2E tests pass", ok(r.get("e2e_tests")), ""),
        ("Browser tests pass", ok(r.get("e2e_tests")), ""),
        ("Visual inspection passes", ok(r.get("visual_tests")), ""),
        ("Accessibility checks pass", ok(r.get("accessibility_tests")), ""),
        ("No unresolved critical issues", not ctx.errors and not structure, ""),
    ]
    return [{"item": n, "passed": bool(p), "detail": d} for n, p, d in items]


def validation_report(ctx: RunContext, status: str) -> dict:
    r = ctx.results
    rep = {"status": status, "graph_validation": r.get("graph_validation", "not_run")}
    for k in STATUS_KEYS:
        rep[k] = r.get(k, "not_run")
    rep["correction_attempts"] = dict(ctx.attempts)
    rep["screenshots"] = r.get("screenshots", 0)
    return rep


def run(ctx: RunContext) -> dict:
    ctx.status.advance(PipelineState.FINAL_VALIDATION)
    revalidate_if_dirty(ctx)
    items = checklist(ctx)
    failed = [i["item"] for i in items if not i["passed"]]
    status = "passed" if not failed else "failed"
    context = {**ctx.contexts.base(), "report": validation_report(ctx, status), "checklist": items, "warnings": ctx.warnings[:30],
               "traceability": {p: rec.source_refs for p, rec in ctx.files.items() if rec.generator == "llm" and not p.startswith("tests/")}}

    def validate(out: object) -> list[str]:
        return [] if isinstance(out, dict) and out.get("verdict") in ("pass", "needs_attention") and isinstance(out.get("concerns", []), list) else ['expected {"verdict": "pass|needs_attention", "concerns": [...]}']

    review = ctx.runner.call("final_review", context, validate)
    for c in review.get("concerns", []):
        ctx.warnings.append(f"final_review: {c}")
    rep = validation_report(ctx, status)
    rep["checklist"] = items
    rep["unresolved"] = failed
    rep["final_review"] = review
    ctx.artifacts.save("frontend_validation_report.json", rep)
    if failed:
        from app.domain.models.errors import AgentError, ErrorKind

        kind = ctx.final_failure.kind if ctx.final_failure else ErrorKind.FUNCTIONAL_TEST_ERROR
        raise AgentError(kind, "Final validation failed: " + "; ".join(failed))
    ctx.status.advance(PipelineState.COMPLETED)
    return rep


def write_report(ctx: RunContext, status: str, error: dict | None = None) -> dict:
    g = ctx.graph
    report = {
        "project": g.project_id if g else ctx.project_dir.name,
        "status": status,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "graph_version": g.graph_version if g else None,
        "pipeline": ctx.status.to_dict(),
        "frontend_architecture": ctx.architecture,
        "routes": [{"path": s.route, "screen": s.screen_ref, "page": s.page_path} for s in ctx.screen_specs],
        "components": [{"ref": c.component_ref, "name": c.name, "path": c.path, "kind": c.kind} for c in ctx.component_specs],
        "api_integrations": [{"api": b.id, "method": b.method, "path": b.path, "function": b.function, "hook": b.hook} for b in ctx.bindings],
        "tests": [t.model_dump() for t in ctx.tests],
        "build_result": {k: ctx.results.get(k, "not_run") for k in ("typescript", "lint", "build", "unit_tests")},
        "browser_test_result": {k: ctx.results.get(k, "not_run") for k in ("e2e_tests", "accessibility_tests", "total", "passed", "failed")},
        "visual_test_result": {"status": ctx.results.get("visual_tests", "not_run"), "screenshots": ctx.results.get("screenshots", 0), "issues": ctx.results.get("visual_issues", [])},
        "correction_attempts": dict(ctx.attempts),
        "files_generated": len(ctx.files),
        "llm_calls": ctx.runner.calls,
        "warnings": ctx.warnings,
        "errors": ctx.errors + ([error] if error else []),
    }
    ctx.artifacts.save("frontend_report.json", report)
    return report
