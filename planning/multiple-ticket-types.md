Treat `Ticket` in `src/rcpond/servicenow.py` as the common base for all ticket types.
Treat the current `ComputeAllocationRequestTicket` as canonical for `Compute Allocation Request` tickets.
Use `temp/reg_workspace_service_now_fields.csv` to define additional fields for non-Compute ticket types (and as metadata such as `question_text`).

* Some fields (like `work_notes`) are common to all ticket types and are not listed in the spreadsheet.
* The `short_description` field on `x_tati_resmgt_research` is the actual ticket-type discriminator.
  `cat_item` does **not** exist on this table (confirmed via the REST API); `u_category` and
  `u_sub_category` are always `"Research Services"` / `"Research Computing Services"` regardless of
  ticket type, so they carry no discriminating information.
* `short_description` alone is not guaranteed to remain a 1:1 match with rcpond "ticket type" going
  forward: it's free text an admin can reword at any time, and a single `short_description` could
  in future need to split into multiple rcpond types discriminated by another field as well (e.g.
  `which_service=Azure` vs `which_service=HPC` under the same "Request access to HPC and cloud
  computing facilities" short_description). Because of this, neither the `_TICKET_TYPES` registry key
  nor the per-type config filename should be derived from `short_description` text — see
  "Implementation design decisions for Option A" below.
* At present rcpond is implemented around a single `ComputeAllocationRequestTicket` shape (the canonical Compute Allocation Request schema).
* In future we will want rcpond to handle all ticket types.
* For page scraping, `question_text` from the CSV can still help map labels in HTML.
* Different ticket types will use a different rules file and different directory of email templates
* Different ticket types correspond to ServiceNow query filters (currently hardcoded in `ServiceNow.get_tickets`). Different queries would retrieve different ticket types.
* An individual user is only likely to work on a subset of ticket types.

Ideas for how to implement multiple ticket types:

The spreadsheet could be included in config directories and used as runtime metadata for non-Compute ticket types. Keep code-level typed dataclasses as the implementation target. `ComputeAllocationRequestTicket` should remain the canonical type for Compute Allocation Request, and additional typed subclasses could be generated from (or aligned to) CSV data for other ticket categories.

---

## Option A — Typed subclasses with a registry (recommended)

Keep the current dataclass pattern. Use `ComputeAllocationRequestTicket` as the canonical class for Compute Allocation Request. For each new ticket type, define a sibling
dataclass with exactly its own fields:

```python
@dataclass
class ComputeAllocationRequestTicket(Ticket):
    MATCH_CRITERIA: ClassVar[MappingProxyType[str, str]] = MappingProxyType({
        "short_description": "Request access to HPC and cloud computing facilities"
    })
    project_title: str
    # ... current ComputeAllocationRequestTicket fields

@dataclass
class GeneralComputeSupportTicket(Ticket):
    MATCH_CRITERIA: ClassVar[MappingProxyType[str, str]] = MappingProxyType({
        "short_description": "General Compute Support Request"
    })
    which_service: str
    which_facility: str
    please_give_details_of_your_query: str

# Registry: arbitrary, developer-chosen key → dataclass.
# The key is never derived from ticket data; dispatch uses each class's MATCH_CRITERIA.
# The key also serves as the per-type config filename stem.
_TICKET_TYPES: dict[str, type[Ticket]] = {
    "compute_allocation_request": ComputeAllocationRequestTicket,
    "general_compute_support": GeneralComputeSupportTicket,
    ...
    # Future, once a single short_description needs to split by another field, each class
    # declares its own MATCH_CRITERIA with both short_description and which_service:
    # "compute_allocation_request_azure": AzureComputeAllocationRequestTicket,
    # "compute_allocation_request_hpc":   HpcComputeAllocationRequestTicket,
}
```

`ServiceNow.get_full_ticket` finds the first `_TICKET_TYPES` class whose `MATCH_CRITERIA` all hold
against the ticket's own fields, and dispatches to that class. The registry *key* (not any ticket
field) then identifies which per-type config to load.
`Config` gains a list of per-type configs mapping that same key → `(rules_path, email_templates_dir,
servicenow_query)`.

