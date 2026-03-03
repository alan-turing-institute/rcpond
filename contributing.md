See the [Scientific Python Developer Guide][spc-dev-intro] for a detailed
description of best practices for developing scientific packages.

[spc-dev-intro]: https://learn.scientific-python.org/development/

# Setting up a development environment manually

You can set up a development environment by running:

```zsh
python3 -m venv venv          # create a virtualenv called venv
source ./venv/bin/activate   # now `python` points to the virtualenv python
pip install -v -e ".[dev]"    # -v for verbose, -e for editable, [dev] for dev dependencies
```

# Post setup

You should prepare pre-commit, which will help you by checking that commits pass
required checks:

```bash
pip install pre-commit # or brew install pre-commit on macOS
pre-commit install # this will install a pre-commit hook into the git repo
```

You can also/alternatively run `pre-commit run` (changes only) or
`pre-commit run --all-files` to check even without installing the hook.

# Testing

Use pytest to run the unit checks:

```bash
pytest
```

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


## Verifiying and serving the docs locally

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
