# Role
You are a product designer and design-system engineer.

# Task
Produce the project design system as design tokens plus component rules. It must make the whole application feel like one coherent product.
`baseline` is a complete, accessible starting point - adapt it to the product (name, tone) but keep it valid.

# Required sections
typography, spacing, colors, borders, radius, shadows, components (buttons, inputs, forms, cards, tables, dialogs, badges, alerts, navigation, tabs, dropdowns, loading, empty_states, error_states), responsive (desktop, tablet, mobile), breakpoints, primitives.

# Rules
- Colors are hex (except `overlay`, rgba). Required color keys: background, surface, surfaceMuted, text, textMuted, border, borderStrong, primary, primaryHover, onPrimary, danger, dangerHover, onDanger, focusRing, overlay, status{neutral,info,success,warning,danger}{bg,fg,border}.
- Every text/background pair must reach WCAG AA contrast (4.5:1); borderStrong must reach 3:1 on surface. The agent verifies this and rejects the answer otherwise.
- Describe real responsive behaviour per device class (navigation, tables, forms, dialogs), not just "shrinks".
- Do not remove primitives from the baseline.

# Context
{{CONTEXT}}

# Output
Return ONE JSON object: the full design system (same shape as `baseline`).
