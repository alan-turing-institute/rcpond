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

If a ticket is closed, resolved, or cancelled, then the datetime of the final comment or work_note can be used as a proxy for the time of final resolution. When a ticket is closed, typically there is a comment (not work_note), posted by the `System` user, with a message similar to "This ticket was automatically closed by the system."

If no notes exist, `opened_at` is used as a last-resort fallback. If a ticket is still open, then the time of final resolution is unknown. There is no known way to determine this from the ServiceNow API.

Future enhancements: test the ServiceNow API to see if it is possible to retrieve the time of final resolution for closed tickets.

## Key metrics to include in the analytics report:

A sample of the kinds of metrics that we would like to include in the analytics report are listed below.

All metrics should be reported per ticket type. Most metrics would not be meaningful aggregated across types — e.g. time-to-resolution norms and outcome distributions differ fundamentally between a compute allocation request and a general support ticket. Where a cross-type summary is shown it should be clearly labelled as an aggregate.

The list of metrics below is a starting point. They have been given a approximate prioritisation, as stages. Implement Stage 1 initially to demonstrate the end-to-end analytics report generation. Stages 2-4 will be implemented in future iterations. 

We should expect the prioritisation for Stages 2 and beyond to vary  based on (a) complexity of implementation, (b) user consultation on what insights are useful, and (c) availability of the information in ServiceNow. Were possible we should ensure flexibility to add additional metrics in future iterations.

Stage 1:
* total number of tickets processed by RCPond
* total number of tickets processed manually (without RCPond)
* total number of tickets processed by RCPond that included subsequent manual interaction

Stage 2:
* distribution of the number of RCPond interactions per ticket (eg 0, 1, 2, 3, ...)
* distribution of the number of manual interactions per ticket (eg 0, 1, 2, 3, ...)
* length of time between ticket creation and first RCPond interaction
* length of time between ticket creation and first manual interaction
* length of time between ticket creation and final resolution (closed, resolved, or cancelled)
* length of time between first RCPond interaction and final resolution

Stage 3:
* How these metrics vary over time (eg by month, quarter, or year) to identify trends in RCPond performance and usage.

Stage 4:
* distribution of the outcomes produced by RCPond (indicated by the template name of the final note posted by RCPond)
* distribution of the initial triage decisions made by RCPond (indicated by the template name of the first note posted by RCPond)
* comparison of the final outcomes produced by RCPond vs the initial triage decisions made by RCPond (eg how often did the initial triage decision match the final outcome, and how often did it differ)


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


# Design decisions (as implemented)

These record the choices made while implementing the stages, so they are not lost to conversation/commit history.

## Note classification (Stages 1-2)

* A note is an **RCPond note** if its content matches the RCPond work-note prefix (any version).
* A note is **automated** if it was authored by the ServiceNow `System` user (e.g. the auto-close comment). Automated notes are *not* counted as manual. The author display name is matched against a single constant (`_SYSTEM_NOTE_AUTHOR = "System"`); confirm it matches the live instance.
* A **manual** note is any note that is neither an RCPond note nor an automated `System` note.

## Stage 1 metric definitions

* **Processed by RCPond** = the ticket has ≥ 1 RCPond note.
* **Processed manually (without RCPond)** = the ticket has ≥ 1 manual note and 0 RCPond notes. A ticket with no notes at all counts as *neither*.
* **Subsequent manual interaction** = a manual note appears after the *first* RCPond note (chronologically).
* Tickets whose type is not in the `_TICKET_TYPES` registry are excluded from the report entirely.

## Caching

* **Deferred.** A single bulk `get_tickets(all_including_closed)` call already returns every base ticket (with notes/state/dates), which is all the implemented metrics need, so the per-ticket cache buys little. It will be built when a stage needs expensive per-ticket full fetches. The `--refresh` flag is accepted but is currently a no-op.

## Stage 2 (distributions and time intervals)

* Interaction distributions are **exact per-count** (0, 1, 2, …); rows are shown for counts present in either the RCPond or the manual distribution.
* Durations are reported **in days**, summarised as n / median / mean / min / max.
* A ticket that does not qualify for an interval is excluded from that interval's statistics (e.g. open tickets contribute to no resolution interval).
* **Resolution-time proxy**: for closed/resolved/cancelled tickets, the datetime of the final note; falling back to `opened_at` when there are no notes; `None` (unknown) for open tickets.

## Stage 3 (trends over time)

* Tickets are bucketed by **creation date** (`opened_at`) cohort.
* Period granularity is selectable via `--period {month,quarter,year}`, **defaulting to quarter**. Period labels: `YYYY-MM`, `YYYY-Qn`, `YYYY`.
* Trend tables show, per period: the Stage 1 counts (total, processed by RCPond, processed manually, RCPond + subsequent) plus the **median resolution time (days)**.


# Implementation plan: pandas DataFrame rewrite

Because the `analytics` subcommand is gated behind `import pandas` (it is de-facto part of the
`html` optional extra, which already depends on `pandas>=2.0` and uses DataFrames in
`parse_html.py`), the analytics computation layer is built on a **pandas DataFrame substrate**
rather than bespoke dataclasses. This keeps Stage 3 (and future Stage 4 crosstabs / extra
export formats) cheap and stays consistent with existing code.

The per-ticket feature-extraction helpers on `Ticket` (`opened_datetime`, `rcpond_note_count`,
`manual_note_count`, `has_subsequent_manual_interaction`, `first_rcpond_note_datetime`,
`first_manual_note_datetime`, `resolution_datetime`) and `servicenow.ticket_type_key` are the
durable core and are reused unchanged. Only the aggregation + rendering layer is pandas-based.

**`build_ticket_frame(tickets) -> DataFrame`** — one row per ticket (unknown-type tickets
excluded), with columns derived from the `Ticket` helpers:

* `type_key`, `opened` (datetime64)
* `rcpond_notes`, `manual_notes` (int)
* `processed_by_rcpond`, `processed_manually`, `subsequent_manual` (bool)
* `first_rcpond`, `first_manual`, `resolution` (datetime64; `NaT` when absent/open)
* `days_to_first_rcpond`, `days_to_first_manual`, `days_to_resolution`,
  `days_rcpond_to_resolution` (float days; `NaN` when an endpoint is missing)

The column set is the de-facto schema (documented in the function docstring), replacing the
typed dataclasses.

**`render_markdown(df, period)`** — all grouping/aggregation is delegated to pandas
(`groupby`/`agg`/`value_counts`/`to_period`) and each section is rendered with
`DataFrame.to_markdown(index=False, missingval="—")`. `tabulate` (a `to_markdown` dependency)
is added to the `html` extra. `NaN` statistics (intervals/periods with no qualifying tickets)
render as an em dash; `.median()`/`.mean()` skip `NaN`, which matches the "exclude
non-qualifying tickets" rule. Trend periods use `opened.dt.to_period('M'|'Q'|'Y')`.

The CLI exposes `--period {month,quarter,year}` (default quarter) on the `analytics`
subcommand.
