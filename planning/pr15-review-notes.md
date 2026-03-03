# General comments:

From asmith:

As far as I know, something we've not explicitly discussed anywhere is that, once complete, the command `rcpond` should be idempotent. Whilst the functionality is limited to triaging tickets, each ticket should be processed at most once.

Instinctively, I feel this behaviour should be enforced primarily within the servicenow module. This is implicitly handled by:
Only collect unassigned tickets
Assign a ticket to a person before acting on it, so that it can't be retrieved again.

Is that correct? If so, it would be worth adding an explicit description in the module docs. What is the intended workflow? Something like:
```
sn = ServiceNow()
tickets = sn.get_unassigned_tickets()
for ticket in tickets:
	full_ticket = sn.get_full_ticket(ticket)
	sn.assign_myself(ticket)
	# Do LLM stuff
	...
	sn.post_note(ticket, "Do next thing....")
```

Are we sure about the initial status of the tickets being triaged? Could there be cases where a ticket has been assigned manually, but not triaged (i.e., the first action has not been decided)?

Do we need to worry about race conditions? What if two people executed `respond` simultaneously? (Maybe too much of an edge case?)

Are we sure that a "worknote" (rather than a "comment"),  is the appropriate next step? A comment is a slightly separate thing in ServiceNow.

Arguably, `post_note` and `assign_myself` could be methods of `Ticket`, rather than `ServiceNow`. Is this just because it is more convenient to access ServiceNow properties this way?

It would be helpful to have some tests, in the broadest sense. These could be pytest tests, or just the curl commands the code is attempting to replicate, or the json responses from ServiceNow saved to file.


# Specific comments:

By file and line number:

`servicenow.py`

Line 172:
Explicitly create a list from the set of extra_fields
```
return FullTicket.from_Ticket(tkt, **_extract_ticket_fields(result, list(extra_fields)))
```

Line 115:
Suggest using `config.servicenow_url` rather than hardcoding the value.

Line 119:
Pass a `Config` rather than the token as a string:
```
def __init__(self, config: Config):
```

Line 194:
Linting tools are your friends 🙂

`pyproject.toml`

I'm not sure what's happen here, but we have two definitions of the `dev` optional dependency group, which causes the second one to overwrite the first. These should be merged.

```
[project.optional-dependencies]
dev = [
  "pytest >=6",
  "pytest-cov >=3",
  "pre-commit",
]
```

```
[dependency-groups]
dev = [
    "pdoc>=16.0.0",
]
```

More significantly, we should workout the chain of events that caused this (eg `$ history | grep pdoc`) and make sure we understand how to avoid it in future.

**Note: The requirement for `pdoc` may or may not be superseded by PR17, but we should still make sure to merge the two dev groups, and understand how this happened

