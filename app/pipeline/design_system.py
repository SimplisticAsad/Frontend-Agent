"""Stage 3 - Design System tokens + rules (validated, incl. WCAG contrast)."""
from __future__ import annotations

from app.generation.design_defaults import default_design_system, validate_design_system
from app.pipeline.context import RunContext


def run(ctx: RunContext) -> dict:
    baseline = default_design_system()
    context = {**ctx.contexts.base(), "baseline": baseline, "required_sections": ["typography", "spacing", "colors", "borders", "radius", "shadows", "components", "responsive", "breakpoints"]}

    def validate(out: object) -> list[str]:
        return ["output must be a JSON object"] if not isinstance(out, dict) else validate_design_system(out)

    ds = ctx.runner.call("design_system", context, validate)
    ds.setdefault("primitives", baseline["primitives"])
    ctx.design_system = ds
    ctx.contexts.design_system = ds
    ctx.artifacts.save("design_system.json", ds)
    return ds