Note: today `MATCH_CRITERIA` only ever needs `short_description`, since that's the only base-`Ticket`
field available before the type is resolved. Matching on a field like `which_service` (a catalogue
variable only fetched once the class and its extra-field list are known) would require fetching a
set of common discriminator fields before dispatch. That fetch-ordering change is not needed yet
and is left as a follow-up design question for when a `which_service`-style split is required.

**Pros:** Preserves type safety, IDE completion, template validation, and the JSON the LLM sees
stays flat and cleanly named. Nothing in `prompt.py` or `tools.py` needs to change.

**Cons:** Each new ticket type requires code changes. Field renames in ServiceNow require code
changes.

---

## Option B — `variables: dict[str, str]` on a single generic ticket class

Replace the typed ComputeAllocationRequestTicket fields with a single `variables` dict. `short_description`
is already on the base `Ticket` class and serves as the type key — no new field needed:

```python
@dataclass
class GenericTicket(Ticket):
    variables: dict[str, str]  # keyed by ServiceNow field name
```

`ServiceNow.get_full_ticket` fetches all `variables.*` fields and stores them in the dict without
knowing their names in advance. `parse_ticket_html` builds the dict directly from HTML labels
using `question_text` (CSV optional). `Config` maps `short_description` → `(rules_path, email_templates_dir,
query)`.

The LLM prompt would look like:
```json
{
  "short_description": "Request access to HPC and cloud computing facilities",
  "variables": {
    "project_title": "...",
    "which_service": "Azure",
    ...
  }
}
```

**Pros:** Adding a new ticket type requires zero code changes. Field names come from ServiceNow/HTML
at runtime. HTML scraping becomes simpler.

**Cons:** Loses type safety and IDE support for individual fields. Template validation
(`_unknown_ticket_attrs` in `config.py`) breaks since there are no typed fields to validate
against. The LLM gets a nested dict instead of flat keys. The one direct field access in code
(`full_ticket.which_service` in `command.py`) breaks.

---

## Option C — Config-driven per-type dataclasses (dynamic, fully data-driven)

Include a schema file (CSV or derived TOML/JSON) in each rcpond-rules deployment. At startup, `Config`
reads that schema and calls `dataclasses.make_dataclass()` to construct the appropriate class for the
configured ticket type(s):

```python
# In Config.__post_init__:
fields_for_type = _read_fields_from_csv(csv_path, short_description="Request access to HPC and cloud computing facilities")
TicketClass = dataclasses.make_dataclass("ComputeAllocationRequestTicket", fields_for_type, bases=(Ticket,))
```

**Pros:** Completely data-driven — changing field names or adding new ticket types requires only
updating schema metadata in rcpond-rules, not the rcpond codebase.

**Cons:** Highest implementation complexity. Type checkers cannot reason about the
dynamically-created class. Template validation and `dataclasses.asdict` still work at runtime,
but IDE and mypy support is effectively lost. Probably premature given only one ticket type is
currently in use.

---

## Recommendation

**Option A** is the least risky path that supports the stated goal of handling all ticket types.
The main effort is:

1. Define typed dataclasses for currently supported `short_description` values.
2. Add a registry mapping an arbitrary, developer-chosen key → match criteria (today just
   `short_description`) + dataclass. The key must never be derived from `short_description` or any
   other ticket field — see "Implementation design decisions" below for why.
3. Extend `Config` so users can configure which types they handle, and point each type (by that same
   key) to its rules file, email templates directory, and ServiceNow query filter.

The field data for step 1 should come from: (a) current code for shared/base fields (`Ticket`) and the Compute Allocation Request schema (`ComputeAllocationRequestTicket`), and (b) CSV + verified ServiceNow payloads for other ticket types.

