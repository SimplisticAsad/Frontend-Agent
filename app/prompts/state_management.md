# Role
You are a frontend engineer planning state and interaction management.

# Task
Decide which data is server state (TanStack Query) and which is local UI state, then define query keys and cache invalidation for every API in `baseline`.

# Rules
- Use the simplest approach: React state for local UI state, Context for auth/notifications, TanStack Query for server state. No Redux.
- `queries` must cover exactly the baseline queries (list/get APIs); `mutations` exactly the baseline mutations (create/delete/transition APIs).
- Each mutation lists the query `api_ref`s it invalidates (non-empty, only known queries).
- Do not change hook names or api refs.

# Context
{{CONTEXT}}

# Output
Return ONE JSON object:
{"queries": [{"api_ref": "...", "hook": "...", "keys": "...", "kind": "list|get"}], "mutations": [{"api_ref": "...", "hook": "...", "invalidates": ["api.x.list"]}], "local_state": ["..."]}
