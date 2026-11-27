# Post comments

**Status: DRAFT.** PR 1 merged. Tagging retired and replaced by `watch_list` (2026-11-25);
the last technical unknown is now answered, so PR 2 is unblocked bar the production test.

Add read and write wrappers for the `comments` field, mirroring the existing `work_notes`
pair.

> **The one thing that makes this different from `work_notes`.** Work notes are internal;
> **comments are customer-visible** and, on a normal ServiceNow configuration, notify the
> requester. Everything RCPond writes today is internal. This is the first feature that emits text
> to an external person, so it carries a different risk class from anything else in the codebase
> — but the text is template-rendered, with no LLM-generated parameters, and
> `post_comment()` is not exposed to the LLM as a tool. Free LLM composition is deferred
> (see Future Step).

## Technically unblocked

`comments` **is writable** through the Table API — confirmed 2026-11-19 on Dev `RES0001192` by
`scripts/probe_field_writes.py`, in a run whose controls both behaved as expected (`state`
NOT-WRITABLE, `work_notes` WRITABLE). A probe entry appended and read back cleanly.

Nothing technical stands in the way. What remains is a question of whether and how this
*should* be done, which the steps below settle.

## What already exists

More than might be expected — only the write path is missing.

| Piece | Status |
|---|---|
| `Ticket.comments` (raw display-value string) | exists, `servicenow.py:72` |
| `_parse_comment_display_values()` | exists, shared with `work_notes` |
| `Ticket.get_combined_notes()` merges both | exists |
| `comments` in `_REFRESHABLE_FIELDS` | exists |
| RCPond/manual note classification across both | exists |
| `get_comments()` | **missing** |
| `post_comment()` | **missing** |
| tool definition + `_IMPLEMENTATIONS` entry | **out of scope for this PR** |

## Sketch

### Step 1 — `ServiceNow.get_comments()`

Exact mirror of `get_work_notes()`:

```python
def get_comments(self, tkt: Ticket) -> list[NoteEntry]:
    result = self._fetch_fields(tkt.sys_id, {"comments"})
    return _parse_comment_display_values(result["comments"])
```

Low risk, read-only, could land on its own ahead of everything else.

### Step 2 — `ServiceNow.post_comment()`

Mirrors `post_note()`.

`post_comment()` must include something that allows both humans and the audit trail to identify
it as a machine generated comment. We will seek user feedback on the preferred format:

(a) Prefix - identical to the work notes
(b) Prefix - but will a more user-friendly string format
(c) postfix/signature (may require updating the auditing logic)

Initially assume '(a) prefix'. We will only switch to another option if user feedback
recommends it.

**Why this needs deciding rather than copying.** `_note_prefix()` tags every work note so
RCPond's own output can be told from a human's — `is_rcpond_processed`, `rcpond_note_count`
and `has_subsequent_manual_interaction` all depend on it. But a customer-visible comment
reading `[rcpond v0.4.1 tool_name] Hello...` is addressed to a researcher, not an operator.
The two requirements pull against each other:

- keep the prefix → the audit trail works, the requester sees machine noise;
- drop it → the comment reads properly, and RCPond can no longer recognise its own comments,
  which breaks the "has a human replied since?" logic for this field;
- option (c) splits the difference by reading as a signature rather than a tag
  (e.g. a trailing `-- posted automatically by RCPond`), at the cost of re-anchoring the
  matchers, which are currently anchored to the start of the note.

Option (a) keeps the audit logic untouched, which is why it is the starting assumption.

### Step 3 - Notifying users

Within this PR the `post_comment()` function will only be called within existing Tools (eg the
GitHubOnboardingTool). In practice the messages will be rendered using jinja2 templates (which
do not require LLM-generated parameters). Posting comments will not be presented to the LLM as
a tool in its own right.

The user named in `requested_for` on the ServiceNow ticket along with followers will be
notified - this is a desired feature, not a bug.

That notification is what makes this feature "sending an email to a researcher" rather than
"writing to a record", and it is the decision with the largest blast radius in this plan. The
table's notification rules should be confirmed as part of the production test below, not
assumed from the above.

