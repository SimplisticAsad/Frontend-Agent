# Graph package contract (input of the Frontend Agent)

The Graph-Making Agent owns *what* the product is. The Frontend Agent reads a directory of JSON graphs and never
reads the original user idea. The entry point is `graph_manifest.json`:

```json
{ "schema_version": "1.0", "project_id": "task_manager", "graph_version": "1.0.0",
  "files": { "project": "project.json", "screens": "screens.json", "...": "..." } }
```

Every graph file is `{ "schema_version": "1.0", "graph": "<name>", "nodes": [ {...}, ... ] }`.
Node ids are globally unique and prefixed by graph (`screen.`, `api.`, `workflow.`, ...). Only the frontend graphs are
loaded (`project actors roles entities relationships capabilities requirements screens components workflows api
permissions validations state_machines dependencies acceptance_criteria assumptions questions`); `backend.json` and
friends are ignored. **Any structural or referential error is a `GRAPH_ERROR` and the pipeline stops before anything is
planned or generated.**

| graph | required keys | notes |
|---|---|---|
| `project` | `name` | one node |
| `roles` | `key`, `name`, `permissions[]` | `key` is what the user object carries (`"manager"`) |
| `permissions` | `action`, `resource`, `roles[]`; optional `conditions` | `conditions: {"role.employee": {"scope": "assigned", "field": "assignee_id"}}` = row-level rule (UI only) |
| `entities` | `name`, `fields[]` | field: `name`, `type` (`string text integer number boolean date datetime enum ref email password`), `required`, `readonly`, `values` (enum), `ref` (entity id); entity: `display_field`, `list_fields`, `state_machine`, `transient` |
| `screens` | `name`, `route`, `layout` (`public`/`authenticated`), `kind` (`login dashboard list form details`) | `feature`, `entity`, `components[]`, `data_sources[]` (api ids), `actions[]` (workflow ids), `permissions[]`, `nav`, `nav_order` |
| `components` | `name`, `kind` (`page_header form stats table status_badge status_control`) | `entity`, `workflow`, `state_machine`, `link_to`, `row_actions[]`, `shared` |
| `workflows` | `name`, `kind` (`login create delete transition`), `entity`, `api` | `permission` (required except login), `trigger{screen,label}`, `screen` (form screen), `form_fields[]`, `submit_label`, `success{navigate,notification}`, `confirm`, `state_machine`+`field` (transition) |
| `api` | `method`, `path`, `operation` (`login list get create delete transition`) | `auth`, `permission`, `request{entity,fields[{name,type,required,source}]}`, `response{entity,shape}`, `errors[]`. `source`: `form` (default), `path`, `query`, `input`, `session.user_id`, `session.role` |
| `validations` | `entity`, `field`, `rules` | rules: `required min_length max_length pattern format(email) min max`; optional `message` |
| `state_machines` | `entity`, `field`, `states[]`, `initial`, `transitions[{from,to,permission}]` | the UI offers *only* these transitions |
| `acceptance_criteria` | `title`, `workflow`, `type` | types: `workflow_success validation_failure workflow_denied transition_allowed transition_denied`; become Playwright tests |
| others | free text | `capabilities`, `requirements`, `relationships`, `dependencies`, `assumptions`, `questions` are validated for references and surfaced as context/warnings; a *blocking* open question is an error |

## Checks beyond schema
* `GRAPH_ERROR` - missing/invalid files, dangling references (screen -> api/workflow/component/permission/entity, workflow ->
  api/entity/permission/screen, role <-> permission, validation -> field, ...), duplicate ids/routes, unsupported kinds,
  unreachable workflows, blocking open questions.
* `GRAPH_IMPLEMENTATION_CONFLICT` - the graph is internally valid but cannot be implemented as written: an API requires a
  field that neither the workflow's form nor a named source (`path`, `session.*`, ...) supplies; a form field the API
  does not accept; a `ref` form field whose screen has no list API to populate it. The agent reports it; it never invents
  behaviour to paper over it.
* `GRAPH_CONFLICT` - raised during correction when the model concludes the *graph* (not the code) is at fault.
