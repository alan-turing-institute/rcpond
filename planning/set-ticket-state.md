# Set ticket state

Add a method to `ServiceNow` that changes a ticket's `state` on the ServiceNow instance, not
just on the local `Ticket` object.

Build this incrementally. Steps 1–3 are the deliverable; Step 6 is recorded but deliberately
not actioned.

## Decisions

| Question | Decision |
|---|---|
| How the caller names the state | A new `SettableState` enum. The existing `TicketState` is renamed `TicketStateFilter`. |
| Permitted target states | Exactly `In Progress`, `On Hold`, `Resolved`. |
| LLM tool | Not now. Written up as Step 6, not implemented. |
| Validation | Pre-validate, PATCH, re-read to confirm. No write-then-revert. |
| Permitted *source* states | Anything except `Closed`. A `Closed` ticket is refused. |
| Work note | None from `set_state`. Required of the Step 6 tool wrapper. |

The permitted set is **not** the full list of states the field can hold. It is the set an
operator can select in the ServiceNow WebUI; the rest (`New`, `Closed`, `Cancelled`) are
driven by the ServiceNow system itself. RCPond should not be able to put a ticket into a
state a human operator could not.

The same principle governs the *source* state. In the WebUI a `Closed` ticket cannot be
changed at all, while a ticket in any other state can be. `Closed` is never chosen by a
person in either direction: a `Resolved` ticket is moved to `Closed` automatically by
ServiceNow about a week later. RCPond matches that — it refuses to touch a `Closed` ticket
and will act on anything else.

### `Ticket.is_closed` is the wrong guard — do not use it

`is_closed` tests membership of `_CLOSED_TICKET_STATES`, which is
`{"Closed", "Resolved", "Cancelled"}`. Using it here would refuse `Resolved` and `Cancelled`
tickets, which the WebUI lets an operator change. The guard is specifically
`state == "Closed"`.

The two concepts are genuinely different and both are correct in their own place.
`is_closed` means *terminal* — immutable for analytics, with a knowable resolution time.
What is needed here is *uneditable*, which is a narrower thing. The names are close enough
that someone will reach for `is_closed` by reflex, so the distinction should be stated in the
`set_state` docstring, not just here.

## Assumption to be tested first: how ServiceNow accepts a state write

**This is the one genuine unknown and Step 0 exists to settle it before anything else is
built.**

Everything RCPond reads today comes back as a *display value* — `get_tickets` and
`get_full_ticket` both pass `sysparm_display_value`, so `Ticket.state` holds `"In Progress"`,
not the integer behind it. The dump of 731 production tickets contains exactly four labels:
`Closed` (494), `In Progress` (225), `On Hold` (10), `Resolved` (2).

Writing is not symmetrical. `state` on `x_tati_resmgt_research` is a choice field, and a
PATCH ordinarily expects the *backing value* (conventionally an integer), not the label.
So `{"state": "In Progress"}` may:

- be accepted and do the right thing,
- be rejected with an error, or
- **be accepted and silently do nothing** — the dangerous case, because the request returns
  200 and only a re-read reveals the state never moved.

The third outcome is why Step 3 re-reads after writing regardless of what Step 0 concludes.

Two ways to make the write deterministic:

1. **`sysparm_input_display_value=true`** on the PATCH, so ServiceNow resolves the label
   server-side. Keeps labels as the only vocabulary in the codebase, consistent with every
   read. Preferred if it works.
2. **An explicit label → backing-value map** in `SettableState`, e.g. `in_progress = ("In Progress", 2)`.
   Removes the ambiguity entirely but hard-codes instance configuration into the source,
   where it will drift silently if the choice list is ever edited.

### Step 0 — spike on the Dev instance

A throwaway script in `scripts/` (same treatment as `scripts/time_full_ticket_dump.py`:
reuse the rcpond package, delete once settled). Against the Dev instance only, on a ticket
created or chosen for the purpose, it should:

- read the raw choice list for `state` (`sys_choice` filtered to this table and field), to
  recover the backing values and confirm the label set;
- PATCH `{"state": "<label>"}` with and without `sysparm_input_display_value=true`, re-reading
  after each to record whether the state actually moved;
- attempt `Resolved` specifically, and record whether mandatory close fields
  (`close_code`, `close_notes`, or scoped equivalents) block it;
- attempt a write to a `Closed` ticket, to learn whether the instance rejects it outright or
  accepts-and-ignores. RCPond refuses these before writing either way, so this does not change
  the design — but it tells us whether the guard is defence in depth or the only thing
  standing between a caller and a silent no-op.

The result decides option 1 vs option 2 and resolves the open question about `Resolved` below.
**Do not write to production while establishing this.**

## Step 1 — rename `TicketState` to `TicketStateFilter`

`TicketState` controls *which tickets `get_tickets` returns* — it is a filter, with members
`user_focus`, `all_open`, `all_including_closed`. None of those is a ticket state, so the name
is a misnomer independently of anything in this document.

