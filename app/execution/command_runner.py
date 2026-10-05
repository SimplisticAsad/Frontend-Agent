"""The only way the agent runs processes: a closed set of predefined npm commands.

LLM output can never reach this module as a command string - callers pass a `Cmd` member.
"""
from __future__ import annotations

import os
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from app.domain.models.errors import SafetyError


class Cmd(Enum):
    INSTALL = ("npm", "install", "--no-audit", "--no-fund")
    BUILD = ("npm", "run", "build")
    TYPECHECK = ("npm", "run", "typecheck")
    LINT = ("npm", "run", "lint")
    TEST = ("npm", "run", "test")
    TEST_E2E = ("npm", "run", "test:e2e")
    TEST_VISUAL = ("npm", "run", "test:visual")
    DEV = ("npm", "run", "dev")

    @property
    def argv(self) -> list[str]:
        return list(self.value)

    @property
    def label(self) -> str:
        return " ".join(self.value[:3] if self.value[1] == "run" else self.value[:2])


@dataclass
class CommandResult:
    cmd: Cmd
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration_s: float = 0.0
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    @property
    def output(self) -> str:
        return (self.stdout + ("\n" + self.stderr if self.stderr else "")).strip()


class CommandRunner(ABC):
    @abstractmethod
    def run(self, cmd: Cmd, cwd: Path, env: dict[str, str] | None = None) -> CommandResult: ...


_ALLOWED_ENV = {"PW_JSON_OUT", "CI", "PLAYWRIGHT_BROWSERS_PATH", "PW_CHROMIUM_PATH", "SCREENSHOT_DIR"}


class SubprocessCommandRunner(CommandRunner):
    def __init__(self, timeout_s: int = 900, max_output_chars: int = 200_000):
        self.timeout_s = timeout_s
        self.max_output = max_output_chars

    def run(self, cmd: Cmd, cwd: Path, env: dict[str, str] | None = None) -> CommandResult:
        if not isinstance(cmd, Cmd):
            raise SafetyError("Only predefined Cmd members may be executed")
        if cmd is Cmd.DEV:
            raise SafetyError("The dev server is started by Playwright's webServer, not by the agent")
        extra = {k: v for k, v in (env or {}).items() if k in _ALLOWED_ENV}
        full_env = {**os.environ, **extra}
        t0 = time.monotonic()
        try:
            p = subprocess.run(cmd.argv, cwd=cwd, env=full_env, capture_output=True, text=True, timeout=self.timeout_s)
            return CommandResult(cmd, p.returncode, p.stdout[-self.max_output :], p.stderr[-self.max_output :], time.monotonic() - t0)
        except subprocess.TimeoutExpired as e:
            out = (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
            return CommandResult(cmd, 124, out[-self.max_output :], "timed out", time.monotonic() - t0, True)
        except FileNotFoundError as e:
            return CommandResult(cmd, 127, "", f"command not found: {e.filename}", time.monotonic() - t0)
