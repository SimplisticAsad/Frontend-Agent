"""The one place a retry loop lives. Every correction loop is bounded by an explicit limit (spec 32/39/59)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from app.domain.models.errors import AgentError, ErrorKind
from app.domain.models.state import PipelineState
from app.pipeline.context import RunContext
from app.pipeline.correction import CorrectionResult, CorrectionService
from app.pipeline.failures import Failure


@dataclass
class LoopOutcome:
    passed: bool
    attempts: int
    last_failure: Failure | None = None
    reason: str = ""
    history: list[dict] = field(default_factory=list)


def correction_loop(
    ctx: RunContext,
    bucket: str,  # "build" | "functional" | "visual" -> ctx.attempts key
    limit: int,
    detect: Callable[[], Failure | None],
    correct: Callable[[Failure], CorrectionResult] | None = None,
) -> LoopOutcome:
    """detect -> (failure? correct -> detect)*, at most `limit` corrections.

    Returns passed=False when the limit is reached, when a correction changes nothing (re-running would be
    pointless), or when the model reports a graph conflict (raised as AgentError).
    """
    service = CorrectionService(ctx)
    correct = correct or service.correct
    resume_state = ctx.status.state
    outcome = LoopOutcome(False, 0)
    while True:
        failure = detect()
        if failure is None:
            outcome.passed = True
            return outcome
        outcome.last_failure = failure
        ctx.events.emit("failure", bucket=bucket, kind=failure.kind.value, step=failure.step, summary=failure.summary, attempt=outcome.attempts)
        if outcome.attempts >= limit:
            outcome.reason = f"correction limit reached ({limit}) with {failure.kind.value} remaining"
            return outcome
        outcome.attempts += 1
        ctx.attempts[bucket] = outcome.attempts
        ctx.status.advance(PipelineState.CORRECTING, f"{bucket} attempt {outcome.attempts}: {failure.kind.value}")
        result = correct(failure)
        ctx.status.advance(resume_state, f"{bucket} correction {outcome.attempts} {'applied' if result.changed else 'made no change'}")
        outcome.history.append({"attempt": outcome.attempts, "kind": failure.kind.value, "step": failure.step, "decision": result.decision,
                                "applied": result.applied, "rejected": result.rejected, "explanation": result.explanation[:300]})
        ctx.events.emit("correction", bucket=bucket, attempt=outcome.attempts, decision=result.decision, applied=result.applied, rejected=result.rejected[:3])
        if result.decision == "graph_conflict":
            raise AgentError(ErrorKind.GRAPH_CONFLICT, f"The correction stage reports a conflict in the graph specification, not in the frontend: {result.graph_conflict}")
        if not result.changed:
            outcome.reason = "correction produced no applicable change: " + ("; ".join(result.rejected) or "nothing to change")
            return outcome
