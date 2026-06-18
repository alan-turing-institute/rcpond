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
These should only operate on tickets of the same type as this reflected the users likely intention when call ing a batch command. The unanswered question is if and how the user can specify which type they want to operate on if they have multiple active types.

The design of the override options depends on how the ticket type is identified.

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
