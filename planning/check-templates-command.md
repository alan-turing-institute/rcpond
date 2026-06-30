# `check-templates` CLI Command

## Goal

Provide a `rcpond check-templates <dir>` command that renders all Jinja2 templates
in a given directory and exits non-zero if any fail. Intended for use as a CI check
in the separate templates repo.

## Command signature

```
rcpond check-templates <templates-dir>
```

- Takes a single positional argument: path to the templates directory.
- Requires **no** ServiceNow or LLM configuration — fully standalone.
- Exits 0 if all templates render successfully; exits 1 if any fail.

## Algorithm

1. **Discover templates**: glob `<dir>/*.j2` (same as `PostTemplatedNoteTool`).
2. **Identify top-level templates**: any file whose name does _not_ start with `_`.
   Underscore-prefixed files are partials — they are available to the Jinja
   `FileSystemLoader` for `{% include %}` resolution but are not rendered directly.
3. **Collect undeclared variables**: for each top-level template, use
   `jinja2.Environment.parse()` + `jinja2.meta.find_undeclared_variables()` to
   discover all variables the template (including any included partials, by parsing
   them separately and unioning their variables) expects. Discard `ticket` — it is
   a context variable supplied at real render time.
4. **Fill dummies**: build a context dict mapping every undeclared variable name to
   a placeholder string based on the name of the variable, by appending `_placeholder` onto the name of any str variable (e.g. `{"subject": "subject_placeholder"}`). This
   makes rendered output identifiable and avoids `UndefinedError`.
5. **Render**: use `jinja2.Environment(loader=FileSystemLoader(<dir>))` to render
   each top-level template with the dummy context. A `FileSystemLoader` is required
   so that `{% include %}` directives resolve correctly.
6. **Collect results**: record which templates passed and which raised an exception
   (e.g. `TemplateSyntaxError`, `TemplateNotFound`).
7. **Report**: print a summary table (pass/fail per template) and, for failures,
   the exception message. Exit 1 if any failures occurred.

## Error modes caught

| Error | Example cause |
|---|---|
| `jinja2.TemplateSyntaxError` | Unclosed block, bad filter name |
| `jinja2.TemplateNotFound` | `{% include '_missing.j2' %}` where file doesn't exist |
| `jinja2.UndefinedError` | Would only occur if variable discovery missed something (e.g. dynamic variable names) |

## Implementation plan

### `command.py` — new function

```python
def check_templates(templates_dir: Path) -> bool:
    """Render all non-partial templates with dummy variables. Returns True if all pass."""
```

Returns `True` if every template rendered without error, `False` otherwise. Prints
results to stdout. Lives in `command.py` alongside the other high-level commands.
No dependency on `Config`, `ServiceNow`, or `LLM`.

### `cli.py` — new subcommand

```python
@cli.command()
def check_templates(templates_dir: Path) -> None:
    """Render all Jinja2 templates in a directory with dummy values (for CI)."""
```

Calls `command.check_templates(templates_dir)` and raises `typer.Exit(1)` on failure.
Does **not** call `_config()` — no env file or credentials needed.

## CI usage in the templates repo

In the templates repo's CI workflow (e.g. GitHub Actions):

```yaml
- name: Install rcpond
  run: pip install rcpond  # or: uv add --dev rcpond

- name: Check templates render
  run: rcpond check-templates ./templates
```

The templates repo needs no Python test code of its own — the check is entirely
owned by rcpond.

## Out of scope

- Snapshot/golden-file comparison of rendered output (can be added later).
- Recursive subdirectory discovery (flat directory assumed for now).
- Linting template style or content (purely a render check).