**No per-comment human confirmation.** The existing tools act unattended and this one will
too. The justification is that the text is template-rendered and deterministic: there is no
LLM-composed content to review at the point of sending, so a confirmation step would be
approving a string that was already fixed when the template was written. The safeguards are
placed elsewhere — a config toggle, and a supervised first production run (see Sequencing).

#### Notifying someone other than the requester — settled 2026-11-25

The users asked for a way to prompt an email to someone else. This was originally scoped as
*tagging* (`@<name>` in a comment). **Tagging is not the mechanism, and is no longer part of
this plan.** Manual testing on production established that:

- tagging a person with `@<name>` in a comment does **not** send them mail;
- adding them to the ticket's **`watch_list`** and then commenting **does** — with or without
  any `@<name>`.

That retires the blocked spike below and replaces it with a narrower question — *can RCPond
write `watch_list`?* — which `scripts/probe_watch_list.py` has now answered: **yes, on both
instances.** See "Spike attempt 2" for the evidence and the constraints that come with it.

The practical consequence for templates: a template does not carry a tag, it carries (or the
calling tool supplies) an **email address to add to the watch list** before the comment is
posted. Notification is then a property of the ticket, not of the comment text.

### Step 4 — tests, docs, changelog

Mirror the `post_note` tests. Note that journal writes cannot be undone, so the integration
test appends permanently to a Dev ticket — the existing `test_post_note` already sets that
precedent.

### Future Step (out of scope for this PR) — the LLM tool

A `tools.py` entry plus an `_IMPLEMENTATIONS` lambda, alongside the existing note tool. This
is the step that needs the most care, for the reason in the banner.

The question it has to answer is whether the LLM may compose comment text freely or only
select from templates. Free composition is more useful and much harder to make safe; templates
are the conservative start, and can be relaxed later once there is some operational experience
of RCPond writing to researchers at all. Deferring it is what keeps this PR's risk bounded.

## Sequencing

Do this work before `set-ticket-state`, and carry it through until it is either complete or has
discovered a blocker that requires action by the ServiceNow administrators.

That ordering is not merely preference: this work is unblocked while `set-ticket-state` waits
on a third party, and `comments` is a mandatory companion of both the `on_hold` and
`resolve_research_request` UI Actions (see planning/set-ticket-state.md, Step 0b) — so this is
a *prerequisite* for that work rather than a detour from it.

One consequence of that coupling is worth recording here, because it constrains the other plan:
since journal fields append, **a state transition that carries `comments` is itself a
customer-visible, notifying comment.** There is no way to perform a quiet `on_hold`.

### PR 1 — plumbing, with no callers

Steps 1, 2 and 4: `get_comments()`, `post_comment()` with prefix (a), and their tests.

Nothing calls `post_comment()` yet. Production behaviour is unchanged and nothing reaches an
external person, so this half can merge without waiting on either unknown below. It is also
the half `set-ticket-state` will need.

### Spike, in parallel — can the Table API tag a user? — **SUPERSEDED**

> **Superseded 2026-11-25.** The question below is the wrong one: tagging does not notify
> anybody (see Step 3). It is kept because attempt 1's findings about what the APIM gateway
> exposes remain true and are relied on elsewhere. The live question, and its answer, are in
> "Spike attempt 2".

Run this *before* writing any templates, not while writing them. It is the only real unknown
left, and it has the same shape as Step 0 in planning/set-ticket-state.md: a cheap experiment
whose answer changes the scope of the work that follows. Tagging may be a Workspace/UI feature
that the Table API does not honour at all.

- **Question:** does a PATCH to `comments` containing a user identifier render as a tag?
- **Instance:** Dev — tagging works there and email is disabled, which is exactly the
  combination this needs.
- **Pass:** the tag renders and the tagged user is recorded. Templates may carry identifiers.
- **Fail:** the identifier appears as literal text. Templates must not promise tagging, and
  Step 3 shrinks accordingly.

#### Spike attempt 1 — 2026-11-24 — blocked, not answered

Run with `scripts/probe_mention.py`. **Neither pass nor fail could be established**, because
both ways of verifying a mention are unreachable through the APIM gateway:

| Table | What it would have told us | Result |
|---|---|---|
| `sys_mention` | that a mention was actually recorded — this is what drives the notification | **HTTP 404** |
| `sys_journal_field` | the raw stored markup, before display rendering | **HTTP 404** |
| `x_tati_resmgt_research` | control: auth and gateway path are fine | HTTP 200 |

