"""UI conventions the generated app, its tests and the prompts must agree on."""

UI_CONVENTIONS = {
    "page_root": 'Every page root element has data-testid="page-<screen-slug>" (e.g. page-project-list).',
    "workflow_trigger": 'Every control that starts a workflow has data-testid="workflow-<workflow-slug>" '
    "(e.g. workflow-project-create). Controls the role lacks permission for are NOT rendered.",
    "form": 'Every form root has data-testid="form-<workflow-slug>". Inputs are labelled with the field label; '
    "the submit button text is the workflow's submit_label.",
    "rows": 'Every list row has data-testid="row-<entity-slug>-<id>".',
    "states": 'Loading state: data-testid="loading-state". Empty state: data-testid="empty-state". '
    'Error state: role="alert" with data-testid="error-state" and a Retry button.',
    "notifications": 'Success notifications render in a role="status" region.',
}
