"""Symbol catalog handed to code-generation prompts so generated code imports real, existing symbols."""
from __future__ import annotations

from app.domain.models.graph import GraphPackage
from app.domain.models.naming import slug
from app.generation.symbols import (
    ApiBinding, api_signature, entity_name, hook_signature, mutation_var_type, workflow_schema_file, workflow_schema_names,
)

HELPERS = {
    "usePermissions": "src/hooks/usePermissions.ts -> { can(permission: PermissionId, resource?: object): boolean; user: AuthUser | null }",
    "useAuth": "src/features/auth/AuthContext.tsx -> { user, signIn(session), signOut() }",
    "useNotify": "src/components/Notifications.tsx -> (message: string, variant?: 'success' | 'info' | 'danger') => void",
    "routeTo": "src/app/routes.ts -> routeTo(screen: ScreenId, params?: Record<string,string>): string",
    "allowedTransitions": "src/lib/stateMachines.ts -> allowedTransitions(machineId, from, isPermitted: (p: PermissionId) => boolean): string[]",
    "stateLabel": "src/lib/stateMachines.ts -> stateLabel(state: string): string",
    "errorMessage": "src/lib/api/client.ts -> errorMessage(error: unknown): string; ApiError has .kind, .status, .fieldErrors",
    "buildLookup/toOptions": "src/lib/lookups.ts -> buildLookup(items, label) / toOptions(items, label); types Lookups, Lookup",
    "formatDate": "src/lib/format.ts -> formatDate(value?: string | null): string",
    "cn": "src/lib/cn.ts",
}


def build_catalog(g: GraphPackage, bindings: list[ApiBinding], design_system: dict | None) -> dict:
    return {
        "api_functions": [{"api_ref": b.id, "module": f"src/lib/api/{b.resource}.ts", "signature": api_signature(b)} for b in bindings],
        "hooks": [
            {"api_ref": b.id, "module": f"src/hooks/queries/{b.resource}.ts", "signature": hook_signature(b), "keys": b.keys_name,
             **({"mutate_variable": mutation_var_type(b)} if b.operation not in ("list", "get") else {})}
            for b in bindings
        ],
        "types": [{"entity": e["id"], "interface": entity_name(e["id"]), "module": f"src/types/{slug(e['id'])}.ts", "fields": [f["name"] for f in e["fields"]]} for e in g.entities],
        "form_schemas": [
            {"workflow": w["id"], "schema": workflow_schema_names(w)[0], "values": workflow_schema_names(w)[1], "defaults": workflow_schema_names(w)[2],
             "module": workflow_schema_file(w), "fields": w["form_fields"]}
            for w in g.workflows if w.get("form_fields")
        ],
        "helpers": HELPERS,
        "ui_primitives": {
            "module": "src/components/ui (index.ts)",
            "exports": ["Button(variant,size,loading)", "Input/Textarea/Select(label,error,hint,required,options)", "Card(title,actions)", "Table/THead/TBody/Tr/Th/Td(label)",
                        "Modal(open,title,onClose,footer)", "Badge(variant)", "Alert(variant,title)", "Pagination(page,pageCount,onPageChange)", "Tabs", "Dropdown",
                        "LoadingState", "EmptyState(title,description,action)", "ErrorState(message,onRetry)", "Spinner"],
        },
        "permissions": [p["id"] for p in g.permissions],
    }