Writing candidate formats was therefore abandoned: a journal entry that merely *looks* like a
mention notifies nobody, and without `sys_mention` there is no way to tell the two apart. The
only readable view is the concatenated display value, which renders and may strip markup.

**No example exists to copy, either.** A scan of all 731 tickets in the 2026-11-08 production
dump found 15 containing `@Name` strings; all five inspected in the WebUI turned out to be
pasted email threads, not mentions. So nobody has demonstrably used this feature on this table.

**Two things follow.**

1. **The decisive method is a browser HAR capture**, exactly as it was for the state question
   (planning/set-ticket-state.md, Step 0b). Tag a user in the Dev WebUI with the network log
   recording, then read the payload. That gives the real format rather than a guess, and the
   comment can afterwards be read back through the API to see what survives.
2. **First, confirm tagging is wanted.** Step 3 says templates should "ideally" carry user
   identifiers. If the operators have not tagged anyone in 731 tickets, this may be solving a
   problem they do not have — which is a cheaper question to answer than the HAR capture, and
   should be asked first.

#### Spike attempt 2 — 2026-11-25 — ANSWERED

Run with `scripts/probe_watch_list.py`, against Dev `RES0001369` and then production
`RES0001933` in a single invocation. Both stages' controls behaved as expected (`state`
NOT-WRITABLE, `assigned_to` WRITABLE), so the verdicts are trustworthy.

| Question | Result |
|---|---|
| Is `watch_list` readable? | **Yes**, both instances. Production already held one watcher. |
| Can it be written with a `sys_user` sys_id? | **WRITABLE**, both instances |
| Can it be written with a bare email address? | **WRITABLE**, both instances — ServiceNow resolves the address to the right user server-side |
| `GET /sys_user` (collection) | **HTTP 404** — no search by name or email |
| `GET /sys_user/{sys_id}` (single record) | HTTP 200 — resolves the *wrong* direction |
| Dot-walk `?sysparm_query=assigned_to.email=<addr>` on the app table | **HTTP 200**, returns the sys_id |

**The feature is unblocked and needs nothing from the API owner.** Write the email address
straight into `watch_list`; ServiceNow does the resolution. No `sys_user` access is required.

Three constraints that fall out of the run, all of which bind the implementation:

1. **`watch_list` is overwritten by a PATCH, not appended to.** The production probe replaced
   an existing watcher with its probe value — and returned HTTP 200 while doing so. Adding a
   watcher must therefore be **read–modify–write**: fetch the current list, append, write the
   whole list back. Done naively, adding one watcher silently un-watches everyone else, and
   nothing in the response indicates it happened.
2. **The email route is proven only for addresses that map to a real `sys_user`.** What an
   unknown address does — stored verbatim, or silently dropped — is untested. Silently dropped
   is the dangerous case: the comment still posts, and nobody is notified. Worth a deliberate
   test before any template depends on an address RCPond has not already seen on the ticket.
3. **Order matters.** The watcher must be on the list *before* the comment is posted; the
   notification fires on the comment, not on the watch-list change.

A fallback exists if the email route ever stops working: the dot-walk query resolves an
address to a sys_id using only the table the gateway already exposes, for anyone appearing in
a reference field on any ticket. Worth recording, not worth building now.

**Not retested, and not in doubt:** that a watcher receives mail when a comment is posted.
The manual production test of 2026-11-25 established it.

### PR 1b — watch-list plumbing, with no callers

Same shape as PR 1, and mergeable for the same reason: nothing calls it, so nothing reaches a
researcher. `post_comment` work does not block on it.

```python
def get_watchers(self, tkt: Ticket) -> list[dict[str, str]]
def add_watcher(self, tkt: Ticket, identifier: str) -> list[dict[str, str]]
def remove_watcher(self, tkt: Ticket, sys_id: str) -> list[dict[str, str]]
```

`identifier` takes an email address or a sys_id, mirroring `assign_to`'s signature.

**`assign_to` is the pattern to follow, not `post_comment`.** It already writes, re-reads, and
treats an empty `display_value` as "ServiceNow did not recognise that identifier" — then
reverts and raises. That is exactly the guard the unknown-address risk (Spike attempt 2,
constraint 2) needs, and it already exists in this codebase.

