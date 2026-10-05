"""Failure taxonomy shared by every stage (spec section 41-43)."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ErrorKind(str, Enum):
    GRAPH_ERROR = "GRAPH_ERROR"
    GRAPH_CONFLICT = "GRAPH_CONFLICT"
    GRAPH_IMPLEMENTATION_CONFLICT = "GRAPH_IMPLEMENTATION_CONFLICT"
    TYPE_ERROR = "TYPE_ERROR"
    LINT_ERROR = "LINT_ERROR"
    BUILD_ERROR = "BUILD_ERROR"
    RUNTIME_ERROR = "RUNTIME_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    API_CONTRACT_ERROR = "API_CONTRACT_ERROR"
    FUNCTIONAL_TEST_ERROR = "FUNCTIONAL_TEST_ERROR"
    VISUAL_ERROR = "VISUAL_ERROR"
    ACCESSIBILITY_ERROR = "ACCESSIBILITY_ERROR"
    LLM_ERROR = "LLM_ERROR"
    SAFETY_ERROR = "SAFETY_ERROR"


@dataclass
class Issue:
    kind: ErrorKind
    code: str
    message: str
    refs: list[str] = field(default_factory=list)
    location: str | None = None
    severity: str = "error"  # error | warning

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "code": self.code,
            "message": self.message,
            "refs": self.refs,
            "location": self.location,
            "severity": self.severity,
        }


class AgentError(Exception):
    """Fatal, stage-terminating error carrying structured issues."""

    def __init__(self, kind: ErrorKind, message: str, issues: list[Issue] | None = None):
        super().__init__(message)
        self.kind = kind
        self.issues = issues or []


class GraphError(AgentError):
    def __init__(self, issues: list[Issue]):
        head = "; ".join(i.message for i in issues[:5])
        more = f" (+{len(issues) - 5} more)" if len(issues) > 5 else ""
        super().__init__(ErrorKind.GRAPH_ERROR, f"Invalid graph package: {head}{more}", issues)


class SafetyError(AgentError):
    def __init__(self, message: str):
        super().__init__(ErrorKind.SAFETY_ERROR, message)


class LLMError(AgentError):
    def __init__(self, message: str):
        super().__init__(ErrorKind.LLM_ERROR, message)
