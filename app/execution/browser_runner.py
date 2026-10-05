"""Runs the generated Playwright suites (real Chromium) and parses their JSON report."""
from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from app.execution.command_runner import Cmd, CommandResult, CommandRunner

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


@dataclass
class TestOutcome:
    title: str
    file: str
    status: str  # passed | failed | timedOut | skipped | interrupted
    error: str = ""
    duration_ms: int = 0

    @property
    def failed(self) -> bool:
        return self.status in ("failed", "timedOut", "interrupted")


@dataclass
class BrowserRunResult:
    command: CommandResult | None
    tests: list[TestOutcome] = field(default_factory=list)
    infrastructure_error: str = ""  # Playwright could not run at all (no report produced)

    @property
    def failures(self) -> list[TestOutcome]:
        return [t for t in self.tests if t.failed]

    @property
    def ok(self) -> bool:
        return not self.infrastructure_error and not self.failures and bool(self.tests)

    @property
    def passed(self) -> int:
        return sum(t.status == "passed" for t in self.tests)


def parse_playwright_report(report: dict) -> list[TestOutcome]:
    out: list[TestOutcome] = []

    def walk(suite: dict, file: str, titles: list[str]) -> None:
        file = suite.get("file") or file
        t = titles + ([suite["title"]] if suite.get("title") and not str(suite["title"]).endswith((".ts", ".tsx")) else [])
        for spec in suite.get("specs", []):
            for test in spec.get("tests", []):
                results = test.get("results", [])
                last = results[-1] if results else {}
                status = last.get("status") or test.get("status") or "skipped"
                if status == "skipped" or test.get("status") == "skipped":
                    status = "skipped"
                errs = last.get("errors") or ([last["error"]] if last.get("error") else [])
                msg = "\n".join(_ANSI.sub("", e.get("message", "")) for e in errs if isinstance(e, dict))
                out.append(TestOutcome(" > ".join(t + [spec.get("title", "")]), spec.get("file") or file, status, msg[:4000], int(last.get("duration", 0))))
        for sub in suite.get("suites", []):
            walk(sub, file, t)

    for s in report.get("suites", []):
        walk(s, s.get("file", ""), [])
    return out


class BrowserRunner(ABC):
    @abstractmethod
    def run_e2e(self, cwd: Path) -> BrowserRunResult: ...

    @abstractmethod
    def run_visual(self, cwd: Path, screenshot_dir: Path) -> BrowserRunResult: ...


class PlaywrightBrowserRunner(BrowserRunner):
    def __init__(self, commands: CommandRunner):
        self.commands = commands

    def _run(self, cmd: Cmd, cwd: Path, extra_env: dict[str, str] | None = None) -> BrowserRunResult:
        report = cwd / "test-results" / "results.json"
        if report.exists():
            report.unlink()
        res = self.commands.run(cmd, cwd, {"PW_JSON_OUT": "test-results/results.json", **(extra_env or {})})
        if not report.exists():
            return BrowserRunResult(res, [], infrastructure_error=(res.output[-1500:] or "Playwright produced no report"))
        try:
            tests = parse_playwright_report(json.loads(report.read_text(encoding="utf-8")))
        except (ValueError, KeyError) as e:
            return BrowserRunResult(res, [], infrastructure_error=f"unreadable Playwright report: {e}")
        return BrowserRunResult(res, tests)

    def run_e2e(self, cwd: Path) -> BrowserRunResult:
        return self._run(Cmd.TEST_E2E, cwd)

    def run_visual(self, cwd: Path, screenshot_dir: Path) -> BrowserRunResult:
        return self._run(Cmd.TEST_VISUAL, cwd, {"SCREENSHOT_DIR": str(screenshot_dir)})
