# Fixtures

The golden input is the real package in `projects/task_manager/graphs/`. Negative tests copy it into a temp directory
(`tests/conftest.py: project` fixture) and break exactly one thing with `edit_graph(...)`, so there is a single source
of truth for graph content and no drifting duplicate fixtures.
