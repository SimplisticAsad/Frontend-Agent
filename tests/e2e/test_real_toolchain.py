"""Real toolchain: npm install, tsc, eslint, vite build, vitest, Playwright (Chromium) against the generated app.

Slow (minutes) and needs network + a Chromium that Playwright can find, so it is opt-in:  pytest -m e2e
"""
from __future__ import annotations

import json
import shutil

import pytest

from app.config.settings import Settings
from app.llm.mock import MockLLMProvider
from app.pipeline.orchestrator import FrontendAgent
from tests.conftest import TASK_MANAGER

pytestmark = pytest.mark.e2e


@pytest.mark.parametrize(
    "faults,expected",
    [
        (set(), {"build": 0, "functional": 0, "visual": 0}),
        ({"build"}, {"build": 1, "functional": 0, "visual": 0}),  # type error injected into a component, fixed by the correction stage
        ({"functional"}, {"build": 0, "functional": 1, "visual": 0}),  # create page forgets its success notification -> caught by the browser tests
        ({"visual"}, {"build": 0, "functional": 0, "visual": 1}),  # fixed-width table overflows every viewport -> caught by screenshots/metrics
    ],
    ids=["clean", "build-fault", "functional-fault", "visual-fault"],
)
def test_generated_app_builds_runs_in_a_browser_and_self_corrects(tmp_path, faults, expected):
    project = tmp_path / "task_manager"
    shutil.copytree(TASK_MANAGER / "graphs", project / "graphs")
    agent = FrontendAgent(project, MockLLMProvider(faults=faults), settings=Settings())
    report = agent.generate()
    assert report["status"] == "passed", json.dumps(report["errors"], indent=2)[:3000]
    assert report["correction_attempts"] == expected
    val = json.loads((project / "frontend-artifacts" / "frontend_validation_report.json").read_text())
    assert {k: val[k] for k in ("typescript", "lint", "build", "unit_tests", "e2e_tests", "visual_tests", "accessibility_tests")} == {
        k: "passed" for k in ("typescript", "lint", "build", "unit_tests", "e2e_tests", "visual_tests", "accessibility_tests")
    }
    assert val["screenshots"] >= 24 and (project / "frontend-artifacts" / "screenshots" / "screen.dashboard__mobile.png").exists()
    assert report["browser_test_result"]["total"] >= 70
