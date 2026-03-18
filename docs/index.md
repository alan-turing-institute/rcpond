# RCPond

A tool to partly automate RCP requests.

RCPond reads requests via tickets from an ServiceNow instance. These requests are typically for computing resources, but the tool could be adapted for other types of requests. RCPond uses a lean LLM to read the request and recommend actions to take.

## Quick start

Try the instructions below. If you need more details or encounter any issues, see the [Configuration](configuration.md) and [Contributing](contributing.md) docs.

### 1 - Install RCPond using `uv`:

```bash
$ uv tool install git+https://github.com/alan-turing-institute/rcpond.git
```

### 2 - Create the default configuration file:

```bash
$ uvx git+ssh://git@github.com/alan-turing-institute/rcpond-rules.git
```

### 3 - Obtain a ServiceNow API token

See [Configuration](configuration.md) for the details and then add the key to the configuration file at `~/.config/rcpond/default.config`

## Further details

* [Configuration](configuration.md)
* [Command reference](command_reference.md)
