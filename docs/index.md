# RCPond

A tool to partly automate RCP requests.

RCPond reads requests via tickets from an ServiceNow instance. These requests are typically for computing resources, but the tool could be adapted for other types of requests. RCPond uses a lean LLM to read the request and recommend actions to take.

## Quick start

Try the instructions below for the simplest setup. If you need more details, different setup options or encounter any issues, see the [Configuration](configuration.md) and [Contributing](contributing.md) docs.

### 1 - Install RCPond using `uv`:

```bash
$ uv tool install git+https://github.com/alan-turing-institute/rcpond.git
```

See the [Installation](configuration.md#installing-rcpond) docs for more details, including upgrading existing installations and troubleshooting tips.

### 2 - Create the default configuration file:

```bash
$ uvx git+ssh://git@github.com/alan-turing-institute/rcpond-rules.git
```

This command should complete within a few seconds. See the [Configuration](configuration.md#using-the-default-configuration-file-recommended) docs for more details, including troubleshooting tips.

### 3 - Login to ServiceNow via the CLI

```bash
$ rcpond login
```

### 4 - Display the relevant ServiceNow tickets:

```bash
$ rcpond display-all
```

## Further details

* [Configuration](configuration.md)
* [Command reference](command_reference.md)
