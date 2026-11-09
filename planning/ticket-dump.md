# Dump tickets

The aim is to create a dump file of ServiceNow tickets that will be used by RCPond in the two methods described in steps 2 and 3 and 'externally' to RCPond.

"externally to RCPond", mean outside the scope of the RCPond tool. The data will still be used by the same user and other operator of the ServiceNow instance. There are no concerns about leaking private information held on ServiceNow.

Build this incrementally

## Assumption: Downloading all of the full tickets does not take an onerous amount of time.

This assumption was tested. A script was written for the purpose which operated by:
- Dumps full tickets to file for all tickets of known type
- Reused and imported existing code from rcpond package to keep the script simple
- When run, it records the time for the full download
The results (~70sec on the production instance) are acceptable.

## Step 1 dump tickets

RCPond should have a `dump-tickets` subcmd, which creates a dump of 'all' of the ServiceNow tickets to a jsonl file. 'All' in this context means the full ticket for every one of the known ticket types now used in the 'analytics' subcmd.
`dump-tickets` should have an optional `--output-file` param;
- If  `--output-file` is NOT specified the default value should be in the CWD, with a filename consisting of the domainname from `RCPOND_SERVICENOW_WEB_URL` and the datetime (local time, to nearest second), with `.jsonl` extension.
- If  `--output-file` is specified it should be the path to the output file. This can be either an absolute path, or a path relative to the CWD.
- There should be a simple clobber protection - it should error if the output-file value (be it specified or default) already exists. The file-and-dir-exist checks should occur before the ServiceNow query, so that the subcmd fails-fast.

Ticket types that are not one of RCPond's known types are deliberately excluded.

The dump should include ticket states 'all_including_closed'

`dump-tickets` must build its Config with `require_rules_and_templates=False`, at its own
`_config(ctx, ...)` call site. It reads neither the rules nor the email templates, and the default of
`True` would fail it with `Missing required configuration: rules_path, email_templates_dir` — the
same false early failure already fixed for `login`, `whoami` and `analytics`. This matters more for
`dump-tickets` than for most commands, because it is meant to be run ad hoc, often from an
environment that has ServiceNow credentials but no per-ticket-type config.

### Where the format code lives

A new `src/rcpond/ticket_dumps.py` module owns both sides of the format: header construction,
serialisation, header validation, the `schema_version` policy, filter-and-fill rehydration and the
`type_key` cross-check. Step 2's loader is a function here, not something written inside
`command.analytics`, because Step 3 needs the same loader.

Keeping write and read together makes the round trip testable with no ServiceNow, no network and no
pandas: write records, read them back, assert equality. That is the test this format needs, and it is
awkward to write if the two halves live apart.

The module must not import pandas. `pandas` is in the `html` optional extra, so putting the writer in
`analytics.py` would make `dump-tickets` — a core command — depend on an optional extra. For the same
reason, once Step 3 drops the html scraping, `evaluate-all` could stop being gated behind the `html`
extra altogether, since it would need neither `bs4` nor `pandas`.

This mirrors the existing split of `parse_html.py` (format) and `html_servicenow.py` (a ServiceNow-
shaped wrapper over it). If Step 3 wants a `DumpServiceNow(ServiceNow)` with no-op writes, for
`_process_ticket` to run against, it sits on top of this module in the same way. Choosing the module
now does not foreclose that class later.

What belongs here: **anything that knows the dump file's shape**. Header fields, the version policy,
rehydration, validation.

What does not: **anything that merely uses dumped tickets**. Analytics aggregation, CLI flag parsing,
and the default filename rule — that last one is a near-miss, but it is `dump-tickets`' user
interface rather than the format, and admitting it would pull CLI concerns in behind it.

The rule matters because a module described as 'the dump module' is how a focused module becomes
`utils.py`.

It will need `_TICKET_TYPES` and `ticket_type_key` from `servicenow.py`. That is a one-way
dependency and no cycle — `config.py` already imports `_TICKET_TYPES` — but this is the third
consumer of a private name, so consider giving the registry a public accessor at the same time.

### Dump file format

The first line is a header object describing the dump. Every subsequent line is one ticket record:
`{"type_key": ..., "ticket": {...}}`, with `type_key` a registry key.

A header line rather than a sidecar `.meta.json` file: the metadata cannot be separated from the data
it describes, and it survives the file being renamed — which the default filename, carrying the
instance and datetime, otherwise relies on not happening.

