"""Failure model + classification of tool output (spec 41)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.domain.models.errors import ErrorKind
from app.execution.browser_runner import TestOutcome
from app.execution.command_runner import Cmd, CommandResult

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_PATH = re.compile(r"((?:src|tests)/[\w@./\-\[\]]+\.(?:tsx?|css|json))")
MAX_OUTPUT_CHARS = 6000


@dataclass
class Failure:
    kind: ErrorKind
    step: str  # structure | typescript | lint | build | unit_tests | e2e | visual
    summary: str
    details: str = ""
    files: list[str] = field(default_factory=list)  # paths mentioned by the tool output (src/... or tests/...)
    tests: list[dict] = field(default_factory=list)  # failing browser tests (title/file/error)
    issues: list[dict] = field(default_factory=list)  # structured defects (visual / structure)
    refs: list[str] = field(default_factory=list)  # graph refs implicated

    def to_dict(self) -> dict:
        return {"kind": self.kind.value, "step": self.step, "summary": self.summary, "details": self.details[:MAX_OUTPUT_CHARS], "files": self.files,
                "tests": self.tests, "issues": self.issues, "refs": self.refs}


STEP_KIND = {
    "typescript": ErrorKind.TYPE_ERROR,
    "lint": ErrorKind.LINT_ERROR,
    "build": ErrorKind.BUILD_ERROR,
    "unit_tests": ErrorKind.FUNCTIONAL_TEST_ERROR,
}
STEP_CMD = {"typescript": Cmd.TYPECHECK, "lint": Cmd.LINT, "build": Cmd.BUILD, "unit_tests": Cmd.TEST}


def mentioned_files(text: str, limit: int = 8) -> list[str]:
    seen: list[str] = []
    for m in _PATH.findall(_ANSI.sub("", text)):
        if m not in seen:
            seen.append(m)
    return seen[:limit]


def failure_from_command(step: str, res: CommandResult) -> Failure:
    out = _ANSI.sub("", res.output)
    tail = out[-MAX_OUTPUT_CHARS:]
    summary = next((ln.strip() for ln in out.splitlines() if "error" in ln.lower() or "FAIL" in ln), out.strip().splitlines()[-1] if out.strip() else "command failed")
    if res.timed_out:
        summary = f"{res.cmd.label} timed out"
    return Failure(STEP_KIND[step], step, summary[:300], tail, mentioned_files(_relevant_lines(step, out)))


def _relevant_lines(step: str, out: str) -> str:
    """Only the lines that point at *failing* files (vitest/eslint also list every passing file)."""
    if step == "unit_tests":
        keep = [ln for ln in out.splitlines() if "FAIL" in ln or "❯" in ln or "Error" in ln]
        return "\n".join(keep)
    if step == "typescript":
        return "\n".join(ln for ln in out.splitlines() if "error TS" in ln)
    if step == "lint":
        return "\n".join(ln for ln in out.splitlines() if re.match(r"^\s*(/|[A-Za-z]:)?.*\.(tsx?|css)\s*$", ln) or "error" in ln)
    return out


def classify_browser_failure(t: TestOutcome) -> ErrorKind:
    m = t.error
    if "ACCESSIBILITY_ERROR" in m or t.title.split(" > ")[-1].startswith("[a11y]"):
        return ErrorKind.ACCESSIBILITY_ERROR
    if "API_CONTRACT_ERROR" in m:
        return ErrorKind.API_CONTRACT_ERROR
    if "RUNTIME_ERROR" in m:
        return ErrorKind.RUNTIME_ERROR
    if re.search(r"net::ERR|ECONNREFUSED|ERR_CONNECTION", m):
        return ErrorKind.NETWORK_ERROR
    return ErrorKind.FUNCTIONAL_TEST_ERROR


def failure_from_browser(failures: list[TestOutcome]) -> Failure:
    kinds = [classify_browser_failure(t) for t in failures]
    order = [ErrorKind.RUNTIME_ERROR, ErrorKind.API_CONTRACT_ERROR, ErrorKind.NETWORK_ERROR, ErrorKind.FUNCTIONAL_TEST_ERROR, ErrorKind.ACCESSIBILITY_ERROR]
    kind = next(k for k in order if k in kinds)
    tests = [{"title": t.title, "file": t.file, "kind": k.value, "error": t.error[:1500]} for t, k in zip(failures, kinds)][:12]
    files = []
    for t in failures:
        for p in [f"tests/e2e/{t.file.split('/')[-1]}" if t.file else ""] + mentioned_files(t.error):
            if p and p not in files:
                files.append(p)
    return Failure(kind, "e2e", f"{len(failures)} browser test(s) failed; first: {failures[0].title}", "\n\n".join(f"{t.title}\n{t.error}" for t in failures[:6])[:MAX_OUTPUT_CHARS], files[:10], tests)