**This step is now optional — decide before starting it.** The rename was agreed when the new
enum was to be called `State`, where the clash was intolerable: `State` and `TicketState`
sitting side by side, meaning unrelated things. `SettableState` does not collide in the same
way, and the two names can coexist without misleading a reader. What remains is the original
misnomer, which is worth fixing but no longer *blocks* this work.

So there are two routes:

- **Keep it here.** One coherent commit series, and the confusing name goes away while this
  area is already being read closely.
- **Drop it from this work.** Removes a 57-reference breaking rename, a deprecation alias and
  a changelog entry from the critical path. `set_state` and `SettableState` do not depend on
  it. The rename becomes its own small piece of work whenever convenient.

The steps below assume it is kept. If dropped, Step 5's `Changed` entry goes with it.

- 57 references across `src/`, `tests/`, `scripts/` and `planning/`. Files touched:
  `servicenow.py`, `command.py`, `cli.py`, `analytics.py`, `html_servicenow.py`,
  `test_servicenow.py`, `test_command.py`, `test_analytics.py`, `test_dump_tickets.py`,
  `scripts/time_full_ticket_dump.py`.
- Nothing in `docs/` names it directly; the API page renders from docstrings, so the rename
  propagates on its own.
- Keep a backward-compatibility alias following the existing `FullTicket` precedent in
  `servicenow.__getattr__`: return `TicketStateFilter` for `TicketState` with a
  `DeprecationWarning`, and add it to `__dir__`.
- Because `pyproject.toml` sets `filterwarnings = ["error"]`, any internal reference left
  behind fails the suite rather than passing quietly. That is the check that the rename is
  complete — no separate test needed for it.

## Step 2 — the `SettableState` enum

The name is deliberately specific. A bare `State` would read as "the states a ticket can be
in", which is a wider set than this enum holds and would invite someone to reach for it when
inspecting `Ticket.state`. `SettableState` pairs with `set_state()` at the call site and says
what the type is for: the states RCPond is permitted to *set*.

```python
class SettableState(Enum):
    """A ticket state RCPond is permitted to set.

    >>> sn.set_state(tkt, SettableState.on_hold)
    """

    in_progress = "In Progress"
    on_hold = "On Hold"
    resolved = "Resolved"
```

Members are limited to the three permitted states, so the enum *is* the validation — there is
no separate allow-list to drift out of step with it. States RCPond must never set are
deliberately absent rather than present-but-rejected.

Note the asymmetry this creates, which is intended: `Ticket.state` can hold `"Closed"` or
`"New"` (both occur in real data), but `SettableState` cannot express them. It is the
vocabulary of *writes*, not of reads. The name carries most of that message; the docstring
should still say it outright.

If Step 0 selects the backing-value option, members become `("In Progress", 2)` tuples with a
`label` and `value` property; the public call signature does not change either way.

## Step 3 — `ServiceNow.set_state()`

```python
def set_state(self, ticket: Ticket, state: SettableState) -> str:
    """Set the ticket's state on the ServiceNow instance."""
```

Sequence:

1. **Validate the argument before any request.** Reject a non-`SettableState` argument with
   `TypeError`. A plain string is *not* silently coerced — accepting `"In Progress"` would
   reintroduce exactly the typo class the enum exists to prevent.
2. **Read the current state** via `_fetch_fields(ticket.sys_id, {"state"})`.
3. **Refuse a `Closed` ticket.** If the state just read is `"Closed"`, raise `ValueError`
   naming the ticket, without attempting the write. Any other current state proceeds.
4. **PATCH** `{"state": ...}` to `{base}/{_TABLE}/{ticket.sys_id}`, in the shape Step 0
   established. `raise_for_status()`.
5. **Re-read** the state the same way.
6. **Compare.** If the re-read label is not the requested one, raise `RuntimeError` naming
   the ticket, the requested state and what was found. This is the guard against the
   silent-no-op case, and the reason a post-write read is not optional.
7. **Update the local object** — `ticket.state = <confirmed label>` — so the in-memory ticket
   matches the instance, as `assign_to` does with `assigned_to` at the end of its own flow.
8. **Return** the confirmed state label.

### Why the guard reads rather than trusting `ticket.state`

Checking the passed-in `Ticket` would be free, but ServiceNow moves `Resolved` tickets to
`Closed` on its own about a week after resolution. A `Ticket` object held across that
boundary — fetched in a batch run, read from a dump, or simply held for a while — can say
`Resolved` when the instance says `Closed`. The guard would then pass on stale data and
RCPond would attempt a write the WebUI forbids.

The failure is not silent: step 6 would catch it and raise. But it would surface as a
confusing "state did not change" after a pointless write, rather than the accurate "this
ticket is Closed". One extra GET buys the correct refusal and the right error message, and
it also supplies the original state for that message. Steps 2 and 5 use the same helper, so
this is one more call of a method the flow already makes.

