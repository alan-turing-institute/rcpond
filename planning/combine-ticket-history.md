
# Combining information from multiple related tickets

## Background

Some projects run for multiple years. During this time there may be multiple tickets created for the same project, as either the needs change or the project spans multiple financial planning periods.

It would be helpful to combine the history of these tickets when reviewing cases, so that we can see the full context of the project and any decisions that have been made in the past.

Possible means to identify related tickets could include properties such as:
* references to other ticket numbers, (extracted from the text fields of the current ticket, via regex => exact match on other ticket numbers)
* tickets with the same or very similar project titles. (matching on the `project_title` fields on all tickets. note that the project title of all tickets is known, and so this knowledge can be used to identify distance metrics between the titles of all tickets, and identify those that are similar)
* tickets with the same project/finance code, (extracted from the text fields of the current ticket => exact match on other `which_finance_code` of other tickets)
* references to the same Azure subscription ID.  (Azure subscription ID can be extracted from the text fields of the current ticket, via regex => find exact match in the text fields of other tickets. Use the `azure_subscription_id_or_hpc_group_project_id` field if available, but the value might be anywhere in the text fields of the ticket)
* tickets from the same user, same principal investigator, or similar project team (match on email address fields)

Initially any match is sufficient. At present we do not have an authoritative way to identify related tickets. We will need to be able to adjust these heuristics over time based on user feedback.

The relevant previous tickets may include "Closed", "Resolved", "Cancelled" states.


# Functional changes

* If the ticket being processed has references to other tickets and past decisions, then RCPond should find those related tickets and consider the whole history of the project when generating a response.
* There should be a new subcommand (`find_related`) which, given an ticket number, lists the related tickets and their status. This can be used to verify that the heuristics are working as expected, and to allow users to provide feedback on which related tickets that are found.


## Implementation

1. Adjust `ServiceNow.get_tickets` so that it can return all tickets, including tickets that are in "Closed", "Resolved", or "Cancelled" states. Potentially, replace the existing `long_list` parameter with an enum, including options `user_focus`, `all_open`, and `all_including_closed`. This will allow the tool to retrieve all tickets, including those that are closed or resolved, which is necessary for combining ticket history. The ticket filtering logic can be applied locally after the tickets are retrieved, rather than by adjusting the query to the ServiceNow API.

Also update `get_ticket()` (single-ticket lookup by number) to search across all ticket states, not just open ones — ticket numbers extracted from text fields may reference closed or resolved tickets.

One or more functions should be added to `ServiceNow` to allow for filtering tickets based on the heuristics described above.

Note: if `multiple-ticket-types` is implemented before this PR, `get_tickets()` will already use per-type queries. The `TicketState` parameter should be added as an orthogonal parameter on top of that system — it controls state filtering, not type filtering. Note that the base `Ticket` dataclass does not contain enough fields to apply any of the heuristics — all candidate tickets must be loaded as full `ComputeAllocationRequestTicket` objects via `get_full_ticket()` before filtering can take place. This will be slow for large ticket volumes; the implementation should log a warning or progress indicator when fetching a large number of full tickets.

2. Create a new Tool, `CombineTicketHistory`, in `tools.py` that:
   1. Finds historical tickets related to the current ticket. This requires loading all tickets as full objects: `[service_now.get_full_ticket(t) for t in service_now.get_tickets(state=TicketState.all_including_closed)]`, then filtering using the heuristics above.
   2. Creates a combined project-wide history deterministically: concatenate the key fields and work note history from each related ticket into a structured per-ticket block. LLM summarisation is not used here — the audit requirement in step 2.3 requires that source material is fully preserved and traceable.
   3. The combined history should be posted to the current ticket's work_notes as an audit note. The format should be a block per related ticket containing its number, state, opened date, project title, and full work note history. This must be readable by a future LLM call, but also comprehensible by a technically-capable human. It must include references to the related tickets and their ticket numbers.
   4. Re-prompts the LLM with the combined history. This will require reworking of the `_process_ticket` function and the `Tool.execute` function to allow for re-prompting the LLM with new information. (See below for more details.)