Proposed header fields:
- `schema_version` — so a future `--dump-file` can reject an incompatible dump instead of silently
  misreading it. Lives here rather than on every record, where it would just repeat. A single
  integer, starting at 1. See the compatibility rule below.
- `created_at` — when the dump was taken, as ISO 8601 in UTC, with the offset written out as
  `+00:00` (e.g. `2026-11-07T14:53:21+00:00`). Always UTC, not local-time-with-an-offset: dumps taken
  on machines in different timezones are then directly comparable, and no reader has to normalise
  before sorting. This is the timestamp an `analytics --dump-file` report should quote;
  without it the report can only name the file. Deliberately not the format used in the default
  filename, which is local time with no colons for filesystem safety, and deliberately not the
  `DD/MM/YYYY HH:MM:SS` used by ServiceNow display values: the header is parsed by machines, possibly
  outside RCPond, so it needs an unambiguous timezone.
- `servicenow_url` and `servicenow_web_url` — which instance the tickets came from. The default
  filename carries the web domain, but a renamed or user-named file carries nothing.
- `query` — the union-of-queries actually sent.
- `registry_ticket_types` — the registered type keys at the time of the dump. A dump is only as
  complete as the registry on the day it was taken; recording this makes a later dump comparable
  with an earlier one, and makes the 'deliberately excluded' types above visible to a reader who
  does not know RCPond's registry.
- `record_count` — the number of ticket lines that follow.
- `limit` — the `--limit` value if one was applied, otherwise null. See the `--limit` note below.

Readers should ignore unknown header fields, so fields can be added without a `schema_version` bump.

Because `record_count` is in the header and the header is line 1, the records are accumulated in
memory and the whole file written in one go. The obvious streaming implementation — write the header,
then append each ticket as it is fetched — cannot know the count when it writes line 1.
`scripts/time_full_ticket_dump.py` already buffers this way; a few hundred full tickets is a trivial
amount of memory.

A consequence worth accepting deliberately: a crash part way through the fetch leaves no file at all,
rather than a truncated one. That is the better outcome here, since a truncated dump is an error case
anyway (see `record_count` below).

Records are sorted by ticket `number`. ServiceNow's result order is not guaranteed stable between
runs, and unsorted records would make two dumps of the same instance diff as though everything had
moved. Diffing successive dumps is a plausible 'externally to RCPond' use, and a stable order is free
now and awkward to introduce once files are in circulation.

The sort is applied to the base tickets immediately after the bulk fetch — **before** any `--limit`
slice, not just before writing. That makes `--limit NN` reproducible: the same NN tickets every run,
on any machine. Sorting only at write time would leave the sample at the mercy of ServiceNow's
ordering for no benefit, since the sort has to happen anyway.

### A failed ticket fetch aborts the whole dump

If `get_full_ticket` fails for any single ticket — a timeout, a 5xx, a token expiring mid-run — the
subcmd aborts and writes no file. It does not skip the ticket and carry on.

This is not a hypothetical case: `scripts/time_full_ticket_dump.py` catches per-ticket failures and
continues, because they were expected to happen, and the fan-out gives ~70sec of opportunity.

Aborting is chosen for consistency with every other stance here — fail-fast on the output path,
error on a `record_count` mismatch, error on an unknown `type_key`. A skipped ticket would make
`record_count` under-count the classifiable tickets, and nothing in the file would distinguish '450
tickets, all of them' from '450 of 462, twelve failed'. That is the silent-incompleteness hazard the
`limit` header field exists to prevent, arriving by another route.

The cost is a wasted run when one ticket is flaky. The error should name the ticket and the
underlying failure, so a re-run is an informed choice rather than a guess.

### schema_version compatibility

`schema_version` is a single integer, starting at 1. Not semver: a minor/patch distinction only earns
its keep when other people write readers against the format, and here one codebase both writes and
reads it.

Bump only on a breaking change — a field removed, renamed, or given a different meaning. Adding a
field is not breaking: readers ignore unknown header fields, and the same promise applies to ticket
records, so adding a catalogue variable to a ticket type does not invalidate every dump in existence.
The loader has to be written to make that promise true — see 'Reading a dump back'.

A reader accepts only the `schema_version` it was written for, and rejects every other value:
- version greater than the one it knows — the dump was written by a later RCPond. Error, naming both
  versions and saying to upgrade. This is the case a user hits once a colleague upgrades first.
