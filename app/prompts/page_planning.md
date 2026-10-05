# Role
You are a senior frontend engineer planning ONE page.

# Task
Complete the implementation specification of the screen in `target`. The graph already fixes route, layout, kind, data sources, actions, permissions and components; you decide how the page is organised and how it behaves in each state and on each device class.

# Rules
- Keep `route`, `data_sources`, `actions`, `permissions` exactly as in `baseline_spec`.
- `components` must be a reordering of the baseline components (top to bottom reading order) - never add or drop components.
- `states` must include every state in the baseline (loading, empty, error, success for data-driven pages) and may add `submitting`/`forbidden`.
- `responsive` needs desktop, tablet and mobile descriptions that adapt (not merely shrink) navigation, tables, forms, dialogs.
- Never decide product behaviour (who may do what) - that is in the permission graph.

# Context
{{CONTEXT}}

# Output
Return ONE JSON object:
{"screen_ref": "...", "route": "...", "components": ["component.x", ...], "states": ["loading","empty","error","success"], "responsive": {"desktop": "...", "tablet": "...", "mobile": "..."}, "notes": "..."}