3. Add a `find_related` CLI subcommand. Given a ticket number, it calls `ServiceNow.find_related_tickets()` and prints each matched ticket's number, state, type, and which heuristic matched (e.g. "matched on finance code: `TUR-2023-001`"). This allows the matching logic to be verified and tuned independently of the full processing pipeline.

`find_related` must search across all active ticket types (using the multi-type query system from `multiple-ticket-types`). The ticket type of the current ticket and each candidate ticket is itself an additional heuristic: some type combinations will never have related tickets (e.g. a GitHub organisation membership ticket is unlikely to be related to a compute allocation request). Allowed type combinations should be configurable and applied as a cheap pre-filter before the more expensive field-matching heuristics.

The system prompt may be adjusted to steer the LLM to look for indications of related tickets and call `CombineTicketHistory` if it finds any.

The `_note_prefix()` function should be extended to include the name of the tool that generated the note, using the format:

`[code]<b>RCPond v{version} [{tool_name}] generated response:</b>[/code]`

For `PostTemplatedNoteTool`, `tool_name` includes the template name, e.g. `post_templated_note:approval_email.yaml.j2`. For other tools, `tool_name` is the tool's name (e.g. `post_freeform_note`, `combine_ticket_history`). This format is shared with the analytics feature, which uses the template name to classify outcomes.

This allows `_should_skip` to distinguish audit notes posted by `CombineTicketHistory` from final-response notes: a ticket should not be skipped if the most recent RCPond note is a `CombineTicketHistory` audit note, since the expected follow-up response has not yet been posted.


## possible interaction of Tool.execute and _process_ticket

There are two possible ways to implement the interaction between Tool.execute and _process_ticket:

A. Structured heirarchy of calls:

* _process_ticket is called with a ticket number, and retrieves the ticket information from ServiceNow. The LLM call identifies that the ticket is related to other tickets, and calls the CombineTicketHistory tool. 
* CombineTicketHistory.execute() method contains three steps:
  * Retrieves the related tickets.
  * Creates a new-in-memory ticket object that contains the combined history of the related tickets. And then calls _process_ticket with the new ticket object. This nested call to _process_ticket will result in a new LLM call and is expected to result in a call to PostFreeformNoteTool or PostTemplatedNoteTool. (and hence a new work_note being added permanently, via the ServiceNow API to the ticket)
* The parent CombineTicketHistory.execute() will then add an second work_note to the original ticket, indicating that the history of related tickets has been combined and added to the current ticket's work_notes. This will allow future LLM calls and human users to have access to the full history of the project.

B. LLM and tools in a loop (recommended)

This approach fits the standard agentic pattern for OpenAI-compatible tool-calling. `_process_ticket` becomes a loop that continues until the LLM calls a terminal tool or produces a response with no tool call:

```
messages = [system_message, user_message(ticket)]
for _ in range(MAX_ITERATIONS):         # guard against infinite loops
    response = llm.generate(messages, tools)
    if response has no tool call:
        break                            # LLM gave a final text response
    tool = find_tool(response.tool_name)
    result = tool.execute(service_now, ticket, **args)
    if tool.is_terminal:
        break                            # note posted; done
    # non-terminal: inject result and continue
    messages += [assistant_turn(response), tool_result_turn(result)]
```

Required changes:

- `Tool` gains an `is_terminal: bool` property (defaults `True` for all existing tools; `CombineTicketHistory` sets it `False`).
- `Tool.execute()` return type changes from `None` to `str | None`: non-terminal tools return their result string for injection into the next LLM call; terminal tools return `None` as now.
- `CombineTicketHistory.execute()` posts the audit note to ServiceNow (for audit/human readability) and also returns the combined history string so it can be injected as context for the next LLM turn.
- `llm.generate()` is extended to accept a full message list in addition to the current `system`/`user` interface, enabling multi-turn conversations.
- A `MAX_ITERATIONS` guard (suggested: 3) prevents runaway loops.

This approach avoids the circular dependency and recursion risk of Approach A. The incremental implementation cost is modest — primarily the extension to `llm.generate()` and the `is_terminal` property on `Tool`.

Approach A is not recommended: `CombineTicketHistory.execute()` calling `_process_ticket` creates a coupling from tools into command logic, and the recursive structure creates an infinite-loop risk if the nested call also triggers `CombineTicketHistory`.


