"""Stage 6 - API integration plan. api.json is authoritative: method/path/function names cannot change."""
from __future__ import annotations

from app.pipeline.context import RunContext

ERROR_STATUSES = [400, 401, 403, 404, 409, 422, 429, 500]


def build_baseline(ctx: RunContext) -> dict:
    apis = []
    for b in ctx.bindings:
        apis.append({
            "api_ref": b.id, "method": b.method, "path": b.path, "operation": b.operation, "function": b.function,
            "hook": b.hook, "module": f"src/lib/api/{b.resource}.ts", "requires_auth": bool(b.api.get("auth", True)),
            "permission": b.api.get("permission"), "declared_errors": b.api.get("errors", []),
        })
    return {
        "apis": apis,
        "error_handling": {
            "400": "validation: show form-level message and field errors when present", "401": "clear session, redirect to sign in",
            "403": "show permission message, keep the user on the page", "404": "not-found state with a way back",
            "409": "conflict message asking the user to refresh", "422": "map field errors onto form fields",
            "429": "ask the user to wait and retry", "500": "recoverable error state with Retry",
            "network": "offline/unreachable message with Retry", "timeout": "timeout message with Retry", "unknown": "generic message, no technical detail",
        },
    }


def _validator(baseline: dict):
    by_ref = {a["api_ref"]: a for a in baseline["apis"]}

    def validate(out: object) -> list[str]:
        if not isinstance(out, dict) or not isinstance(out.get("apis"), list):
            return ["output must be {\"apis\": [...], \"error_handling\": {...}}"]
        p: list[str] = []
        seen = set()
        for a in out["apis"]:
            ref = a.get("api_ref") if isinstance(a, dict) else None
            if ref not in by_ref:
                p.append(f"unknown api_ref {ref!r} (the frontend must not invent endpoints)")
                continue
            seen.add(ref)
            for k in ("method", "path", "function", "hook"):
                if k in a and a[k] != by_ref[ref][k]:
                    p.append(f"{ref}: '{k}' is fixed by api.json and must be {by_ref[ref][k]!r}")
        if seen != set(by_ref):
            p.append(f"every API must be planned; missing {sorted(set(by_ref) - seen)}")
        eh = out.get("error_handling")
        if not isinstance(eh, dict) or not {"network", "timeout", "401", "403", "404", "409", "422", "429", "500"} <= set(map(str, eh)):
            p.append("error_handling must cover 401,403,404,409,422,429,500,network,timeout")
        return p

    return validate


def run(ctx: RunContext) -> dict:
    baseline = build_baseline(ctx)
    context = {**ctx.contexts.base(), "baseline": baseline, "apis": [b.api for b in ctx.bindings]}
    out = ctx.runner.call("api_integration", context, _validator(baseline))
    merged = []
    llm_by_ref = {a["api_ref"]: a for a in out["apis"]}
    for a in baseline["apis"]:
        extra = llm_by_ref[a["api_ref"]]
        merged.append({**a, "notes": str(extra.get("notes", ""))[:500]})
    plan = {"apis": merged, "error_handling": {**baseline["error_handling"], **{str(k): v for k, v in out["error_handling"].items()}}}
    ctx.api_plan = plan
    ctx.artifacts.save("api_integration.json", plan)
    return plan
