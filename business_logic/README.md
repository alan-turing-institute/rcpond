# Example business logic

A minimal, self-contained example of RCPond's per-ticket-type configuration, used by
[contributing.md](../contributing.md) to run RCPond without touching your personal
config at `~/.config/rcpond/`.

Everything here is a toy example. The real rules and templates are not in this public repo.

## Layout

```
business_logic/                                   <- point XDG_CONFIG_HOME at this
├── system_prompt_template.txt                    <- shared by every ticket type
├── rcpond/
│   └── ticket_types/                             <- fixed location; see "Why the nesting?"
│       ├── compute_allocation_request.config
│       └── software_request.config
├── compute_allocation_request/                   <- runnable
│   ├── RULES.md
│   └── email_templates/{approve,resubmit}.yaml.j2
└── software_request/                             <- illustrative only; see below
    ├── RULES.md
    └── email_templates/approve.yaml.j2
```

## Why the nesting?

RCPond looks for a ticket type's config at a **fixed** path:

```
$XDG_CONFIG_HOME/rcpond/ticket_types/<ticket-type>.config
```

There is no environment variable or CLI flag that points somewhere else. Setting
`XDG_CONFIG_HOME=business_logic` is therefore how this directory is used, and it is why
the `.config` files sit under `business_logic/rcpond/ticket_types/` rather than beside
the rules they configure.

Relocating `XDG_CONFIG_HOME` also moves where `default.config` is looked up. There isn't
one here, which is deliberate: your personal config is then entirely out of the picture
and every remaining value must come from the environment.

> [!IMPORTANT]
> `XDG_CONFIG_HOME` **must be an absolute path**. A relative value is silently ignored —
> you get `~/.config` instead, and a confusing "No config file found for ticket type"
> error naming a path you never set.
>
> From the [XDG Base Directory Specification](https://specifications.freedesktop.org/basedir/latest/),
> *Basics*: "All paths set in these environment variables must be absolute. If an
> implementation encounters a relative path in any of these variables it should consider
> the path invalid and ignore it."

## Running it

Paths inside the `.config` files are relative to the working directory, so run from the
repository root. See [contributing.md](../contributing.md) for the full recipe.

## The second ticket type is not runnable yet

`software_request` shows what a second type's files look like, but selecting it fails:

```
$ rcpond process-next --ticket-type software_request
ValueError: Unknown ticket_type 'software_request'. Known types: 'compute_allocation_request'.
```

`Config` validates `--ticket-type` against the `_TICKET_TYPES` registry in
`src/rcpond/servicenow.py`, which currently holds only `compute_allocation_request`.
Making this type work needs a `Ticket` subclass with its own `MATCH_CRITERIA` registered
there — that is the outstanding work described in
[planning/multiple-ticket-types.md](../planning/multiple-ticket-types.md).

Until then these files serve as the layout reference for adding a type, and as a check
that nothing about the directory structure assumes a single type.
