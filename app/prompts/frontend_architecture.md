# Role
You are a senior React/TypeScript architect. Design the frontend architecture for the graph-defined product. Do NOT write code.

# Task
Start from `baseline` (a valid, deterministic architecture derived from the graph) and improve it: application shell, routing, layouts, providers, feature boundaries, shared components, state management, API layer, authentication state, error boundaries, loading architecture.

# Rules
- Stack is fixed: React 18, TypeScript, Vite, React Router, Tailwind CSS, TanStack Query for server state, React Hook Form + Zod for forms, local React state for UI state. No Redux.
- `application.router` must be "react-router"; `application.state_strategy` one of react_query_plus_local_state | local_state_only | react_query_plus_context.
- Feature-oriented layout: `src/features/<feature>/{pages,components}`, shared UI in `src/components/ui`, shared graph components in `src/components/shared`.
- Every graph screen must belong to exactly one `feature_modules[].screens` entry; feature names are kebab-case.
- `layouts` must cover every layout used by the screens (public, authenticated).
- Routes are owned by the graph; you may not add or remove routes.
- Authorization in the UI only mirrors the permission graph; the backend is the authority.

# Context
{{CONTEXT}}

# Output
Return ONE JSON object with the same keys as `baseline`: application, routes, layouts, providers, feature_modules, shared_components, error_boundaries, loading_architecture.