Design points, each of which exists because of something the probe showed:

- **Read–modify–write, verified by re-reading.** Read the current list, append, write the whole
  list back, re-read, and confirm both that the new entry is present *and* that every prior
  entry survived. A PATCH overwrites. The response cannot be trusted: this table returns
  HTTP 200 for writes it discards.
- **Idempotent.** Adding someone already on the list returns the list unchanged rather than
  duplicating them.
- **Parse the `value` side, never `display_value`.** With `sysparm_display_value=all` both come
  back comma-separated. Backing values are 32-character hex sys_ids, so splitting is safe.
  Display names are not — a name like `Smith, Andrew` would split into two entries and silently
  mis-pair every name after it. For names, `GET /sys_user/{sys_id}` works through the gateway
  (Spike attempt 2); that endpoint is useless for *adding* people but correct for *displaying*
  them.
- **`HtmlServiceNow` counterparts belong in the same PR.** PR 1 shipped `get_comments` and
  `post_comment` without them and both raised `AttributeError`, because that class has no
  `self.session` by design. `watch_list` is not in the HTML export, so `get_watchers` returns
  `[]` and `add_watcher` is a no-op.
- **The test that matters starts from a NON-EMPTY watch list.** An empty one cannot tell
  appending from overwriting, so the obvious test passes against a destructive implementation.

Two decisions taken 2026-11-26:

- **`add_watcher` is NOT behind `ALLOW_COMMENTS_ON_SN_TICKETS`.** That gate exists to stop text
  reaching a researcher; adding a watcher sends no mail. Noted for the record: it is not inert
  either, since the new watcher will receive mail the next time *anyone*, including a human
  operator, comments on the ticket. Revisit if that proves surprising in practice.
- **`watch_list` is NOT added to the `Ticket` dataclass.** The user prompt is the full ticket
  serialised as JSON, so a field there would put watchers' names into every LLM prompt — prompt
  bloat and personal data, for something no tool reads. Fetch on demand instead.

**`remove_watcher` was deferred, then un-deferred — the integration test needs it.** Without
it that test is only honest once: the first run leaves the watcher on the ticket, so every
later run finds them already present, appends nothing, and silently decays into a test of
idempotency while still passing. Establishing the precondition requires removal, so the
"nothing needs it yet" argument was wrong — the test does.

It takes a **sys_id, not an email**. The stored list holds sys_ids, and matching an email
against them would need the reverse lookup the gateway does not expose. `add_watcher` can
take either because ServiceNow does that resolution server-side on write; removal has no
equivalent, so the asymmetry is real rather than an oversight and belongs in the docstring.

The integration test's own identifiers live in an uncommitted fixture
(`tests/fixtures/local_watch_list.json`, gitignored) holding both the email and the sys_id of
someone who has agreed to be used for testing: the email so the run exercises server-side
resolution, the sys_id so the test can assert and clean up exactly. The test skips when the
file is absent, so it is a no-op for anyone who has not set one up.

### PR 2 — templates, and wiring into existing tools

The spike is now answered (attempt 2), so this is unblocked bar the arranged production test.
Constraints on it:

- **The first production comment must be a single manual invocation**, not a tool run. The
  first email to a researcher should be deliberate and watched. This is also the run that
  confirms who actually receives mail.
- **Put `post_comment()` behind a config toggle.** Done — `ALLOW_COMMENTS_ON_SN_TICKETS` in
  `servicenow.py`, which `post_comment()` raises on when False. Note that nothing *enforces*
  that a caller checks the flag first: a tool that forgets will crash rather than degrade.
  Tools that want to degrade gracefully (posting a work note instead, say) must read the flag
  and decide before calling.
- **Adding a watcher needs its own wrapper, and it must read–modify–write.** See Spike attempt
  2, constraint 1. This is the one place in the feature where the obvious implementation is
  silently destructive, so it wants a test that starts from a non-empty watch list — an empty
  one cannot tell appending from overwriting.
- **Watch list before comment.** The notification fires on the comment; a watcher added
  afterwards gets nothing.

### Then `set-ticket-state`

By which point it is either unblocked or escalated to the ServiceNow administrators.