No revert on failure. `assign_to` reverts because it can write an assignee ServiceNow does not
recognise and must undo it; here the enum makes an invalid value unreachable, so a failure
means the instance rejected or ignored a *valid* request. Writing again in response would add
a second confusing entry to the ticket's Activity log without fixing anything.

### Naming

`set_state` reads consistently with `assign_to` / `post_note` (verb-first, no `update_`
prefix anywhere in the class). Alternative `update_state` noted; not preferred.

### Work note on a state change

**`set_state` itself posts no work note.** It does one thing, and a caller that wants the
change annotated already has `post_note`.

Attribution is still required, just not here. Every other mutation RCPond makes is traceable
through `_note_prefix`; a bare state change is attributable only to the acting account, which
for Client Credentials is a shared service account. **The tool wrapper in Step 6 must
therefore post a work note or equivalent** — that is a requirement on Step 6, not an option.
Its details are out of scope for this plan.

Note the consequence for ordering: a wrapper that writes the note and then the state can
leave a note describing a change that never happened, if the state write fails. Step 6 should
set the state first and note it afterwards. Recording it here so the constraint is not
rediscovered later.

## Step 4 — tests

Unit tests, written first, mocking the session as the existing `find_related` tests do:

- each of the three permitted states PATCHes the expected body to the expected URL;
- a non-`SettableState` argument (`"In Progress"`, `None`, an int) raises `TypeError` **and
  sends no request** — assert the session was not called, not merely that it raised;
- a ticket whose current state reads `"Closed"` raises `ValueError` and **sends no PATCH**;
- a ticket whose current state reads `"Resolved"`, and separately `"Cancelled"`, is accepted
  and does PATCH — these are the cases `is_closed` would wrongly have refused, so they are
  the tests that stop someone "simplifying" the guard into `ticket.is_closed` later;
- a stale `Ticket` carrying `state="Resolved"` whose instance state reads `"Closed"` is
  refused — the guard uses the freshly read value, not the attribute;
- a re-read returning a different state raises `RuntimeError` and the message names the ticket;
- a re-read returning the requested state updates `ticket.state` and returns the label;
- a non-2xx PATCH propagates and leaves `ticket.state` untouched;
- `SettableState` has exactly the three permitted members — a test that fails if someone adds
  `closed` without revisiting this document.

One integration test marked `@pytest.mark.integration()` against Dev, following
`test_change_assignee`: read a ticket's state, move it to `On Hold`, confirm, restore the
original. It must restore even on failure, or it will leave Dev tickets parked.

## Step 5 — docs and changelog

- `ServiceNow` docstrings carry the API docs (`docs/api.md` renders from them), so `set_state`
  and `SettableState` need full NumPy-style Parameters/Returns/Raises sections.
- The module docstring at the top of `servicenow.py` lists the public API and must gain
  `set_state`.
- `CHANGELOG.md` under `## [Unreleased]`: `Added` for `set_state` and `SettableState`; `Changed` for
  the `TicketState` → `TicketStateFilter` rename, naming the deprecation alias. The rename is
  user-visible for anyone importing it.

## Step 6 — LLM tool (recorded, not actioned)

Exposing `set_state` through `tools.py` would let the model move tickets autonomously during
`process-all`. That is a product decision, not a mechanical extension, and is deliberately out
of scope here. If taken up it needs: a `Tool` definition, an `_IMPLEMENTATIONS` entry taking
`(service_now, ticket, **kwargs)`, `dry_run` handling matching the other tools, a decision on
whether the model may set `Resolved` at all, and — **required, not optional** — a work note
for attribution, written after the state change rather than before it. See "Work note on a
state change" under Step 3.

The tool schema is generated from the signature by introspection, so the model would see
`SettableState` and its three members as the parameter's allowed values. That is a further
argument for the specific name: it is part of the prompt surface, not just the source.

## Open question

1. **Does `Resolved` succeed without close fields?**

   This is a question about how the instance is configured, not about what anyone wants.
   Step 0 answers it by experiment on Dev; no decision is needed beforehand.

   Each outcome may then raise a decision:

   - **Blocked by mandatory close fields.** `set_state` cannot set `Resolved` with its
     current signature. Choose: extend the signature to accept `close_code`/`close_notes`,
     or drop `Resolved` from `SettableState` and handle resolution as separate work.
   - **Succeeds.** *Succeeds* is not *should*. If the instance permits resolving a ticket
     with no close notes, it is still a workflow judgement whether RCPond ought to. Worth
     a moment's thought rather than adopting the permissive behaviour by default.
That is the only one left. Two earlier questions are now settled and recorded in place:

- *Whether to refuse an already-terminal ticket.* RCPond matches the WebUI — only `Closed` is
  refused, and the guard is `state == "Closed"`, not `Ticket.is_closed`.
- *Whether a state change posts a work note.* Not from `set_state`; required of the Step 6
  tool wrapper.
