# rcpond

[![Actions Status][actions-badge]][actions-link]
[![PyPI version][pypi-version]][pypi-link]
[![PyPI platforms][pypi-platforms]][pypi-link]

A tool to partly automate RCP requests

## Installation

For most users the recommended installation method is via `uv`:
```bash
uv tool install git+ssh://git@github.com/alan-turing-institute/rcpond.git
```
RCPond will need additional configuration before its first use. See [docs/usage.md](docs/usage.md) for instructions on how to set up the configuration files and obtain a ServiceNow API token.

## Usage

See [docs/usage.md](docs/usage.md) for configuration and command reference.

## Contributing

See [CONTRIBUTING.md](contributing.md) for instructions on how to contribute.

## License

Distributed under the terms of the [MIT licence](licence.md).


<!-- prettier-ignore-start -->
[actions-badge]:            https://github.com/alan-turing-institute/rcpond/workflows/CI/badge.svg
[actions-link]:             https://github.com/alan-turing-institute/rcpond/actions
[pypi-link]:                https://pypi.org/project/rcpond/
[pypi-platforms]:           https://img.shields.io/pypi/pyversions/rcpond
[pypi-version]:             https://img.shields.io/pypi/v/rcpond
<!-- prettier-ignore-end -->
