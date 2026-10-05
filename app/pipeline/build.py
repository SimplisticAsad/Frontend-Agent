"""Static validation + build + unit tests, with bounded automatic correction (spec 32-33)."""
from __future__ import annotations

import hashlib

from app.domain.models.errors import AgentError, ErrorKind
from app.domain.models.state import PipelineState
from app.execution.command_runner import Cmd
from app.pipeline.context import RunContext
from app.pipeline.failures import STEP_CMD, Failure, failure_from_command
from app.pipeline.loop import LoopOutcome, correction_loop
from app.validation.frontend_validation import verify_structure

STEPS = ["typescript", "lint", "build", "unit_tests"]
QUICK_STEPS = ["typescript", "lint"]
RESULT_KEY = {"typescript": "typescript", "lint": "lint", "build": "build", "unit_tests": "unit_tests"}


def install_dependencies(ctx: RunContext) -> None:
    pkg = ctx.workspace.root / "package.json"
    marker = ctx.workspace.root / "node_modules" / ".agent-install-hash"
    digest = hashlib.sha256(pkg.read_bytes()).hexdigest()
    if ctx.skip_install or (marker.exists() and marker.read_text() == digest):
        ctx.events.emit("install_skipped")
        return
    res = ctx.commands.run(Cmd.INSTALL, ctx.workspace.root)
    ctx.events.emit("install", exit_code=res.exit_code, duration_s=round(res.duration_s, 1))
    if not res.ok:
        raise AgentError(ErrorKind.BUILD_ERROR, f"npm install failed: {res.output[-600:]}")
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(digest)


def structure_failure(ctx: RunContext) -> Failure | None:
    issues = verify_structure(ctx.g, ctx.workspace, ctx.screen_specs, ctx.component_specs, [t.path for t in ctx.tests])
    if not issues:
        return None
    paths = []
    for i in issues:
        for r in i.refs:
            for p, rec in ctx.files.items():
                if r in rec.source_refs and p not in paths and not p.startswith("tests/"):
                    paths.append(p)
    return Failure(ErrorKind.GRAPH_IMPLEMENTATION_CONFLICT, "structure", f"{len(issues)} graph requirement(s) are not implemented in the code", "\n".join(i.message for i in issues),
                   paths[:8], issues=[i.to_dict() for i in issues], refs=sorted({r for i in issues for r in i.refs}))


def run_checks(ctx: RunContext, steps: list[str] | None = None) -> Failure | None:
    """Run structure check then each npm step in order; stop at the first failure. Updates ctx.results."""
    steps = steps or STEPS
    sf = structure_failure(ctx)
    if sf:
        return sf
    for step in steps:
        res = ctx.commands.run(STEP_CMD[step], ctx.workspace.root)
        ctx.events.emit("command", step=step, exit_code=res.exit_code, duration_s=round(res.duration_s, 1))
        if not res.ok:
            ctx.results[RESULT_KEY[step]] = "failed"
            for later in steps[steps.index(step) + 1 :]:
                ctx.results.setdefault(RESULT_KEY[later], "not_run")
            return failure_from_command(step, res)
        ctx.results[RESULT_KEY[step]] = "passed"
    return None


def run(ctx: RunContext) -> LoopOutcome:
    install_dependencies(ctx)
    ctx.status.advance(PipelineState.STATIC_VALIDATION)

    def detect() -> Failure | None:
        f = run_checks(ctx)
        if f is None:
            ctx.dirty = False
        return f

    outcome = correction_loop(ctx, "build", ctx.limits.max_build_correction_attempts, detect)
    if outcome.passed:
        ctx.status.advance(PipelineState.BUILT)
    return outcome
