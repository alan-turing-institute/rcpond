See the [Scientific Python Developer Guide][spc-dev-intro] for a detailed
description of best practices for developing scientific packages.

[spc-dev-intro]: https://learn.scientific-python.org/development/

# Setting up a development environment manually

You can set up a development environment by running:

```zsh
uv venv         # create a virtualenv called venv
source .venv/bin/activate   # now `python` points to the virtualenv python
uv pip install -v -e . --group dev    # `-v` for verbose, `-e` for editable, `--group dev` for dev dependencies
```

# Post setup

You should prepare pre-commit, which will help you by checking that commits pass
required checks:

```bash
pre-commit install # this will install a pre-commit hook into the git repo
```

You can also/alternatively run `pre-commit run` (changes only) or
`pre-commit run --all-files` to check even without installing the hook.

# Testing

Use pytest to run the unit checks:

```bash
pytest
```

There are also integration tests. These are disabled by default and are not included in the CI/CD testing, but they can be run with:

```bash
pytest -m integration
```

The integration tests require a live connection to a ServiceNow (Dev) instance, specified in a `.env` file. *Running these test will make permanent changes to the tickets on the ServiceNow instance* so they are not suitable for regular unit testing. They are intended to be run manually when making changes to the `ServiceNow` class or related code.

Integration test will not load any credentials from the XDG config file (`~/.config/rcpond/default.config`). This is prevented to avoid accidentally running integration tests with real credentials, causing unwanted changes to a production ServiceNow instance. If you want to run integration tests, you must explicitly provide test credentials via a `.env` file or environment variables.


# Running RCPond against the example business logic

[`business_logic/`](business_logic/) is a self-contained example of the per-ticket-type
configuration — rules, email templates and a `.config` file per type. Running against it
lets you exercise `process-next` and friends without touching your personal config at
`~/.config/rcpond/`, and without `--env-file`.

Put the non-type-specific settings in a `.env` file:

```
RCPOND_LLM_CHAT_COMPLETIONS_URL=https://...
RCPOND_LLM_API_KEY=your-api-key-here
RCPOND_LLM_MODEL=gpt-4o
RCPOND_SERVICENOW_URL=https://...
RCPOND_SERVICENOW_WEB_URL=https://...
RCPOND_SERVICENOW_TOKEN=your-servicenow-token
RCPOND_SYSTEM_PROMPT_TEMPLATE_PATH=business_logic/system_prompt_template.txt
```

Then, **from the repository root**:

```bash
set -a; source .env; set +a
XDG_CONFIG_HOME="$PWD/business_logic" rcpond process-next --ticket-type compute_allocation_request
```

`rules_path`, `email_templates_dir` and `servicenow_query` come from
`business_logic/rcpond/ticket_types/compute_allocation_request.config`; everything else
comes from the environment.

## Why `XDG_CONFIG_HOME` rather than `--env-file`

A ticket type's config is read from a **fixed** path,
`$XDG_CONFIG_HOME/rcpond/ticket_types/<ticket-type>.config`. No environment variable or
CLI flag points anywhere else, and passing `--ticket-type` makes that file mandatory —
it is an error if the file is absent, even when every value it would supply is already
set in the environment. Overriding `XDG_CONFIG_HOME` is therefore the way to point
RCPond at a different set of per-type configs.

It has the useful side effect of relocating the `default.config` lookup too, so your
personal configuration is completely out of the picture.

## Three things that will catch you out

