# Post comments

**Status: DRAFT.** Decisions taken; ready to start PR 1.

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

### Step 3 - Notifying and tagging users

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

With the ServiceNow WebUI, it is possible to tag individuals or groups. Ideally it would be
possible to specify user-identifiers in the jinja templates and that these users/groups will be
tagged when the message is posted. Some experimentation is required to test if/how this can be
achieved; the spike under Sequencing defines what counts as an answer.

For testing:
 - on the Dev instance, tagging is possible, but email notifications are disabled.
 - on the Production instance, email notifications are enabled. A specific ticket and willing
   test user can be arranged in due course.

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

### Spike, in parallel — can the Table API tag a user?

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

### PR 2 — templates, and wiring into existing tools

Needs the spike result, and needs the arranged production test before anything runs
unattended. Two constraints on it:

- **The first production comment must be a single manual invocation**, not a tool run. The
  first email to a researcher should be deliberate and watched. This is also the run that
  confirms who actually receives mail.
- **Put `post_comment()` behind a config toggle.** This is the first thing RCPond does that
  reaches a researcher; a flag disables it in production without needing a revert. The repo
  already has the pattern (`MATCH_ON_CORE_FUNDING_FINANCE` in `servicenow.py`).

### Then `set-ticket-state`

By which point it is either unblocked or escalated to the ServiceNow administrators.