- version lower than the one it knows — the dump was written by an earlier RCPond. Error, naming both
  versions and pointing at CHANGELOG.md.

**There is no promise to read older schema versions.** No migration layer, no reader per historical
version. When the version is bumped, the CHANGELOG entry records which RCPond version wrote which
`schema_version`, and that is what a user consults to pick a version that can read an old dump. The
cost of this is borne by a rare case; the cost of the alternative is borne on every future change.

Reject a file whose first line has no `schema_version` key: it is not an RCPond dump. Note this
catches files from `scripts/time_full_ticket_dump.py`, which have no header and would otherwise
half-work, since their record shape is the one adopted here.

Validate the header before reading any records, matching the fail-fast stance on the output path
above. A dump that takes ~70sec to produce deserves a loader that rejects it immediately rather than
part way through.

Two related header checks:
- `record_count` disagreeing with the number of ticket lines means a truncated or interrupted write.
  Error: a partial dump yields a quietly wrong analytics report, the same hazard as `--limit`.
- `limit` non-null is a *valid* partial dump, not an error. The report says so, which is covered by
  'any information in the header' in Step 2.

### Reading a dump back

Records are rehydrated using the registry: construct `_TICKET_TYPES[type_key]` from the record's
`ticket` object, giving back the same subclass instance that was dumped.

Not the base `Ticket`: the records hold full tickets, so `Ticket(**record["ticket"])` raises
`TypeError: unexpected keyword argument` on the first catalogue variable. Filtering down to the base
fields would also work for Step 2 — `build_ticket_frame` only uses base-ticket methods plus
`ticket_type_key()` — but it discards exactly the fields Step 3 needs, and would have to be undone.

The record is not passed to the constructor as-is. Before constructing, the loader:
- drops keys the dataclass does not declare, and
- fills declared fields that the record does not carry with `""` (every extra field on every ticket
  type is a bare `str`).

This is what makes 'adding a field is not breaking' true in both directions. A dataclass constructor
rejects unknown keyword arguments *and* requires every field that has no default, so without the
filter-and-fill:
- a dump from a later RCPond that added a catalogue variable raises
  `TypeError: unexpected keyword argument`, and
- a dump from an earlier RCPond, read after a field was added, raises
  `TypeError: missing required positional argument`.

Neither is caught by the `schema_version` check, because adding a field does not bump the version —
so the user would get a raw `TypeError` instead of the actionable message the version check exists to
give. Filtering and filling costs a few lines and removes both cases.

A `type_key` that is not in the current registry means the dump came from a later version of RCPond
than the one reading it. This passes the `schema_version` check, because registering a new ticket
type is an additive change and does not bump the version. Detect it up front by comparing the
header's `registry_ticket_types` with the registry, and **error** — naming the unknown type keys.

Not skip-and-warn: skipping would silently narrow an `analytics` report, which is the exact failure
the header provenance exists to prevent.

The asymmetry is deliberate, and only one direction is an error:
- a type in the header that the **registry lacks** — the dump holds records this RCPond cannot
  rehydrate. Error.
- a type in the **registry that the header lacks** — the dump simply predates that type being
  registered. Benign, and must not error. This is the common case as the registry grows, and every
  dump taken today becomes an instance of it the next time a ticket type is added.

#### The stored type_key is authoritative

The `type_key` in the record records what the ticket was classified as at dump time, by the registry
current then. A reader uses it as-is and does **not** re-derive the type from `MATCH_CRITERIA`.

This matters because `build_ticket_frame` currently re-derives the type itself with
`ticket_type_key()`, and **silently excludes** any ticket for which that returns `None`. For live
data that is harmless: the union query and the classifier are built from the same `MATCH_CRITERIA`,
so everything fetched classifies. For a dump, the classification and the read happen at different
times, and nothing keeps them in step.

So without the stored key winning, a single `MATCH_CRITERIA` change — ServiceNow rewording a
`short_description`, which is the kind of change the registry exists to absorb — would break every
dump file already written. The records still load, because `type_key` is still a valid registry key,
but every one of them is dropped from the frame, giving an empty or heavily narrowed report. Re-
deriving throws away an answer the file already holds, and that was correct when it was written.

So Step 2 passes the stored `type_key` through to `build_ticket_frame` rather than letting it
re-derive. See the note in Step 2 — this is a change to `analytics.py`, not only to the loader.

