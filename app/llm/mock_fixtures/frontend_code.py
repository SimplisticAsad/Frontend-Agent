"""Deterministic React/TypeScript fixtures for the MockLLMProvider.

Everything is derived from the graph + the planning specs passed in the request, so any graph that uses the
supported screen/component/workflow kinds produces a coherent app.  Real providers write this code themselves.
"""
from __future__ import annotations

from app.domain.models.graph import GraphPackage
from app.domain.models.naming import label_of, plural, slug, tail, workflow_testid, form_testid, row_testid
from app.generation.symbols import (
    ApiBinding, build_api_bindings, component_path, entity_name, entity_plural, enum_type_name, field_label, machine_for_entity, mutation_var_type, workflow_schema_file, workflow_schema_names, state_label,
)
from app.llm.mock_fixtures.tsgen import Imports, lower_first, q

EMPTY = "EMPTY_ERRORS"


class FrontendFixtures:
    def __init__(self, g: GraphPackage):
        self.g = g
        self.bindings = build_api_bindings(g)

    # ------------------------------------------------------------------ lookups
    def binding(self, api_ref: str) -> ApiBinding:
        return next(b for b in self.bindings if b.id == api_ref)

    def type_file(self, entity_ref: str) -> str:
        return f"src/types/{slug(entity_ref)}.ts"

    def hooks_file(self, b: ApiBinding) -> str:
        return f"src/hooks/queries/{b.resource}.ts"

    def display_field(self, entity_ref: str) -> str:
        e = self.g.require(entity_ref)
        return e.get("display_field") or next((f["name"] for f in e["fields"] if f["type"] in ("string",) and f["name"] != "id"), "id")

    def is_required(self, entity_ref: str, name: str) -> bool:
        f = self.g.entity_field(entity_ref, name) or {}
        return bool(f.get("required") or any(v["rules"].get("required") for v in self.g.validations_for(entity_ref, name)))

    def badge_component(self, entity_ref: str) -> dict | None:
        return next((c for c in self.g.nodes("components") if c["kind"] == "status_badge" and c.get("entity") == entity_ref), None)

    def list_fields(self, entity_ref: str) -> list[dict]:
        e = self.g.require(entity_ref)
        names = e.get("list_fields") or [f["name"] for f in e["fields"] if f["name"] not in ("id",)][:5]
        return [self.g.entity_field(entity_ref, n) for n in names if self.g.entity_field(entity_ref, n)]

    # ------------------------------------------------------------------ hooks
    def hooks(self, resource: str) -> str:
        bs = [b for b in self.bindings if b.resource == resource]
        path = f"src/hooks/queries/{resource}.ts"
        imp = Imports(path)
        imp.add("src/lib/api/client.ts", "ApiError", type=True)
        react_q = set()
        ent_ref = next((b.entity_ref or b.request_entity_ref for b in bs if b.entity_ref or b.request_entity_ref), None)
        keys = bs[0].keys_name
        body: list[str] = []
        if resource != "auth" and ent_ref:
            body.append(
                f"export const {keys} = {{\n  all: [{q(resource)}] as const,\n  list: (params?: object) => [{q(resource)}, 'list', params ?? {{}}] as const,\n"
                f"  detail: (id: string) => [{q(resource)}, 'detail', id] as const,\n}};\n"
            )
        for b in bs:
            imp.add(f"src/lib/api/{resource}.ts", b.function)
            if b.shape == "session":
                imp.add("src/types/api.ts", "Session", type=True)
            elif b.entity_ref:
                imp.add(self.type_file(b.entity_ref), b.entity, type=True)
            if b.input_type:
                imp.add(self.type_file(b.request_entity_ref), b.input_type, type=True)
            if b.params_type:
                imp.add(self.type_file(b.request_entity_ref), b.params_type, type=True)
            if b.operation == "list":
                react_q.add("useQuery")
                if b.params_type:
                    body.append(
                        f"export function {b.hook}(params?: {b.params_type}) {{\n  return useQuery<{b.returns_ts}, ApiError>({{\n"
                        f"    queryKey: {keys}.list(params),\n    queryFn: ({{ signal }}) => {b.function}(params, signal),\n  }});\n}}\n"
                    )
                else:
                    body.append(
                        f"export function {b.hook}() {{\n  return useQuery<{b.returns_ts}, ApiError>({{\n"
                        f"    queryKey: {keys}.list(),\n    queryFn: ({{ signal }}) => {b.function}(signal),\n  }});\n}}\n"
                    )
            elif b.operation == "get":
                react_q.add("useQuery")
                body.append(
                    f"export function {b.hook}(id: string | undefined) {{\n  return useQuery<{b.returns_ts}, ApiError>({{\n"
                    f"    queryKey: {keys}.detail(id ?? ''),\n    queryFn: ({{ signal }}) => {b.function}(id as string, signal),\n    enabled: Boolean(id),\n  }});\n}}\n"
                )
            else:
                react_q.add("useMutation")
                var_t = mutation_var_type(b)
                if b.path_params and b.input_type:
                    fn = f"({{ {', '.join(b.path_params)}, input }}) => {b.function}({', '.join(b.path_params)}, input)"
                elif b.path_params and len(b.path_params) == 1:
                    fn = f"({b.path_params[0]}) => {b.function}({b.path_params[0]})"
                elif b.input_type:
                    fn = f"(input) => {b.function}(input)"
                else:
                    fn = f"() => {b.function}()"
                if b.operation == "login":
                    body.append(f"export function {b.hook}() {{\n  return useMutation<{b.returns_ts}, ApiError, {var_t}>({{ mutationFn: {fn} }});\n}}\n")
                else:
                    react_q.add("useQueryClient")
                    body.append(
                        f"export function {b.hook}() {{\n  const queryClient = useQueryClient();\n  return useMutation<{b.returns_ts}, ApiError, {var_t}>({{\n"
                        f"    mutationFn: {fn},\n    onSuccess: () => queryClient.invalidateQueries({{ queryKey: {keys}.all }}),\n  }});\n}}\n"
                    )
        imp.add("@tanstack/react-query", *sorted(react_q))
        return imp.render() + "\n\n" + "\n".join(body)

    # ------------------------------------------------------------------ components
    def component(self, spec: dict) -> str:
        comp = self.g.require(spec["component_ref"])
        return getattr(self, f"_c_{comp['kind']}")(comp, spec["path"])

    def _c_page_header(self, comp: dict, path: str) -> str:
        return """import type { ReactNode } from 'react';

export interface PageHeaderProps {
  title: string;
  description?: string;
  actions?: ReactNode;
}

export function PageHeader({ title, description, actions }: PageHeaderProps) {
  return (
    <header className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0">
        <h1 className="break-words text-2xl font-semibold text-text">{title}</h1>
        {description && <p className="mt-1 text-sm text-textMuted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </header>
  );
}
""".replace("PageHeader", comp["name"])

    def _c_status_badge(self, comp: dict, path: str) -> str:
        sm = self.g.require(comp["state_machine"])
        name, ent = comp["name"], sm["entity"]
        ty = enum_type_name(ent, sm["field"])
        states = sm["states"]
        variants = {s: ("neutral" if i == 0 else "success" if i == len(states) - 1 else "info") for i, s in enumerate(states)}
        vmap = ", ".join(f"{s}: '{v}'" for s, v in variants.items())
        imp = Imports(path)
        imp.add("src/components/ui/Badge.tsx", "Badge", "StatusVariant", type=False)
        imp.add("src/lib/stateMachines.ts", "stateLabel")
        imp.add(self.type_file(ent), ty, type=True)
        return f"""{imp.render()}

const VARIANTS: Record<{ty}, StatusVariant> = {{ {vmap} }};

export interface {name}Props {{
  status: {ty};
}}

export function {name}({{ status }}: {name}Props) {{
  return <Badge variant={{VARIANTS[status] ?? 'neutral'}}>{{stateLabel(status)}}</Badge>;
}}
"""

    def _c_status_control(self, comp: dict, path: str) -> str:
        sm = self.g.require(comp["state_machine"])
        name, ent = comp["name"], sm["entity"]
        ty, E, e = enum_type_name(ent, sm["field"]), entity_name(ent), lower_first(entity_name(ent))
        wf = self.g.require(comp["workflow"])
        tid = workflow_testid(wf["id"])
        imp = Imports(path)
        imp.add("react", "useState")
        for n, m in (("Alert", "Alert"), ("Button", "Button"), ("Select", "Field")):
            imp.add(f"src/components/ui/{m}.tsx", n)
        imp.add("src/lib/stateMachines.ts", "stateLabel")
        imp.add(self.type_file(ent), E, ty, type=True)
        field = label_of(sm["field"])
        return f"""{imp.render()}

export interface {name}Props {{
  {e}: {E};
  allowed: {ty}[];
  onTransition: (to: {ty}) => void;
  isPending: boolean;
  error: string | null;
}}

export function {name}({{ {e}, allowed, onTransition, isPending, error }}: {name}Props) {{
  const [next, setNext] = useState<{ty} | ''>('');
  if (allowed.length === 0) {{
    return (
      <p data-testid="status-no-transitions" className="text-sm text-textMuted">
        No {field.lower()} changes are available to you from {{stateLabel({e}.{sm['field']})}}.
      </p>
    );
  }}
  return (
    <form
      className="flex max-w-md flex-col gap-3"
      onSubmit={{(event) => {{
        event.preventDefault();
        if (next) {{
          onTransition(next);
          setNext('');
        }}
      }}}}
    >
      {{error && <Alert variant="danger">{{error}}</Alert>}}
      <Select
        label="Change {field.lower()}"
        data-testid="{tid}"
        placeholder="Select new {field.lower()}"
        hint={{`Current {field.lower()}: ${{stateLabel({e}.{sm['field']})}}`}}
        value={{next}}
        onChange={{(event) => setNext(event.target.value as {ty} | '')}}
        options={{allowed.map((s) => ({{ value: s, label: stateLabel(s) }}))}}
      />
      <Button type="submit" disabled={{!next}} loading={{isPending}} data-testid="{tid}-submit">
        Update {field.lower()}
      </Button>
    </form>
  );
}}
"""

    def _c_stats(self, comp: dict, path: str) -> str:
        from app.generation.component_contracts import stats_prop

        name = comp["name"]
        ents = comp.get("entities", [])
        imp = Imports(path)
        for e in ents:
            imp.add(self.type_file(e), entity_name(e), type=True)
        imp.add("src/lib/stateMachines.ts", "stateLabel")
        props = ";\n  ".join(f"{stats_prop(e)}: {entity_name(e)}[]" for e in ents)
        args = ", ".join(stats_prop(e) for e in ents)
        cards = []
        for e in ents:
            p = stats_prop(e)
            cards.append(f"    {{ id: {q(slug(plural(tail(e))))}, label: {q(entity_plural(e))}, value: {p}.length }},")
            sm = machine_for_entity(self.g, e)
            if sm:
                for s in sm["states"]:
                    cards.append(f"    {{ id: {q(slug(plural(tail(e))) + '-' + slug(s))}, label: `{entity_plural(e)} · ${{stateLabel({q(s)})}}`, value: {p}.filter((x) => x.{sm['field']} === {q(s)}).length }},")
        cards_s = "\n".join(cards)
        return f"""{imp.render()}

export interface {name}Props {{
  {props};
}}

export function {name}({{ {args} }}: {name}Props) {{
  const cards = [
{cards_s}
  ];
  return (
    <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4" data-testid="dashboard-stats">
      {{cards.map((c) => (
        <div key={{c.id}} className="rounded-lg border border-border bg-surface p-4 shadow-card">
          <dt className="text-sm text-textMuted">{{c.label}}</dt>
          <dd className="mt-1 text-3xl font-semibold text-text" data-testid={{`stat-${{c.id}}`}}>
            {{c.value}}
          </dd>
        </div>
      ))}}
    </dl>
  );
}}
"""

    def _c_table(self, comp: dict, path: str) -> str:
        name, ent = comp["name"], comp["entity"]
        E = entity_name(ent)
        sm = machine_for_entity(self.g, ent)
        badge = self.badge_component(ent)
        link_screen = self.g.get(comp["link_to"]) if comp.get("link_to") else None
        delete_wf = next((self.g.require(w) for w in comp.get("row_actions", []) if self.g.require(w)["kind"] == "delete"), None)
        disp = self.display_field(ent)
        imp = Imports(path)
        imp.add("react", "useEffect", "useState")
        imp.add("src/components/ui/Pagination.tsx", "Pagination")
        imp.add("src/components/ui/Table.tsx", "Table", "TBody", "Td", "Th", "THead", "Tr")
        imp.add(self.type_file(ent), E, type=True)
        imp.add("src/lib/lookups.ts", "Lookups", type=True)
        fields = self.list_fields(ent)
        heads, cells = [], []
        for f in fields:
            lab = field_label(self.g, ent, f["name"])
            heads.append(f"            <Th>{lab}</Th>")
            n, t = f["name"], f["type"]
            if n == disp and link_screen:
                imp.add("react-router-dom", "Link")
                imp.add("src/app/routes.ts", "routeTo")
                expr = (f"<Link className=\"inline-flex min-h-[44px] items-center font-medium text-primary underline underline-offset-2 md:min-h-[24px]\" to={{routeTo({q(link_screen['id'])}, {{ id: item.id }})}}>"
                        f"{{item.{n}}}</Link>")
            elif t == "ref":
                expr = f"{{lookups?.[{q(n)}]?.[item.{n} ?? ''] ?? '—'}}"
            elif sm and sm["field"] == n and badge:
                imp.add(component_path(badge), badge["name"])
                expr = f"<{badge['name']} status={{item.{n}}} />"
            elif t in ("date", "datetime"):
                imp.add("src/lib/format.ts", "formatDate")
                expr = f"{{formatDate(item.{n})}}"
            elif t in ("integer", "number", "boolean"):
                expr = f"{{String(item.{n})}}"
            else:
                expr = f"{{item.{n} || '—'}}"
            cells.append(f"              <Td label={q(lab)}>{expr}</Td>")
        action_head = action_cell = ""
        props_extra = ""
        sig = "items, lookups" if any(f["type"] == "ref" for f in fields) else "items"
        if delete_wf:
            imp.add("src/components/ui/Button.tsx", "Button")
            props_extra = f"  onDelete?: (item: {E}) => void;\n  deletingId?: string | null;\n"
            sig = ("items, lookups, onDelete, deletingId" if any(f["type"] == "ref" for f in fields) else "items, onDelete, deletingId")
            action_head = "            {onDelete && (\n              <Th>\n                <span className=\"sr-only\">Actions</span>\n              </Th>\n            )}"
            action_cell = (f"              {{onDelete && (\n                <Td label=\"Actions\" className=\"md:text-right\">\n"
                           f"                  <Button\n                    variant=\"danger\"\n                    size=\"sm\"\n                    data-testid=\"{workflow_testid(delete_wf['id'])}\"\n"
                           f"                    aria-label={{`{delete_wf['name'].split()[0]} ${{item.{disp}}}`}}\n                    loading={{deletingId === item.id}}\n"
                           f"                    onClick={{() => onDelete(item)}}\n                  >\n                    {(delete_wf.get('trigger') or {}).get('label', 'Delete')}\n                  </Button>\n                </Td>\n              )}}")
        return f"""{imp.render()}

const PAGE_SIZE = 10;

export interface {name}Props {{
  items: {E}[];
  lookups?: Lookups;
{props_extra}}}

export function {name}({{ {sig} }}: {name}Props) {{
  const [page, setPage] = useState(1);
  const pageCount = Math.max(1, Math.ceil(items.length / PAGE_SIZE));
  useEffect(() => {{
    if (page > pageCount) setPage(pageCount);
  }}, [page, pageCount]);
  const visible = items.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  return (
    <div>
      <Table aria-label="{entity_plural(ent)}">
        <THead>
          <Tr>
{chr(10).join(heads)}
{action_head}
          </Tr>
        </THead>
        <TBody>
          {{visible.map((item) => (
            <Tr key={{item.id}} data-testid={{`{row_testid(ent)}-${{item.id}}`}}>
{chr(10).join(cells)}
{action_cell}
            </Tr>
          ))}}
        </TBody>
      </Table>
      <Pagination page={{page}} pageCount={{pageCount}} onPageChange={{setPage}} />
    </div>
  );
}}
"""

    def _form_field_jsx(self, wf: dict, name: str, imp: Imports, used: set[str]) -> str:
        ent = wf["entity"]
        f = self.g.entity_field(ent, name)
        lab = field_label(self.g, ent, name)
        req = " required" if self.is_required(ent, name) else ""
        err = f"error={{errors.{name}?.message}}"
        reg = f"{{...register({q(name)})}}"
        t = f["type"]
        if t == "text":
            used.add("Textarea")
            return f"      <Textarea label={q(lab)}{req} {err} {reg} />"
        if t in ("ref", "enum"):
            used.add("Select")
            if t == "ref":
                opts = f"refOptions[{q(name)}] ?? []"
            else:
                opts = "[" + ", ".join(f"{{ value: {q(v)}, label: {q(state_label(v))} }}" for v in f["values"]) + "]"
            return f"      <Select label={q(lab)}{req} placeholder={q('Select ' + lab.lower())} options={{{opts}}} {err} {reg} />"
        used.add("Input")
        extra = {"password": ' type="password" autoComplete="current-password"', "email": ' type="email" autoComplete="email"', "date": ' type="date"',
                 "integer": ' type="number" inputMode="numeric"', "number": ' type="number"'}.get(t, "")
        return f"      <Input label={q(lab)}{req}{extra} {err} {reg} />"

    def _c_form(self, comp: dict, path: str) -> str:
        wf = self.g.require(comp["workflow"])
        name = comp["name"]
        schema, values, defaults = workflow_schema_names(wf)
        login = wf["kind"] == "login"
        has_ref = any((self.g.entity_field(wf["entity"], n) or {}).get("type") == "ref" for n in wf["form_fields"])
        imp = Imports(path)
        imp.add("@hookform/resolvers/zod", "zodResolver")
        imp.add("react", "useEffect")
        imp.add("react-hook-form", "useForm")
        imp.add("src/components/ui/Alert.tsx", "Alert")
        imp.add("src/components/ui/Button.tsx", "Button")
        imp.add(workflow_schema_file(wf), schema, defaults)
        imp.add(workflow_schema_file(wf), values, type=True)
        used: set[str] = set()
        fields = "\n".join(self._form_field_jsx(wf, n, imp, used) for n in wf["form_fields"])
        imp.add("src/components/ui/Field.tsx", *sorted(used))
        if has_ref:
            imp.add("src/components/ui/Field.tsx", "SelectOption", type=True)
        props = [f"  onSubmit: (values: {values}) => void;"]
        if not login:
            props.append("  onCancel: () => void;")
        props += ["  isSubmitting: boolean;", "  serverError: string | null;", "  fieldErrors: Record<string, string>;"]
        if has_ref:
            props.append("  refOptions: Record<string, SelectOption[]>;")
        args = ["onSubmit", "isSubmitting", "serverError", "fieldErrors"] + ([] if login else ["onCancel"]) + (["refOptions"] if has_ref else [])
        reset_line = "" if login else "    reset,\n"
        secondary = "" if login else (
            "        <Button variant=\"ghost\" onClick={onCancel}>\n          Cancel\n        </Button>\n"
            "        <Button variant=\"secondary\" onClick={() => reset()}>\n          Reset\n        </Button>\n")
        return f"""{imp.render()}

export interface {name}Props {{
{chr(10).join(props)}
}}

export function {name}({{ {', '.join(args)} }}: {name}Props) {{
  const {{
    register,
    handleSubmit,
{reset_line}    setError,
    formState: {{ errors }},
  }} = useForm<{values}>({{ resolver: zodResolver({schema}), defaultValues: {defaults} }});

  useEffect(() => {{
    for (const [field, message] of Object.entries(fieldErrors)) {{
      if (field in {defaults}) setError(field as keyof {values}, {{ type: 'server', message }});
    }}
  }}, [fieldErrors, setError]);

  return (
    <form data-testid="{form_testid(wf['id'])}" noValidate onSubmit={{handleSubmit(onSubmit)}} className="flex w-full max-w-xl flex-col gap-4">
      {{serverError && (
        <Alert variant="danger" data-testid="form-error">
          {{serverError}}
        </Alert>
      )}}
{fields}
      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
{secondary}        <Button type="submit" loading={{isSubmitting}}>
          {wf.get('submit_label', 'Submit')}
        </Button>
      </div>
    </form>
  );
}}
"""
