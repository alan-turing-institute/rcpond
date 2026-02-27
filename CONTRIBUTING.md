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

The pre-commit also checks for possible secrets in the code, using the custom script `pre-commit-scripts/check_secrets.py`. Specifically, it look for the strings
`RCPOND_LLM_API_KEY` and `RCPOND_SERVICENOW_TOKEN` in text files.

There are accepted safe placeholder values, which can be committed. To update the environment variable which are monitored, or the accepted placeholder values, edit the `CHECKED_KEYS` dict within the `check_secrets.py` script.

NOTE: this is not foolproof. For example, it does not detect if the API key is stored on a separate line to the variable name:
```
RCPOND_LLM_API_KEY:
my_secret_api_key_value
```