The loader still compares `ticket_type_key(rehydrated_ticket)` with the stored `type_key`, but a
disagreement is a **warning**, not an error — naming the ticket number, the stored key and the
derived one. It no longer threatens correctness, since the stored key wins. It is now a signal that
`MATCH_CRITERIA` has drifted since the dump was taken, which is worth knowing and otherwise
invisible.

A stored `type_key` that is not in the registry at all remains an error, as above: there is no class
to rehydrate it into.

### Notes from the implementation

Three decisions taken while building `ticket_dumps.py` that this plan had left open.

**Drift is returned, not printed.** `load_dump` collects the disagreements into
`DumpFile.type_key_drift` rather than emitting the warning itself. Two reasons: the project turns
warnings into errors under pytest, so `warnings.warn` would make drift a test failure rather than a
warning; and printing from the format module would put user interface in the one layer this plan
keeps it out of. **This makes reporting drift Step 2's job** — if `command.analytics` ignores the
list, drift is silent again, which is the opposite of the intent.

**`created_at` is injectable.** `write_dump` takes an optional `datetime` so tests are not
timing-dependent. It is converted with `.astimezone(UTC)`, so a caller passing an aware local-time
value still produces UTC in the file.

**`write_dump` overwrites, and does not do the clobber check.** That check belongs to the caller,
which makes it before fetching anything. Putting it in `write_dump` would place it after the ~70sec
fan-out, which is what the fail-fast requirement above rules out.

One latent cost worth recording: `_rehydrate` fills a missing field with `""`, assuming every ticket
field is a `str`. True of all three registered types today, and noted in the code. A non-`str` field
added later would be filled with a wrongly-typed value rather than failing. No guard was added, as
that is speculative until such a field exists.

There should be a:
- `--limit NN` flag; the first NN tickets by ticket `number`. Reproducible between runs, because the
  sort is applied before the slice (see above). If `--limit NN` is used, include this in the header's
  `limit` field. The limit should be implemented by fetching the base ticket for all tickets, sorting,
  and then slicing before the fan-out. Only retrieve the full ticket for the NN tickets.

- progress output; the same behaviour as 'scripts/time_full_ticket_dump.py'

Docs and changelog for this step:
- `CHANGELOG.md` — an `Added` entry under `## [Unreleased]` for the `dump-tickets` subcmd, stating
  that it writes `schema_version` 1. Every later bump gets an entry too: the changelog is how a user
  finds the RCPond version that can read an old dump, since readers do not support old versions.
- `docs/` — document the subcmd, its flags, the default filename rule, and the dump file format.
  The format section above is the reference for anyone reading a dump outside RCPond, so it belongs
  in the docs rather than only in this planning file.

## Step 2 produce analytics based on dumped tickets

The 'analytics' subcmd has the stub of a cache and `--refresh` feature. This is not required and should be dropped. The changes required to drop it include:
- CHANGELOG.md — a Removed/Changed entry under ## [Unreleased], since it's a user-visible CLI change (your CLAUDE.md requires this).
- cli.py:373-379 — the typer.Option itself.
- command.py:326 — the refresh: bool = False parameter, the _ = refresh discard at line 358, and the refresh entry in the NumPy-style Parameters block at lines 341-344.
- command.py:356-357 — the TODO comment, which points at a cache design in planning/analytics.md that will no longer be happening. That doc needs a note saying the cache was superseded by the dump file, or a future reader will implement it.

Instead the analytics subcmd should have a `--dump-file` option.
- If not provided there should be no change to how the subcmd operates. It should retrieve the tickets from the configured ServiceNow instance. Also the report should state that it was based on live data, giving a timestamp approximately when the query was run.
- If `--dump-file` is provided, the subcmd should derive the analytics report from the tickets in the dump file and not query a live ServiceNow instance. Also the report should state the path+name of the file it was based on, and a table with all the key:value pairs from the header.

`analytics --dump-file` is a niche requirement. For now the user can tolerate having to have the
vars below in the config file, none of which are used when reading from a dump file. Adding a
`require_servicenow=False` param to the Config constructor would remove them; it is not worth doing
yet.

Required regardless of auth mode (`analytics` already passes `require_rules_and_templates=False`,
so the rules and template vars are not among them):
- `RCPOND_LLM_CHAT_COMPLETIONS_URL`, `RCPOND_LLM_API_KEY`, `RCPOND_LLM_MODEL` — note these are *not*
  auth related. `analytics` never calls the LLM, in either mode; they are required because `Config`
  validates every field unconditionally.
