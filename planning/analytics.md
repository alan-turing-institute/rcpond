# Add a means to generate analytics about the performance of the RCPond system

## Purpose

We would like to be able to reproducibly generate analytics about the performance of the RCPond system. We expect to run the analytics report generation on a regular basis (eg monthly or weekly)

The overall approach should be to derive information from ServiceNow itself, using the history of the tickets as the primary source of information. We do not plan to store any additional information in a separate database, but rather to generate the analytics report on demand from the ServiceNow ticket history.

We do not want the RCPond command to "phone home" to provide analytics information to a central server.

The analytics report should generate a summary for all tickets, including those that have only been processed manually, without RCPond. This should enable comparison of benefits of RCPond vs manual processing, and allow us to identify areas where RCPond is not performing as expected.

# Detecting information from the tickets and derived information

Different outcomes from the RCPond tool can be detected in different ways:
* After the `_note_prefix()` extension is deployed (see Dependencies), the template name can be used to identify the outcome of the RCPond interaction. Note that tickets processed before this change will fall into the unknown-outcome category for these metrics — a first analytics run after deployment should therefore be expected to show a high proportion of unknown-outcome tickets.
* (Optional for first version) The text of the note itself can be used to match key words/phrases in the templates
* In some cases the final outcome may not be detectable deterministically. This may include cases where the final outcome is a manual decision that is not reflected in the RCPond notes, or the `PostFreeformNoteTool` was used.
    * Initially having an "unknown-outcome" category is acceptable, but we should aim to reduce the number of tickets in this category over time.
    * A future enhancement could be to use an LLM to classify the final outcome based on the text of the notes, but this is not a priority at present.

If a ticket is closed, resolved, or cancelled, then the datetime of the final comment or work_note can be used as a proxy for the time of final resolution. If no notes exist, `opened_at` is used as a last-resort fallback. If a ticket is still open, then the time of final resolution is unknown. There is no known way to determine this from the ServiceNow API.

Future enhancements: test the ServiceNow API to see if it is possible to retrieve the time of final resolution for closed tickets.

## Key metrics to include in the analytics report:

A sample of the kinds of metrics that we would like to include in the analytics report are listed below.

All metrics should be reported per ticket type. Most metrics would not be meaningful aggregated across types — e.g. time-to-resolution norms and outcome distributions differ fundamentally between a compute allocation request and a general support ticket. Where a cross-type summary is shown it should be clearly labelled as an aggregate.

The list of metrics below is a starting point. In the future we will need to prioritise this list based on (a) complexity of implementation, (b) user consultation on what insights are useful, and (c) availability of the information in ServiceNow.

* total number of tickets processed by RCPond
* total number of tickets processed manually (without RCPond)
* total number of tickets processed by RCPond that included subsequent manual interaction
* distribution of the number of RCPond interactions per ticket (eg 0, 1, 2, 3, ...)
* distribution of the number of manual interactions per ticket (eg 0, 1, 2, 3, ...)

* length of time between ticket creation and first RCPond interaction
* length of time between ticket creation and first manual interaction
* length of time between ticket creation and final resolution (closed, resolved, or cancelled)
* length of time between first RCPond interaction and final resolution

* distribution of the outcomes produced by RCPond (indicated by the template name of the final note posted by RCPond)
* distribution of the initial triage decisions made by RCPond (indicated by the template name of the first note posted by RCPond)
* comparison of the final outcomes produced by RCPond vs the initial triage decisions made by RCPond (eg how often did the initial triage decision match the final outcome, and how often did it differ)

* How these metrics vary over time (eg by month, quarter, or year) to identify trends in RCPond performance and usage.

# Usage

There should be a new subcommand (`analytics`) which, when run, generates the analytics report and outputs it in markdown. The report should include tables of the key metrics.

In future we may want to add additional output formats to support visualisation of the data, but at present we will focus on generating a markdown report.

# Dependencies and assumed prior work

Assume these have already been implemented (see planning/combine-ticket-history.md):
* TicketState enum and the ability to retrieve tickets in all states (including closed, resolved, and cancelled) using `get_tickets()` method in `ServiceNow` class.
* `_note_prefix()` extended to the format `[code]<b>RCPond v{version} [{tool_name}] generated response:</b>[/code]`, where `tool_name` for `PostTemplatedNoteTool` is `post_templated_note:{template_name}` (see planning/combine-ticket-history.md).

# Caching

The performance is not expected to be a critical concern, since the analytics report will be run on a periodic basis (eg weekly or monthly). However, the report generation may require fetching a large number of tickets from ServiceNow, which may be slow.
Local caching of the ticket history data (raw ticket objects, not computed metrics) should be implemented. Caching raw data rather than computed metrics allows metric definitions to change without requiring a full re-fetch. A simple JSON file in the XDG cache directory will be sufficient.

Closed, resolved, and cancelled tickets are immutable once in that state and can be cached indefinitely. Open tickets may gain new notes at any time and should be re-fetched on every run.

The cache must record the ticket type (the `_TICKET_TYPES` registry key) alongside each ticket so that it can be deserialized to the correct dataclass. A cache entry without a type key should be treated as stale and re-fetched.

A `--refresh` flag should be provided to force a full re-fetch of all tickets, bypassing the cache. This serves as an escape hatch if the cache becomes stale or corrupt.

# Implementation

Analytics computation logic should live in a new `analytics.py` module. The `command.py` module should contain an `analytics(config)` function as the entry point, consistent with how other commands are structured. The CLI subcommand should be added to `cli.py` following the same `_config(ctx)` pattern used by other subcommands.