**Option B** becomes attractive if the field sets are unstable (ServiceNow admins regularly rename
or add fields) and maintaining code per ticket type is impractical. The cost is losing type-checked
template validation — but that could be recovered by validating template variables against a schema
source at config load time instead of against `dataclasses.fields`.

---

## Q: How should per-ticket-type config mappings work in practice?

Three distinct design questions here — let me take them separately.

1. How the dotenv format could represent per-type config
The current flat KEY=VALUE format can support multiple types in two ways:

A) Namespaced keys with an active-types list:

```
RCPOND_ACTIVE_TICKET_TYPES=compute_allocation_request,general_compute_support

RCPOND_COMPUTE_ALLOCATION_REQUEST_RULES_PATH=/path/to/compute/rules.md
RCPOND_COMPUTE_ALLOCATION_REQUEST_EMAIL_TEMPLATES_DIR=/path/to/compute/templates/

RCPOND_GENERAL_COMPUTE_SUPPORT_RULES_PATH=/path/to/support/rules.md
RCPOND_GENERAL_COMPUTE_SUPPORT_EMAIL_TEMPLATES_DIR=/path/to/support/templates/
```

Workable, but the key names become long, and the existing `RCPOND_RULES_PATH` and `RCPOND_EMAIL_TEMPLATES_DIR` keys would need to be retired or repurposed.

B) Separate config file per ticket type (my preference):

The global default.config keeps shared settings (LLM credentials, ServiceNow auth, URL). Per-type settings live in their own files in a subdirectory:

```
~/.config/rcpond/default.config
~/.config/rcpond/ticket_types/
    compute_allocation_request.config
    general_compute_support.config
```

Each per-type file uses the same simple KEY=VALUE format but only carries the type-specific keys:

```
RCPOND_RULES_PATH=/path/to/compute/rules.md
RCPOND_EMAIL_TEMPLATES_DIR=/path/to/compute/templates/
RCPOND_SERVICENOW_QUERY=assigned_toISEMPTY^short_description=...
```

2. Ergonomic activation — which ticket types are "active"

