# RCPond

A tool to partly automate RCP requests.

RCPond reads requests via tickets from an ServiceNow instance. These requests are typically for computing resources, but the tool could be adapted for other types of requests. RCPond uses a Lean Language Model (LLM) to read the request and recommend actions to take.

## Quick start

### 1 - Install RCPond using `uv`:

```bash
uv tool install git+ssh://git@github.com/alan-turing-institute/rcpond.git
```

### 2 - Create the default configuration file:

```bash
uvx --from git+ssh://git@github.com/alan-turing-institute/rcpond-rules.git rcpond-install
```

### 3. Obtain a ServiceNow API token

See [Configuration](configuration.md) for the details and then add the key to the configuration file at `~/.config/rcpond/default.config`

## Further details

* [Configuration](configuration.md)
* [Command reference](command_reference.md)