1. **`XDG_CONFIG_HOME` must be absolute.** A relative path is silently ignored, and you
   get `~/.config` instead — producing a "No config file found for ticket type" error
   that names a path you never set. Hence `"$PWD/business_logic"`. The
   [XDG Base Directory Specification](https://specifications.freedesktop.org/basedir/latest/)
   (*Basics*) requires this: "All paths set in these environment variables must be
   absolute. If an implementation encounters a relative path in any of these variables it
   should consider the path invalid and ignore it."
2. **Quote any value containing a space** in a file you `source`. `RCPOND_SERVICENOW_QUERY`
   is the one that bites: unquoted, the shell reports `command not found` for the word
   after the space and leaves the variable *unset*, so RCPond silently falls back to its
   default query. (`--env-file` tolerates unquoted values, and now also strips matched
   surrounding quotes, so one correctly quoted file works with both mechanisms.)
3. **Run from the repository root.** Paths inside the example `.config` files are
   relative to the working directory.

## Only one ticket type is currently runnable

`business_logic/` also contains a `software_request` type, but selecting it fails:

```
ValueError: Unknown ticket_type 'software_request'. Known types: 'compute_allocation_request'
```

Its files show the layout for a second type; making it work requires registering a
`Ticket` subclass in `_TICKET_TYPES` (`src/rcpond/servicenow.py`). See
[business_logic/README.md](business_logic/README.md) and
[planning/multiple-ticket-types.md](planning/multiple-ticket-types.md).


# Coverage

Use pytest-cov to generate coverage reports:

```bash
pytest --cov=rcpond
```

# Pre-commit

This project uses pre-commit for all style checking. Install pre-commit and run:

```bash
pre-commit run -a
```

to check all files.

The pre-commit also checks for possible secrets in the code, using the custom script `pre-commit-scripts/check_secrets.py`. Specifically, it look for the strings
`RCPOND_LLM_API_KEY` and `RCPOND_SERVICENOW_TOKEN` in text files.

There are accepted safe placeholder values, which can be committed. To update the environment variable which are monitored, or the accepted placeholder values, edit the `CHECKED_KEYS` dict within the `check_secrets.py` script.

NOTE: this is not foolproof. For example, it does not detect if the API key is stored on a separate line to the variable name:
```
RCPOND_LLM_API_KEY:
my_secret_api_key_value
```

# Documentation

## Adding a new docs page

Create a Markdown file anywhere under `docs/`. For example:

```bash
touch docs/my-new-page.md
```

The [mkdocs-awesome-pages-plugin](https://github.com/lukasgeiter/mkdocs-awesome-pages-plugin)
will pick it up automatically. The page
will appear in the nav after any explicitly listed entries in `docs/.pages`. To
control where it sits relative to other pages, add it to the `nav` list in
`docs/.pages` before the `...` entry.

## Linking a root-level file into the docs

A small number of pages (home, contributing, licence, code of conduct) are
served from files that live in the repository root rather than in `docs/`. This
is done via symlinks and then add the symlink filename is added to the appropriate position in `docs/.pages`.

```bash
ln -s ../my-root-file.md docs/my-root-file.md
```

This intended only to save duplication for files that should be visible directly from the GitHub repo as well as the documentation. Most other documentation should live in `docs/` as a regular file.

## API reference

The API reference is generated automatically from docstrings using
[mkdocstrings](https://mkdocstrings.github.io/python/). The entry point is
`docs/api.md`, which contains a single directive:

```
::: rcpond
```

This renders the entire `rcpond` package recursively. Docstrings should follow
[NumPy style](https://numpydoc.readthedocs.io/en/latest/format.html).


## Verifying and serving the docs locally

Install the docs dependencies and start the MkDocs development server:

Ensure that the optional "docs" dependency group is installed, which includes MkDocs and its plugins:
```bash
uv pip install -e ".[docs]"
```

To verify the documentation builds correctly, you can run:
```bash
mkdocs build --strict --verbose
```

To serve the documentation locally, start the MkDocs development server:
```bash
mkdocs serve
```

The site is then available at `http://127.0.0.1:8000`.

# Changelog

Notable changes should be recorded in `CHANGELOG.md`, following the
[Keep a Changelog](https://keepachangelog.com/en/1.0.0/) format. Add an entry
under the `[Unreleased]` section for any user-facing change: new features go
under `Added`, behaviour changes under `Changed`, and bug fixes under `Fixed`.
Version sections are created when a release is tagged.