With the per-file approach, presence of a file activates the ticket type. To stop processing a type, the user removes (or doesn't install) its config file. rcpond-rules installs files for all supported types; the user simply deletes the ones irrelevant to them. No explicit "active types" list to maintain.

For process-next and process-all, rcpond reads all config files in ticket_types/, builds the registry of active types, then fetches tickets matching any of their queries. When a ticket comes back, its `short_description` value selects the right rules/templates automatically — no ambiguity.

3. CLI overrides
For single-ticket commands (display-ticket, process-ticket): the ticket's `short_description` is known after the first API call, so the correct rules/templates are selected automatically. A CLI override isn't really needed in the normal flow.

For multi-ticket commands (process-all, process-next):
These accept a mandatory `--ticket-type <key>` flag (e.g. `--ticket-type compute_allocation_request`). The key must match one of the active ticket types in config; rcpond errors clearly if the key is unrecognised or has no corresponding config file. This is mandatory rather than optional: silently processing all active types in a single batch run risks a user process ticket for which they are not the person primarily responsible. It makes the user's intent explicit in logs and audit trails.

Single-ticket commands (display-ticket, process-ticket) do not need this flag — the correct type is resolved automatically from the ticket's own fields after the first API call.

---

## Q: Directory-per-type (fixed internal structure) vs explicit-paths config file

A variation on option B: each ticket type gets a directory with fixed internal structure (`rules.md` and `email_templates/` hardcoded as subdirectory names). Only the directory path needs to be in config.

**Pros of directory-per-type**

- Simpler config — one path per ticket type instead of two
- Natural bundling — rules and templates travel together; easier to share or version-control a ticket type as a single unit
- Matches the existing rcpond-rules pattern (already installs a directory bundle)
- Self-documenting on the filesystem — open the directory and everything for that type is right there

**Cons of directory-per-type**

- Hidden convention — fixed names (`rules.md`, `email_templates/`) are not visible from the config; users must know the convention
- Less flexible — rules and templates must live inside the designated directory; cannot point at pre-existing files elsewhere without restructuring or symlinking
- Cannot share a `rules.md` across ticket types without duplication or symlinks
- Harder to test with an alternative rules file via CLI — must swap a file inside the directory rather than just pass a different path
- Updating via rcpond-rules overwrites a whole directory, which is riskier than updating individual files

**Pros of explicit-paths config file**

- More flexible — rules and templates can live anywhere
- Explicit — config file shows exactly what is configured
- Can share a `rules.md` between ticket types by pointing both at the same path
- Easy to test with an alternative rules file: change one line or pass `--rules-path` on the CLI
- Consistent with the existing single-type config pattern

**Cons of explicit-paths config file**

- Two paths to configure per ticket type (slightly more verbose)
- Rules and templates can get out of sync if paths are changed independently
- Less self-contained — ticket type config is spread across multiple filesystem locations

**Decision: explicit-paths config file (option B).**

---

## Q: Implementation design decisions for Option A

**1. Should `ComputeAllocationRequestTicket` keep this name?**

Yes. Keep `ComputeAllocationRequestTicket` as the canonical Compute Allocation Request schema name going forward.

**2. How should per-type config filenames be derived?**

Not by slugifying `short_description`. Two problems with that:

- `short_description` is free text on the ServiceNow catalogue item and can be reworded by an admin
  at any time. A filename (and registry key) derived from it would silently orphan the matching
  config file on the next reword, with no error until a ticket of that type next arrives.
- A single `short_description` may in future need to map to *multiple* rcpond ticket types,
  discriminated by an additional field (e.g. `which_service=Azure` vs `which_service=HPC` under the
  same "Request access to HPC and cloud computing facilities" short_description). There is no way to
  slugify one `short_description` value into two distinct, stable filenames.

Instead, each `_TICKET_TYPES` entry is keyed by an arbitrary key chosen once by the developer when
the type is added — never recomputed from ServiceNow data. The `short_description` (and, in future,
any other discriminating field) is stored as `match` data on the entry, not as the key. The same key
is reused as the per-type config filename stem:

```
~/.config/rcpond/ticket_types/compute_allocation_request.config
~/.config/rcpond/ticket_types/general_compute_support.config
~/.config/rcpond/ticket_types/turing_github_org_membership.config
```

and, once a `short_description` needs to split further:

```
~/.config/rcpond/ticket_types/compute_allocation_request_azure.config
~/.config/rcpond/ticket_types/compute_allocation_request_hpc.config
```

This keeps filenames short and stable, and means a `short_description` reword — or a future split
into multiple types — is a change to the matching registry entry, not a file rename plus an update
to everything that pointed at the old filename.

**3. Should the ServiceNow query filter be in the per-type config file?**

Yes. Each per-type config file specifies its own `RCPOND_SERVICENOW_QUERY` (replacing the current hardcoded query in `ServiceNow.get_tickets`). This means adding a new ticket type requires only a new config file and no code changes to the query layer.

Example per-type config file:

```
RCPOND_RULES_PATH=/path/to/compute_allocation/rules.md
RCPOND_EMAIL_TEMPLATES_DIR=/path/to/compute_allocation/templates/
RCPOND_SERVICENOW_QUERY=assigned_toISEMPTY^short_description=Request access to HPC and cloud computing facilities
```

## Other Notes

* It is possible that a ServiceNow query could return multiple ticket types if the filters are not mutually exclusive.
* RCPond should always assert that a newly read/retrieved ticket is of the type expected, and not rely on the query to be completely correct. RCPond should evaluate each `_TICKET_TYPES` entry's `match` criteria against the ticket's own fields to determine which type it is and select the rules/templates accordingly. Still need to decide how to handle a ticket that matches no active type in config.
* `RCPOND_SERVICENOW_QUERY` (which tickets get fetched) and a registry entry's `match` criteria (how a fetched ticket is dispatched) express overlapping intent independently and could drift out of sync — e.g. a query broadened to fetch more tickets without updating `match` to discriminate them. Not a blocker for the single-field (`short_description`-only) case, but worth keeping in mind once `match` grows additional fields.
* `get_tickets()` will later gain a `TicketState` parameter (from the `combine-ticket-history` feature) to support fetching closed, resolved, and cancelled tickets. The function signature should be designed to accommodate this as an orthogonal parameter alongside the per-type query system — state filtering and type filtering are independent concerns.
* The `_TICKET_TYPES` registry (or per-type config) should support declaring which ticket type combinations are considered potentially related, for use by the `find_related` subcommand (from the `combine-ticket-history` feature). Some combinations will never have related tickets (e.g. a GitHub organisation membership ticket and a compute allocation request) and this can be used as a cheap pre-filter before the more expensive field-matching heuristics are applied.

## Threading ticket-type into all layers of RCPond

Surfaced on 2026-09-21 by this, which fails:

```bash
(set -a; source .env; set +a; XDG_CONFIG_HOME="$PWD/example_config_dir" rcpond login)
ValueError: Missing required configuration: rules_path, email_templates_dir
```

Once `rules_path` and `email_templates_dir` live *only* in per-type config files — which
is the point of the feature — every command that cannot reach a per-type config breaks,
including commands that have no need to read the rules or templates at all.

### Two distinct problems

**1. `Config` validates every field for every command.**

`login` needs only the auth settings, but `rules_path` and `email_templates_dir` are
unconditionally required. They can now only come from the per-type loader, which runs
only when `ticket_type` is set, and `login` has no `--ticket-type`. So validation fails
on two values `login` would never read.

**2. Per-type config is wired into only 2 of 12 subcommands.**

| Takes `--ticket-type` | Does not |
|---|---|
| `process-next`, `process-all` | `login`, `whoami`, `display-all`, `display-ticket`, `browse-ticket`, **`process-ticket`**, `evaluate-all`, `find-related`, `analytics`, `check-templates` |

`process-ticket` is the one to note: it runs the LLM, so it genuinely needs rules and
templates, yet it cannot load them from a per-type config either. `check-templates` is
similar — it exists to validate template directories but cannot see the per-type ones.

### Commands fall into three groups

Worth settling this taxonomy before writing code, because it determines what
`--ticket-type` should *mean* per command.

Two independent axes matter, and conflating them is what produced the `rcpond login`
failure above:

- **Type scope** — how many ticket types are in play (the groups below).
- **Needs rules/templates** — whether the command reads rules or templates at all. This
  does *not* follow from the group.

`rules_path` and `system_prompt_template_path` are read only by `prompt.py`;
`email_templates_dir` only by `PostTemplatedNoteTool`. Everything else never touches them.

| Group | Commands | Needs rules/templates | Type scope |
|---|---|---|---|
| **A. Needs neither** | `login`, `whoami` | No | None. A `--ticket-type` switch would be meaningless and would confuse users. |
| **B. One type per invocation** | `process-next`, `process-all`, `process-ticket`, `display-all`, `display-ticket`, `browse-ticket`, `find-related` | `process-*` yes; the rest no | Exactly one type. `--ticket-type` selects it, **defaulting to `compute_allocation_request`**. |
| **C. All types, always** | `check-templates` | Templates only | Every configured type; no switch. Deliberately the one command that seeks out other types without being asked. |

Two commands sit outside the taxonomy for now — see "Deferred: the genuinely cross-type
commands" below.

So "thread `--ticket-type` through every command" is the wrong goal. The goal is:

- **A**: stop requiring rules or templates at all.
- **B**: accept `--ticket-type`, defaulted; load that one per-type config.
- **C**: enumerate every configured type.

`find-related` belongs in B despite first appearances. Its input is one ticket and its
output is many, but the candidates come from `get_tickets(all_including_closed)` filtered
by the per-type `servicenow_query`, so the results are always the input ticket's type.
Cross-type relations are a *future* possibility — what the "Other Notes" bullet about
declaring relatable type combinations anticipates.

### Why there is no "mixed types" group

An earlier draft had a fourth group for commands whose result set may span types
(`display-all`, `analytics`, `evaluate-all`), narrowed by a repeatable
`--include-ticket-type` filter defaulting to all types. That group has been **eliminated**,
and with it the second flag. Two moves did it:

**`display-all` becomes group B.** Restricting it to a single type is not a loss: it makes
`display-all` show exactly the set that `process-all` would act on. Under the mixed-type
design the two would have disagreed, so a user could see tickets that the very next
command would refuse to touch. One flag, one meaning, and the `MATCH_CRITERIA` guard
applies to it for free.

**`analytics` and `evaluate-all` are deferred**, not redesigned (below).

This removes a substantial amount of machinery that was being introduced for a single
command: a second CLI flag whose default was the *inverse* of `--ticket-type`'s, a
per-ticket filtering path through `get_tickets`, and the risk — noted in the earlier
draft — that a later "consistency" tidy-up would unify the two flags and silently narrow
`analytics` to one type. None of that has to exist.

The rejected design is preserved here because the reasoning still applies if a genuinely
cross-type command is ever needed:

> Groups B and C both narrow by ticket type, but with **opposite defaults and different
> arity** — B defaults to one named type and takes exactly one; C defaulted to all types
> and took zero or more. Giving both the name `--ticket-type` would mean the same flag
> meaning opposite things depending on the command, undiscoverable from the name. Hence
> `--include-ticket-type`: repeatable, obviously a filter, emphasising inclusion and
> leaving room for a future `--exclude-ticket-type`.

### Deferred: the genuinely cross-type commands

**`analytics`** is the one command that is cross-type by nature: it already groups by
`ticket_type_key(ticket)`, derived per ticket rather than from config, and reports per
type. Forcing it into group B would make it report on one type and quietly lose that.

It remains **broken** under a per-type-only config, failing with
`Missing required configuration: rules_path, email_templates_dir`.

Note this is *not* a ticket-type problem. `analytics` reads no rules and no templates, so
the one-line fix is `require_rules_and_templates=False` at its `_config(ctx, ...)` call
site — the same treatment as `login` and `whoami`, for the same reason. No per-type
config, no filter switch and no `per_type` mapping are needed to unbreak it. Accepted as
broken for now by explicit decision, but the cost of fixing it is one line, not a feature.

**`evaluate-all`** is doubly exceptional and its future is undecided. Its tickets come
from **local HTML files, not a ServiceNow query**, so the query-ordering problem below
does not apply to it. It is also **conditionally registered** (inside
`try: import rcpond.html_servicenow`, the `html` extra), so it is absent from the CLI
unless that dependency group is installed. It does need rules and templates, so unlike
`analytics` it cannot be unbroken with a one-line change. Acceptable that it remains
unable to handle multiple ticket types at this stage.

### Why inference is deferred

Group B's long-term ideal is to infer a single ticket's type from the ticket itself rather
than from a flag or default. That is not currently possible, and the reason is worth
recording so it is not rediscovered:

`get_ticket()` locates a ticket by filtering `get_tickets(all_including_closed)` through
`self._query` (`servicenow.py`), and `servicenow_query` comes from the **per-type**
config. So the type is needed in order to fetch the ticket whose type was to be inferred.

Escaping this needs either a type-agnostic query for single-ticket lookup, or the union of
all configured types' queries — which is another argument for `Config` knowing about every
configured type (C-i below).

### Guarding the default

A fixed default is good ergonomics but has one real hazard: a user working on a different
ticket type silently gets `compute_allocation_request` rules and templates applied, with
no error.

Because `ticket_type_key()` already derives a ticket's type from its own fields, this is
cheap to close — and it serves the fail-early preference directly:

> When the ticket type came from the **default** rather than an explicit `--ticket-type`,
> assert that each fetched ticket actually satisfies that type's `MATCH_CRITERIA`, and
> fail if it does not.

**Decided:** an explicit `--ticket-type` is subject to the same check. Applying it
everywhere is more consistent and catches a mistyped flag, and there is no use case for
deliberately applying one type's rules to another type's ticket.

### Group C needs per-type config loadable for every type

Today the per-type file is read once, inside `Config.__post_init__`, and flattened into
`config.rules_path` / `config.email_templates_dir` — a single type's values on a single
object. Group C (`check-templates`) needs every configured type's values simultaneously,
which that shape cannot express.

With the mixed-types group eliminated, `check-templates` is now the **only** driver for
this work: nothing else needs more than one type's config at a time. It stays accepted —
validating templates for just one type is not much of a check — but it is no longer
blocking anything else, and could reasonably be scheduled after the rest.

Options:

- Accepted **C-i. `Config` holds a mapping.** `config.per_type: dict[str, PerTypeConfig]`, keyed
  by registry key, populated for every `.config` file present in
  `$XDG_CONFIG_HOME/rcpond/ticket_types/`. Group B selects one entry; `check-templates`
  iterates all. Flat `rules_path` becomes a convenience accessor for group B, or goes away.
- Rejected **C-ii. Lazy per-type loader.** `config.for_ticket_type(key) -> PerTypeConfig`, reading
  and caching on demand. Smaller change, but errors surface late and are harder to
  report up front.
- Rejected **C-iii. Leave `check-templates` unable to reach per-type config.** It would
  then validate only the default type's templates, silently passing a deployment whose
  other types' templates are broken — the opposite of what the command exists to do.

C-i is accepted: it makes "which types are configured on this host" an explicit,
inspectable fact, gives `check-templates` something to iterate over, and lets an
unknown-type ticket be detected at startup rather than mid-run.

Two consequences, both decided:

- **All consumers move to the mapping.** The flat `config.rules_path` and
  `config.email_templates_dir` attributes do not survive as group B conveniences —
  keeping both shapes would let them drift. `prompt.py` and `PostTemplatedNoteTool` take
  a `PerTypeConfig` (or the key to look up) instead.
- **A ticket matching no registered type aborts the run.** It is not skipped with a
  warning. A ticket RCPond cannot classify is a configuration or query error, and
  skipping would silently under-process a batch — the failure mode hardest to notice.
  This also settles the question left open in "Other Notes" above.

### Immediate fix for problem 1

Independent of the above, and unblocks `rcpond login` today:

```python
## config.py — InitVar, defaulting to today's strict behaviour
def __post_init__(self, env_path, cli_args, require_rules_and_templates=True):
    ...
    ## login/whoami authenticate only; they never read rules or templates
    if not require_rules_and_templates:
        optional |= {"rules_path", "email_templates_dir", "system_prompt_template_path"}
```

with `_config(ctx, require_rules_and_templates=False)` in `login` and `whoami`, and the Jinja
template validation skipped on that path.

**Decided:** the `InitVar` above, rather than a separate narrower `AuthConfig` object for
group A. The `InitVar` is a contained change that keeps one config type; an `AuthConfig`
would be cleaner in principle but is a much larger refactor for two commands.

Note this is **complementary to the default ticket type, not an alternative to it.** A
default would incidentally make `rcpond login` work, because per-type config would always
load and would always supply `rules_path`. But that fixes the symptom: `login` would still
*require* a `compute_allocation_request.config` to exist in order to authenticate, for
values it never reads. Fail-early validation earns its keep when what is validated is
genuinely needed; validating a superset is not early failure but false failure — which is
exactly the bug being fixed here. Do both.

Rejected alternatives:

- **Give `login` a `--ticket-type`.** Semantically wrong: authenticating has no ticket
  type, and it would train users to pass a meaningless flag.
- **Auto-default to whichever type happens to be registered, when only one is.** Silently
  changes behaviour the moment a second type is registered — exactly the transition this
  feature is meant to make safe. Note this objection does *not* apply to a **fixed,
  named** default of `compute_allocation_request`: that is stable, visible in `--help`,
  and unaffected by new registrations. The named default is adopted above.
- **Make `rules_path` / `email_templates_dir` optional for everyone, validated at point
  of use.** Defers errors from startup to mid-run, and worsens the failure mode for the
  process commands, which are the ones that actually need these values.

### Open questions

Settled during review, and folded into the sections above:

| Question | Decision |
|---|---|
| Name for a mixed-types filter switch | Moot — the mixed-types group was eliminated, so no second flag is needed. The `--include-ticket-type` reasoning is preserved above in case one is ever required. |
| Does explicit `--ticket-type` skip the `MATCH_CRITERIA` check? | No — the check applies either way |
| Ticket matching no registered type | Abort the run; do not skip with a warning |
| `require_rules_and_templates` mechanism | `Config` `InitVar`, not a separate `AuthConfig` |
| Flat `rules_path` vs `per_type` mapping | Move all consumers to the mapping |
| Does `find-related` span types? | No — candidates come from the per-type query, so results are always the input ticket's type. Cleanly group B. |

### Where each command declares whether it needs rules or templates

**Decided: at the call site.** A command that does not need rules or templates passes
`require_rules_and_templates=False` in its own `_config(ctx, ...)` call. No central table in
`cli.py` — that would duplicate the command list and fall out of step with it.

Note this cannot be derived from the group: group B is mixed, since `process-*` reads rules
and templates while `display-all`, `display-ticket`, `browse-ticket` and `find-related` do
not. It has to be stated per command.

The arrangement fails safe. `require_rules_and_templates` defaults to `True`, so a new command
whose author forgets to declare it gets today's over-strict validation — a loud, spurious
"missing configuration" error rather than silently skipped validation.

### Which commands get the flag

Under a per-type-only config (rules and templates declared *only* in
`ticket_types/*.config`), every command that cannot reach a per-type config fails
identically today. Confirmed by running each against an environment with no
`RCPOND_RULES_PATH` or `RCPOND_EMAIL_TEMPLATES_DIR`:

```
rcpond login                 -> ValueError: Missing required configuration: rules_path, email_templates_dir
rcpond whoami                -> ValueError: Missing required configuration: rules_path, email_templates_dir
rcpond display-all           -> ValueError: Missing required configuration: rules_path, email_templates_dir
rcpond analytics             -> ValueError: Missing required configuration: rules_path, email_templates_dir
rcpond browse-ticket RES0001 -> ValueError: Missing required configuration: rules_path, email_templates_dir
```

So seven commands read neither rules nor templates: `login`, `whoami`, `display-all`,
`display-ticket`, `browse-ticket`, `find-related`, `analytics`.

**Decided: `login` and `whoami` only.** They will *never* need rules or templates, so
exempting them is permanent and correct.

Of the other five, four are now resolved a different way: `display-all`, `display-ticket`,
`browse-ticket` and `find-related` joined group B and take `--ticket-type`, so they reach
a per-type config and no longer fail. Exempting them would have been the wrong fix — they
need a ticket type for the *query*, not just for rules and templates.

`analytics` is the exception and stays broken by decision. Unlike the other four it is
cross-type by nature, so `--ticket-type` is not the right answer for it; unlike
`process-*` it reads no rules or templates. It is therefore the one command for which the
`require_rules_and_templates=False` exemption *would* be the correct permanent fix — a
one-line change, deferred rather than ruled out. See "Deferred: the genuinely cross-type
commands" above.

