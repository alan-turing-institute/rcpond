# Ticket dump files

`rcpond dump-tickets` writes a [JSON Lines](https://jsonlines.org/) file holding every
ticket of every ticket type RCPond knows about. Other RCPond commands read it, and so can
anything else — the format is plain JSON, one object per line, and needs no RCPond code to
parse.

See the [command reference](command_reference.md) for the command's options.

## What the file looks like

The **first line is a header** describing the dump. Every line after it is one ticket:

```json
{"schema_version": 1, "created_at": "2026-11-07T14:53:21+00:00", "record_count": 412, ...}
{"type_key": "compute_allocation_request", "ticket": {"number": "RES0001009", ...}}
{"type_key": "github_onboarding_request", "ticket": {"number": "RES0001073", ...}}
```

Records are sorted by ticket number, so two dumps of the same instance can be diffed
directly.

`type_key` names the ticket type the ticket was classified as **at the time of the dump**.
Treat it as the authoritative answer rather than re-deriving the type from the ticket's
fields: ServiceNow wording changes over time, and the dump records what was true when it
was written.

Each `ticket` object holds the full ticket — the standard fields plus the catalogue
variables belonging to that ticket type. Which variables those are depends on `type_key`.

## What the header tells you

The header records where the dump came from and what it covers: when it was taken, the
instance URLs, the query sent, the ticket types registered at the time, how many records
follow, and whether `--limit` was applied.

Two of those are worth reading before trusting a dump:

- **`limit`** is non-null when the dump is deliberately partial. The header is the only
  place that says so — a sampled file is otherwise indistinguishable from a complete one.
- **`registry_ticket_types`** lists the ticket types RCPond knew about when the dump ran.
  Types absent from that list are absent from the file, however many such tickets the
  instance holds.

`created_at` is ISO 8601 in UTC. It is the time of the dump, not of the report or analysis
that reads it.

The [`rcpond.ticket_dumps` API reference](api.md) documents every header field.

## Reading one outside RCPond

```python
import json

import pandas as pd

with open("dump.jsonl") as f:
    header = json.loads(f.readline())
    tickets = pd.DataFrame(json.loads(line)["ticket"] for line in f)

print(header["created_at"], header["record_count"], header["limit"])
```

Mixing ticket types in one dataframe gives empty cells where a type lacks another type's
catalogue variables. To work with a single type, filter on `type_key` as you read:

```python
with open("dump.jsonl") as f:
    next(f)  # skip the header
    records = [json.loads(line) for line in f]

compute = pd.DataFrame(
    r["ticket"] for r in records if r["type_key"] == "compute_allocation_request"
)
```

## Versions

The header's `schema_version` says which version of the format a file uses.

**RCPond reads only the version it was built for.** There is no conversion of older dumps
and no fallback. If a dump is rejected as the wrong version, the
[changelog](changelog.md) records which RCPond version writes which `schema_version`, and
that is where to look for one that can read it.

Fields may be added to the header, or to a ticket, without changing `schema_version`, so a
reader should ignore fields it does not recognise rather than failing on them.
