"""Visual testing (spec 37-39): real screenshots at three viewports + objective layout metrics + vision-model review.

The vision model is asked for *structured defects* with the screen spec, design system, viewport and expected
behaviour as context - never "does this look good?".  Layout metrics measured in the browser provide a
deterministic floor so a missing/weak vision model can not let a broken layout through.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from app.domain.models.errors import ErrorKind, LLMError
from app.domain.models.state import PipelineState
from app.pipeline.build import QUICK_STEPS, run_checks
from app.pipeline.context import RunContext
from app.pipeline.failures import Failure
from app.pipeline.loop import LoopOutcome, correction_loop

SEVERITIES = ("low", "medium", "high", "critical")
BLOCKING = {"high", "critical"}
ISSUE_TYPES = {"layout", "overflow", "overlap", "clipping", "navigation", "spacing", "alignment", "missing_element", "accessibility", "consistency", "blank_area", "modal", "table", "other"}


@dataclass
class Capture:
    screen: str
    viewport: str
    png: Path
    metrics: dict
    route: str = ""


@dataclass
class VisualIssue:
    severity: str
    type: str
    description: str
    location: str
    recommended_fix: str
    screen: str = ""
    viewport: str = ""
    source: str = "metrics"  # metrics | vision

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @property
    def blocking(self) -> bool:
        return self.severity in BLOCKING


# ------------------------------------------------------------------ parsing / deterministic analysis
def parse_issues(raw: object, screen: str = "", viewport: str = "", source: str = "vision") -> list[VisualIssue]:
    """Parse a vision-model answer. Raises LLMError (for retry) when the structure is wrong."""
    items = raw.get("issues") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise LLMError('visual analysis must be {"issues": [...]}')
    out = []
    for it in items:
        if not isinstance(it, dict):
            raise LLMError("each issue must be an object")
        sev = str(it.get("severity", "")).lower()
        if sev not in SEVERITIES:
            raise LLMError(f"severity must be one of {SEVERITIES}, got {it.get('severity')!r}")
        typ = str(it.get("type", "other")).lower()
        out.append(VisualIssue(sev, typ if typ in ISSUE_TYPES else "other", str(it.get("description", ""))[:400], str(it.get("location", ""))[:200],
                               str(it.get("recommended_fix", ""))[:400], str(it.get("screen", screen)) or screen, str(it.get("viewport", viewport)) or viewport, source))
    return out


def issues_from_metrics(screen: str, viewport: str, m: dict) -> list[VisualIssue]:
    out: list[VisualIssue] = []
    add = lambda sev, typ, desc, loc, fix: out.append(VisualIssue(sev, typ, desc, loc, fix, screen, viewport, "metrics"))
    vw = m.get("viewport", {}).get("width", 0)
    if m.get("horizontalOverflow"):
        els = m.get("overflowingElements") or []
        add("high", "overflow", f"The page scrolls horizontally at {viewport} (content is {m.get('documentWidth')}px wide in a {vw}px viewport).",
            els[0]["selector"] if els else "document", "Constrain the overflowing element (max-w-full, min-w-0, flex-wrap) or make it scroll inside its own container; on small screens stack content.")
    for t in m.get("tables") or []:
        if t.get("overflows") and not m.get("horizontalOverflow"):
            add("high", "table", f"A table is wider than its container at {viewport}.", t["selector"], "Use the responsive Table primitive so rows become stacked cards on small screens.")
    for o in (m.get("overlappingControls") or [])[:3]:
        add("high", "overlap", f"Interactive controls overlap: {o['a']} and {o['b']}.", o["a"], "Give the controls their own space (gap, flex-wrap) instead of absolute positioning.")
    d = m.get("dialog")
    if d and not d.get("insideViewport"):
        add("high", "modal", f"The dialog is positioned partly outside the {viewport} viewport.", "[role=dialog]", "Center the dialog or use a bottom sheet on small screens with max-h and scrolling.")
    if m.get("mainTextLength", 1) == 0:
        add("high", "blank_area", "The main content area is empty.", "main", "Render content or an explicit loading/empty state.")
    for c in (m.get("clippedText") or [])[:3]:
        add("medium", "clipping", f"Text is clipped: '{c['text']}'.", c["selector"], "Allow wrapping (break-words) or show the full text in a tooltip/detail.")
    if viewport == "mobile":
        for s in (m.get("smallTargets") or [])[:3]:
            add("medium", "accessibility", f"Touch target {s['width']}x{s['height']}px is smaller than 24px.", s["selector"], "Increase the hit area to at least 44px on touch screens.")
    if m.get("h1Count", 1) != 1 and screen != "navigation.menu" and not screen.endswith(".dialog"):
        add("medium", "other", f"Expected exactly one h1, found {m.get('h1Count')}.", "document", "Render a single page heading.")
    return out


# ------------------------------------------------------------------ capture
def load_captures(shot_dir: Path) -> list[Capture]:
    caps = []
    for meta in sorted(shot_dir.glob("*.json")):
        png = meta.with_suffix(".png")
        if not png.exists():
            continue
        data = json.loads(meta.read_text(encoding="utf-8"))
        caps.append(Capture(data["screen"], data["viewport"], png, data["metrics"], data.get("route", "")))
    return caps


def capture_all(ctx: RunContext) -> tuple[list[Capture], Failure | None]:
    shot_dir = ctx.artifacts.path("screenshots")
    if shot_dir.exists():
        shutil.rmtree(shot_dir)  # never analyse stale images
    shot_dir.mkdir(parents=True, exist_ok=True)
    res = ctx.browser.run_visual(ctx.workspace.root, shot_dir)
    if res.infrastructure_error:
        return [], Failure(ErrorKind.RUNTIME_ERROR, "visual", "Playwright could not run the visual suite", res.infrastructure_error)
    if res.failures:
        first = res.failures[0]
        return [], Failure(ErrorKind.VISUAL_ERROR, "visual", f"{len(res.failures)} screen(s) did not render for capture; first: {first.title}", "\n\n".join(f"{t.title}\n{t.error}" for t in res.failures[:5])[:5000],
                           [f"tests/visual/{first.file.split('/')[-1]}"] if first.file else [], issues=[{"severity": "high", "type": "blank_area", "description": t.error[:200], "screen": t.title, "location": "page"} for t in res.failures[:5]])
    caps = load_captures(shot_dir)
    ctx.results["screenshots"] = len(caps)
    return caps, None


# ------------------------------------------------------------------ vision
def vision_issues(ctx: RunContext, caps: list[Capture]) -> list[VisualIssue]:
    by_screen: dict[str, list[Capture]] = {}
    for c in caps:
        by_screen.setdefault(c.screen, []).append(c)
    out: list[VisualIssue] = []
    ds = ctx.contexts.design_system or {}
    for screen, group in by_screen.items():
        spec = next((s for s in ctx.screen_specs if s.screen_ref == screen), None)
        context = {
            **ctx.contexts.base(), "screen": screen, "screen_spec": spec.model_dump() if spec else None,
            "design_system": {"colors": ds.get("colors"), "components": ds.get("components"), "responsive": ds.get("responsive")},
            "viewports": [{"name": c.viewport, "width": c.metrics.get("viewport", {}).get("width"), "image": c.png.name, "layout_metrics": c.metrics} for c in group],
            "expected_behavior": spec.responsive if spec else {},
            "checklist": ["overlapping elements", "broken layouts", "overflowing content", "clipped text", "unusable mobile layouts", "inconsistent spacing", "broken navigation",
                          "incorrect alignment", "missing elements", "inaccessible controls", "unexpected blank areas", "modal positioning", "table overflow", "visual inconsistency"],
        }

        def validate(raw: object, _screen=screen) -> list[str]:
            try:
                parse_issues(raw, _screen)
                return []
            except LLMError as e:
                return [str(e)]

        raw = ctx.runner.call("visual_analysis", context, validate, unit=screen, images=[c.png for c in group])
        out += parse_issues(raw, screen, source="vision")
    return out


def analyse(ctx: RunContext, caps: list[Capture]) -> list[VisualIssue]:
    issues: list[VisualIssue] = []
    for c in caps:
        issues += issues_from_metrics(c.screen, c.viewport, c.metrics)
    issues += vision_issues(ctx, caps)
    seen, uniq = set(), []
    for i in issues:
        k = (i.screen, i.viewport, i.type, i.location)
        if k not in seen:
            seen.add(k)
            uniq.append(i)
    return uniq


def failure_from_issues(ctx: RunContext, issues: list[VisualIssue]) -> Failure:
    blocking = [i for i in issues if i.blocking]
    files: list[str] = []
    refs = sorted({i.screen for i in blocking if i.screen})
    for r in refs:
        spec = next((s for s in ctx.screen_specs if s.screen_ref == r), None)
        if spec:
            files += [spec.page_path] + [c.path for c in ctx.component_specs if c.component_ref in spec.components]
    if not refs:  # layout-level issues (e.g. navigation.menu) implicate the shared layout/components
        files += [p for p in ctx.files if p.startswith("src/components/shared/")]
    return Failure(ErrorKind.VISUAL_ERROR, "visual", f"{len(blocking)} blocking visual defect(s) on {len(refs) or 'shared'} screen(s)",
                   "\n".join(f"[{i.severity}] {i.screen}@{i.viewport} {i.type}: {i.description} (fix: {i.recommended_fix})" for i in blocking[:20]),
                   list(dict.fromkeys(files)), issues=[i.to_dict() for i in blocking[:30]], refs=refs)


def detect_once(ctx: RunContext) -> Failure | None:
    f = run_checks(ctx, QUICK_STEPS)
    if f:
        return f
    caps, fail = capture_all(ctx)
    if fail:
        ctx.results["visual_tests"] = "failed"
        return fail
    issues = analyse(ctx, caps)
    ctx.results["visual_issues"] = [i.to_dict() for i in issues]
    ctx.results["visual_tests"] = "failed" if any(i.blocking for i in issues) else "passed"
    ctx.artifacts.save("visual_report.json", {"captures": len(caps), "issues": [i.to_dict() for i in issues]})
    blocking = [i for i in issues if i.blocking]
    return failure_from_issues(ctx, issues) if blocking else None


def run(ctx: RunContext) -> LoopOutcome:
    outcome = correction_loop(ctx, "visual", ctx.limits.max_visual_correction_attempts, lambda: detect_once(ctx))
    if outcome.passed:
        ctx.status.advance(PipelineState.VISUALLY_TESTED)
    return outcome