- `RCPOND_SERVICENOW_URL`, `RCPOND_SERVICENOW_WEB_URL`

Plus, depending on the resolved auth mode:
- `token`: `RCPOND_SERVICENOW_TOKEN`
- `oauth_user`: `RCPOND_SERVICENOW_CLIENT_ID`, `RCPOND_SERVICENOW_CLIENT_SECRET`,
  `RCPOND_SERVICENOW_OAUTH_SCOPE`, `RCPOND_SERVICENOW_OAUTH_REDIRECT_PORT`,
  `RCPOND_SERVICENOW_OAUTH_AUTH_URL`, `RCPOND_SERVICENOW_OAUTH_TOKEN_URL`
- `oauth_client_credentials`: `RCPOND_SERVICENOW_CLIENT_ID`, `RCPOND_SERVICENOW_CLIENT_SECRET`,
  `RCPOND_SERVICENOW_OAUTH_TOKEN_URL`

The values are never sent anywhere in dump-file mode — they only have to be present. See the note
below on branching before `ServiceNow` is constructed, which is what makes that true.

The loader is the one in `ticket_dumps` (see Step 1), not a reader written inside `command.analytics`.
Step 3 needs the same function.

`analytics` must report `DumpFile.type_key_drift`. `load_dump` returns the drift rather than printing
it (see 'Notes from the implementation' in Step 1), so a caller that ignores the list makes
`MATCH_CRITERIA` drift silent again — the failure the cross-check exists to surface. Printing the
ticket numbers, the stored key and the derived one is enough.

`build_ticket_frame` must accept the `type_key` per ticket and use it, instead of re-deriving the
type with `ticket_type_key()` and silently dropping what it cannot classify. See 'The stored
type_key is authoritative' in Step 1 for why. Two consequences:
- This is a signature change in `analytics.py`, so it is Step 2 work, not loader work.
- The live path supplies the key too — `ticket_type_key()` at the point of fetch — so there is one
  code path, not a dump-only special case. Live data classifies by definition, so this changes no
  behaviour there.

The `--dump-file` branch must be taken *before* `ServiceNow` is constructed. `ServiceNow.__init__`
eagerly calls `get_bearer_token(config)`, so merely constructing the client authenticates — a live
token request, and under `oauth_user` possibly a browser flow. Building the client and only then
choosing where the tickets come from would contradict 'not query a live ServiceNow instance' while
appearing to satisfy it. With the branch in the right place, the config vars must be present but
nothing is ever sent.

Docs and changelog for this step:
- `CHANGELOG.md` — a `Removed`/`Changed` entry for `--refresh` (see above) and an `Added` entry for
  `--dump-file`.
- `docs/` — document `--dump-file`, and the provenance line the report now carries in both modes.

## Step 3 Update the evaluate subcmd to use the dump jsonl files

Currently the evaluate subcmd compares a ground-truth csv file with an html-scraped dump of the tickets.
The html scraping can be dropped.
Instead the ground-truth csv can be compared with the jsonl dump file.

It is intended that Step 3 will supersede the contents of 'combining-analytics-and-evaluate-subcommands.md'. However there are still features described in that doc that have not yet been incorporated into Step 3.

Docs and changelog for this step: to be decided once the step is specified. It removes the html
scraping, which is user-visible, so at minimum a `Removed` entry and a pass over any docs that
describe `evaluate-all` taking a directory of html files.

## Step 4 - edge cases

If either  `RCPOND_TICKET_TYPE=github_onboarding_request rcpond dump-tickets` or 
`RCPOND_TICKET_TYPE=github_onboarding_request rcpond analytics`  fail, this is acceptable in an initial implementation, because this is a niche case. But this could be explicitly handled in due course.

Note that for `analytics` this is not a possibility but a certainty: a set `RCPOND_TICKET_TYPE` makes
`_assert_expected_ticket_type` reject every ticket the cross-type union query returns.

`dump-tickets` could have an optional `--ticket-type` flag. 
  If not specified then all registered ticket types are dumped
  `rcpond dump-tickets --ticket-type xxx` would create a dump file containing only ticket-type=xxx, where 'xxx' is a registered ticket type

`analytics` could have an optional `--ticket-type` flag. 
  If not specified then the report should have sections for all registered ticket types (eg current behaviour)
  `rcpond analytics --ticket-type xxx` would create a report containing only sections for ticket-type=xxx, where 'xxx' is a registered ticket type.

Both flags need docs and a changelog entry when implemented.