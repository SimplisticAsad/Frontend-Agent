"""Stage 7 - State / interaction plan: query keys, cache invalidation, local vs server state."""
from __future__ import annotations

from app.pipeline.context import RunContext


def build_baseline(ctx: RunContext) -> dict:
    queries, mutations = [], []
    for b in ctx.bindings:
        if b.operation in ("list", "get"):
            queries.append({"api_ref": b.id, "hook": b.hook, "keys": b.keys_name, "kind": b.operation})
    for b in ctx.bindings:
        if b.operation in ("create", "delete", "transition"):
            inv = [q["api_ref"] for q in queries if ctx.bindings and any(x.id == q["api_ref"] and x.entity_ref == b.request_entity_ref for x in ctx.bindings)]
            mutations.append({"api_ref": b.id, "hook": b.hook, "invalidates": inv})
    return {
        "server_state": "TanStack Query; one key factory per resource (all/list/detail); stale time 15s",
        "queries": queries, "mutations": mutations,
        "local_state": ["form values (react-hook-form)", "modal open/close", "pagination page", "mobile menu open"],
        "auth_state": "AuthProvider context; session persisted in localStorage; cleared on 401",
    }


def _validator(baseline: dict):
    q_refs = {q["api_ref"] for q in baseline["queries"]}
    m_refs = {m["api_ref"] for m in baseline["mutations"]}

    def validate(out: object) -> list[str]:
        if not isinstance(out, dict):
            return ["output must be a JSON object"]
        p: list[str] = []
        if {m.get("api_ref") for m in out.get("mutations", []) if isinstance(m, dict)} != m_refs:
            p.append(f"mutations must cover exactly {sorted(m_refs)}")
        for m in out.get("mutations", []):
            if isinstance(m, dict):
                bad = set(m.get("invalidates", [])) - q_refs
                if bad:
                    p.append(f"{m.get('api_ref')}: invalidates unknown queries {sorted(bad)}")
                if not m.get("invalidates"):
                    p.append(f"{m.get('api_ref')}: a mutation must invalidate at least one query")
        if {q.get("api_ref") for q in out.get("queries", []) if isinstance(q, dict)} != q_refs:
            p.append(f"queries must cover exactly {sorted(q_refs)}")
        return p

    return validate


def run(ctx: RunContext) -> dict:
    baseline = build_baseline(ctx)
    context = {**ctx.contexts.base(), "baseline": baseline, "api_plan": ctx.api_plan}
    out = ctx.runner.call("state_management", context, _validator(baseline))
    plan = {**baseline, "mutations": out["mutations"], "queries": out["queries"], "local_state": out.get("local_state", baseline["local_state"])}
    ctx.state_plan = plan
    ctx.artifacts.save("state_plan.json", plan)
    return plan
