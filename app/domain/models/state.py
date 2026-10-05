"""Explicit pipeline state machine (spec 66/67). Transitions are enforced, not suggested."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable
from enum import Enum


class PipelineState(str, Enum):
    CREATED = "CREATED"
    LOADING_GRAPHS = "LOADING_GRAPHS"
    GRAPHS_VALIDATED = "GRAPHS_VALIDATED"
    ANALYZED = "ANALYZED"
    ARCHITECTED = "ARCHITECTED"
    DESIGN_GENERATED = "DESIGN_GENERATED"
    PLANNED = "PLANNED"
    GENERATED = "GENERATED"
    STATIC_VALIDATION = "STATIC_VALIDATION"
    BUILT = "BUILT"
    BROWSER_TESTED = "BROWSER_TESTED"
    VISUALLY_TESTED = "VISUALLY_TESTED"
    CORRECTING = "CORRECTING"
    FINAL_VALIDATION = "FINAL_VALIDATION"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


S = PipelineState
# Forward path; CORRECTING is entered from and returns to the validation states; FAILED from anywhere.
ALLOWED: dict[PipelineState, set[PipelineState]] = {
    S.CREATED: {S.LOADING_GRAPHS},
    S.LOADING_GRAPHS: {S.GRAPHS_VALIDATED},
    S.GRAPHS_VALIDATED: {S.ANALYZED},
    S.ANALYZED: {S.ARCHITECTED},
    S.ARCHITECTED: {S.DESIGN_GENERATED},
    S.DESIGN_GENERATED: {S.PLANNED},
    S.PLANNED: {S.GENERATED},
    S.GENERATED: {S.STATIC_VALIDATION},
    S.STATIC_VALIDATION: {S.BUILT, S.CORRECTING},
    S.BUILT: {S.BROWSER_TESTED, S.CORRECTING},
    S.BROWSER_TESTED: {S.VISUALLY_TESTED, S.CORRECTING},
    S.VISUALLY_TESTED: {S.FINAL_VALIDATION, S.CORRECTING},
    S.CORRECTING: {S.STATIC_VALIDATION, S.BUILT, S.BROWSER_TESTED, S.VISUALLY_TESTED},
    S.FINAL_VALIDATION: {S.COMPLETED},
    S.COMPLETED: set(),
    S.FAILED: set(),
}


class InvalidTransition(RuntimeError):
    pass


@dataclass
class StageRecord:
    state: str
    status: str  # ok | failed
    detail: str = ""


@dataclass
class PipelineStatus:
    state: PipelineState = PipelineState.CREATED
    history: list[StageRecord] = field(default_factory=list)
    failure: dict | None = None
    listener: Callable[["PipelineStatus"], None] | None = field(default=None, repr=False)

    def _notify(self) -> None:
        if self.listener:
            self.listener(self)

    def advance(self, to: PipelineState, detail: str = "") -> None:
        if to is PipelineState.FAILED:
            self.history.append(StageRecord(to.value, "failed", detail))
            self.state = to
            self._notify()
            return
        if to not in ALLOWED[self.state]:
            raise InvalidTransition(f"{self.state.value} -> {to.value} is not allowed")
        self.state = to
        self.history.append(StageRecord(to.value, "ok", detail))
        self._notify()

    def to_dict(self) -> dict:
        return {
            "state": self.state.value,
            "history": [r.__dict__ for r in self.history],
            "failure": self.failure,
        }
