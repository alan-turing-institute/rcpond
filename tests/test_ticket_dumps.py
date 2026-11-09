"""Tests for the ticket dump file format — writing, reading, and the compatibility rules.

Fully offline: no ServiceNow, no network, no pandas. That is the point of keeping both
halves of the format in one module — the round trip is testable on its own.

See planning/ticket-dump.md for the format and the rules asserted here.
"""

import dataclasses
import json
from datetime import UTC, datetime

import pytest

from rcpond.servicenow import (
    _TICKET_TYPES,
    ComputeAllocationRequestTicket,
    GitHubOnboardingRequestTicket,
    Ticket,
    ticket_type_key,
)
from rcpond.ticket_dumps import SCHEMA_VERSION, load_dump, write_dump

_BASE_FIELDS = {f.name for f in dataclasses.fields(Ticket)}


def _base(number: str, short_description: str, **overrides) -> Ticket:
    values = {
        "sys_id": f"sys-{number}",
        "number": number,
        "opened_at": "01/01/2026 09:00:00",
        "requested_for": "Ada Example",
        "u_category": "",
        "u_sub_category": "",
        "short_description": short_description,
        "state": "New",
        "assigned_to": "",
        "work_notes": "",
        "comments": "",
    }
    values.update(overrides)
    return Ticket(**values)


def _full(cls, number: str, **overrides) -> Ticket:
    """Build a full ticket of ``cls`` with every extra field populated."""
    criteria = dict(cls.MATCH_CRITERIA)
    base = _base(number, criteria["short_description"])
    extra = {f.name: f"{f.name}-value" for f in dataclasses.fields(cls) if f.name not in _BASE_FIELDS}
    extra.update(overrides)
    return cls.from_Ticket(base, **extra)


def _cart(number: str, **overrides) -> Ticket:
    return _full(ComputeAllocationRequestTicket, number, **overrides)


def _onboarding(number: str, **overrides) -> Ticket:
    return _full(GitHubOnboardingRequestTicket, number, **overrides)


def _write(path, tickets, **kwargs):
    """write_dump with the provenance arguments defaulted."""
    kwargs.setdefault("servicenow_url", "https://api.example.invalid/table")
    kwargs.setdefault("servicenow_web_url", "https://example.service-now.com")
    kwargs.setdefault("query", "short_description=A^ORshort_description=B")
    return write_dump(path, tickets, **kwargs)


def _read_lines(path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def _write_raw(path, header: dict, records: list[dict]) -> None:
    """Write a dump file verbatim, for cases a well-behaved writer cannot produce."""
    lines = [json.dumps(header), *[json.dumps(r) for r in records]]
    path.write_text("\n".join(lines) + "\n")


def _valid_header(**overrides) -> dict:
    header = {
        "schema_version": SCHEMA_VERSION,
        "created_at": "2026-11-07T14:53:21+00:00",
        "servicenow_url": "https://api.example.invalid/table",
        "servicenow_web_url": "https://example.service-now.com",
        "query": "short_description=A",
        "registry_ticket_types": ["compute_allocation_request"],
        "record_count": 0,
        "limit": None,
    }
    header.update(overrides)
    return header


def _record(ticket: Ticket, type_key: str | None = None, **ticket_overrides) -> dict:
    payload = dataclasses.asdict(ticket)
    payload.update(ticket_overrides)
    return {"type_key": type_key or ticket_type_key(ticket), "ticket": payload}


## ── Writing: header ─────────────────────────────────────────────────────────


def test_header_is_the_first_line_and_records_follow(tmp_path):
    path = tmp_path / "dump.jsonl"
    _write(path, [_cart("RES0000002"), _cart("RES0000001")])

    lines = _read_lines(path)

    assert lines[0]["schema_version"] == SCHEMA_VERSION
    ## Records carry type_key/ticket; the header does not, so the two are unambiguous.
    assert [line["type_key"] for line in lines[1:]] == ["compute_allocation_request"] * 2


def test_header_records_provenance(tmp_path):
    """Each asserted value is deliberately unlike the `_write` defaults.

    Reusing a default would leave it unclear whether the header carried the value passed
    here or simply whatever the helper supplies.
    """
    path = tmp_path / "dump.jsonl"
    _write(
        path,
        [_cart("RES0000001")],
        servicenow_url="https://api-under-test.invalid/table",
        servicenow_web_url="https://web-under-test.invalid",
        query="short_description=Under test",
    )

    header = _read_lines(path)[0]

    assert header["servicenow_url"] == "https://api-under-test.invalid/table"
    assert header["servicenow_web_url"] == "https://web-under-test.invalid"
    assert header["query"] == "short_description=Under test"


def test_header_records_the_registry_at_dump_time(tmp_path):
    """A reader cannot otherwise tell which types were deliberately excluded."""
    path = tmp_path / "dump.jsonl"
    _write(path, [_cart("RES0000001")])

    header = _read_lines(path)[0]

    assert "compute_allocation_request" in header["registry_ticket_types"]
    ## Every registered type, not merely the ones that happened to have tickets.
    assert "github_onboarding_request" in header["registry_ticket_types"]


def test_header_record_count_matches_the_lines_written(tmp_path):
    path = tmp_path / "dump.jsonl"
    _write(path, [_cart("RES0000001"), _cart("RES0000002"), _onboarding("RES0000003")])

    lines = _read_lines(path)

    assert lines[0]["record_count"] == 3
    assert len(lines[1:]) == 3


@pytest.mark.parametrize(
    ("limit", "expected"),
    [(None, None), (20, 20)],
    ids=["no_limit_is_null", "limit_recorded"],
)
def test_header_records_whether_a_limit_was_applied(tmp_path, limit, expected):
    """Without this, a partial dump is indistinguishable from a complete one.

    The filename cannot carry it: --output-file names the file in that case.
    """
    path = tmp_path / "dump.jsonl"
    _write(path, [_cart("RES0000001")], limit=limit)

    assert _read_lines(path)[0]["limit"] == expected


def test_created_at_is_iso_8601_in_utc(tmp_path):
    """Always UTC with an explicit +00:00, so dumps from different machines compare directly."""
    path = tmp_path / "dump.jsonl"
    _write(path, [_cart("RES0000001")])

    created_at = _read_lines(path)[0]["created_at"]
    parsed = datetime.fromisoformat(created_at)

    assert created_at.endswith("+00:00")
    assert parsed.utcoffset().total_seconds() == 0
    ## Not the ServiceNow display format, which carries no timezone at all.
    assert parsed.tzinfo is not None


def test_created_at_can_be_supplied(tmp_path):
    """Injectable so the rest of the suite is not timing-dependent."""
    path = tmp_path / "dump.jsonl"
    _write(path, [_cart("RES0000001")], created_at=datetime(2026, 11, 6, 14, 53, 21, tzinfo=UTC))

    assert _read_lines(path)[0]["created_at"] == "2026-11-06T14:53:21+00:00"


## ── Writing: records ────────────────────────────────────────────────────────


def test_records_are_sorted_by_ticket_number(tmp_path):
    """ServiceNow's order is not stable between runs; sorting makes two dumps diffable."""
    path = tmp_path / "dump.jsonl"
    _write(path, [_cart("RES0000003"), _cart("RES0000001"), _cart("RES0000002")])

    numbers = [line["ticket"]["number"] for line in _read_lines(path)[1:]]

    assert numbers == ["RES0000001", "RES0000002", "RES0000003"]


def test_records_carry_the_full_ticket_fields(tmp_path):
    """A base-ticket dump would be useless to evaluate, which needs the catalogue variables."""
    path = tmp_path / "dump.jsonl"
    _write(path, [_cart("RES0000001")])

    payload = _read_lines(path)[1]["ticket"]

    assert payload["which_service"] == "which_service-value"
    assert payload["project_title"] == "project_title-value"


def test_write_rejects_a_ticket_matching_no_registered_type(tmp_path):
    """type_key is the record's ground truth, so there is nothing to write without one."""
    path = tmp_path / "dump.jsonl"
    stray = _base("RES0000009", "Something nobody registered")

    with pytest.raises(ValueError, match="RES0000009"):
        _write(path, [stray])


## ── Round trip ──────────────────────────────────────────────────────────────


def test_round_trip_preserves_tickets_their_subclass_and_their_type_key(tmp_path):
    """The single most important property of the format.

    The type key is asserted here rather than in a test of its own: it comes back from the
    same round trip, and Step 2 needs it alongside the ticket because the stored key is
    authoritative rather than re-derived.
    """
    path = tmp_path / "dump.jsonl"
    written = [_cart("RES0000001"), _onboarding("RES0000002")]
    _write(path, written)

    loaded = load_dump(path)

    assert [d.ticket for d in loaded.tickets] == written
    assert [type(d.ticket) for d in loaded.tickets] == [
        ComputeAllocationRequestTicket,
        GitHubOnboardingRequestTicket,
    ]
    assert [d.type_key for d in loaded.tickets] == [
        "compute_allocation_request",
        "github_onboarding_request",
    ]


def test_round_trip_preserves_the_header(tmp_path):
    path = tmp_path / "dump.jsonl"
    _write(path, [_cart("RES0000001")], limit=5, created_at=datetime(2026, 11, 7, 14, 53, 21, tzinfo=UTC))

    header = load_dump(path).header

    assert header.schema_version == SCHEMA_VERSION
    assert header.created_at == "2026-11-07T14:53:21+00:00"
    assert header.record_count == 1
    assert header.limit == 5


## ── Reading: filter and fill ────────────────────────────────────────────────


def test_unknown_record_fields_are_dropped(tmp_path):
    """A dump from a later RCPond that added a catalogue variable must still load.

    Without this the dataclass constructor raises 'unexpected keyword argument', and the
    schema_version check does not catch it because adding a field is not a bump.
    """
    path = tmp_path / "dump.jsonl"
    record = _record(_cart("RES0000001"), field_added_in_a_later_version="surprise")
    _write_raw(path, _valid_header(record_count=1), [record])

    ## The premise, asserted rather than described: splatting the payload straight into
    ## the constructor is what the loader must not do.
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        ComputeAllocationRequestTicket(**record["ticket"])

    loaded = load_dump(path)

    assert loaded.tickets[0].ticket.number == "RES0000001"
    assert not hasattr(loaded.tickets[0].ticket, "field_added_in_a_later_version")


def test_missing_record_fields_are_filled_with_empty_strings(tmp_path):
    """A dump from an earlier RCPond, read after a field was added, must still load.

    Without this the constructor raises 'missing required positional argument'.
    """
    path = tmp_path / "dump.jsonl"
    payload = dataclasses.asdict(_cart("RES0000001"))
    del payload["which_service"]
    record = {"type_key": "compute_allocation_request", "ticket": payload}
    _write_raw(path, _valid_header(record_count=1), [record])

    ## The premise, asserted rather than described: the field has no default, so the
    ## constructor rejects the payload outright unless the loader fills it.
    with pytest.raises(TypeError, match="which_service"):
        ComputeAllocationRequestTicket(**payload)

    loaded = load_dump(path)

    assert loaded.tickets[0].ticket.which_service == ""


## ── Reading: header validation ──────────────────────────────────────────────


def test_rejects_a_file_with_no_schema_version(tmp_path):
    """Catches a file that is not an rcpond dump at all — including script output."""
    path = tmp_path / "dump.jsonl"
    header = _valid_header()
    del header["schema_version"]
    _write_raw(path, header, [])

    with pytest.raises(ValueError, match="schema_version"):
        load_dump(path)


def test_rejects_a_file_whose_first_line_is_a_ticket_record(tmp_path):
    """The headerless shape the timing script writes must not half-work."""
    path = tmp_path / "dump.jsonl"
    path.write_text(json.dumps(_record(_cart("RES0000001"))) + "\n")

    with pytest.raises(ValueError, match="schema_version"):
        load_dump(path)


def test_rejects_an_empty_file(tmp_path):
    path = tmp_path / "dump.jsonl"
    path.write_text("")

    with pytest.raises(ValueError, match="empty"):
        load_dump(path)


@pytest.mark.parametrize(
    "version",
    [SCHEMA_VERSION + 1, SCHEMA_VERSION - 1],
    ids=["newer_dump", "older_dump"],
)
def test_rejects_any_other_schema_version(tmp_path, version):
    """Only the version this reader was written for is accepted — no migration layer.

    Both directions error, and the message names both versions so the user can find the
    rcpond version that wrote it from the changelog.
    """
    path = tmp_path / "dump.jsonl"
    _write_raw(path, _valid_header(schema_version=version), [])

    with pytest.raises(ValueError, match=rf"{version}\b.*\b{SCHEMA_VERSION}\b|{SCHEMA_VERSION}\b.*\b{version}\b"):
        load_dump(path)


def test_unknown_header_fields_are_ignored(tmp_path):
    """Fields can be added without a schema_version bump — that is the whole policy."""
    path = tmp_path / "dump.jsonl"
    _write_raw(path, _valid_header(some_future_field="ignore me"), [])

    assert load_dump(path).header.schema_version == SCHEMA_VERSION


def test_rejects_a_record_count_that_disagrees_with_the_lines(tmp_path):
    """A truncated or interrupted write would otherwise yield a quietly narrowed report."""
    path = tmp_path / "dump.jsonl"
    _write_raw(path, _valid_header(record_count=5), [_record(_cart("RES0000001"))])

    with pytest.raises(ValueError, match="record_count"):
        load_dump(path)


def test_a_limited_dump_is_valid_not_an_error(tmp_path):
    """--limit produces a deliberately partial dump; the report says so, the loader allows it."""
    path = tmp_path / "dump.jsonl"
    _write(path, [_cart("RES0000001")], limit=1)

    loaded = load_dump(path)

    assert loaded.header.limit == 1
    assert len(loaded.tickets) == 1


## ── Reading: the registry ───────────────────────────────────────────────────


def test_rejects_a_header_type_the_registry_does_not_have(tmp_path):
    """The dump may hold records this rcpond cannot rehydrate, so fail before reading any."""
    path = tmp_path / "dump.jsonl"
    _write_raw(
        path,
        _valid_header(registry_ticket_types=["compute_allocation_request", "type_from_the_future"]),
        [],
    )

    with pytest.raises(ValueError, match="type_from_the_future"):
        load_dump(path)


def test_accepts_a_registry_with_types_the_header_lacks(tmp_path):
    """The benign direction: the dump simply predates that type being registered.

    This is the common case as the registry grows — every dump taken today becomes an
    instance of it the next time a ticket type is added — so erroring here would make
    adding a type invalidate every existing dump.
    """
    ## The premise: the registry must hold more types than the header lists, or this
    ## asserts nothing. Registering a fourth type would otherwise quietly neuter it.
    assert len(_TICKET_TYPES) > 1

    path = tmp_path / "dump.jsonl"
    _write_raw(
        path,
        _valid_header(registry_ticket_types=["compute_allocation_request"], record_count=1),
        [_record(_cart("RES0000001"))],
    )

    loaded = load_dump(path)

    assert len(loaded.tickets) == 1


def test_rejects_a_record_whose_type_key_is_not_registered(tmp_path):
    """There is no class to rehydrate it into."""
    path = tmp_path / "dump.jsonl"
    record = _record(_cart("RES0000001"), type_key="type_from_the_future")
    ## Header lists only known types, so the record is what fails, not the header check.
    _write_raw(path, _valid_header(record_count=1), [record])

    with pytest.raises(ValueError, match="type_from_the_future"):
        load_dump(path)


## ── Reading: the stored type_key is authoritative ───────────────────────────


def test_stored_type_key_wins_when_match_criteria_have_drifted(tmp_path):
    """A MATCH_CRITERIA change must not break dump files already written.

    Re-deriving the type would classify this record as nothing at all, and
    build_ticket_frame silently drops those — so an entire dump would vanish from the
    report with no error. The stored key was correct when written, so it is used as-is.
    """
    path = tmp_path / "dump.jsonl"
    ## Simulates ServiceNow rewording short_description after the dump was taken.
    drifted = _record(_cart("RES0000001"), short_description="Wording that no longer matches")
    _write_raw(path, _valid_header(record_count=1), [drifted])

    loaded = load_dump(path)

    assert loaded.tickets[0].type_key == "compute_allocation_request"
    assert isinstance(loaded.tickets[0].ticket, ComputeAllocationRequestTicket)
    ## The re-derivation that would have been used instead finds nothing.
    assert ticket_type_key(loaded.tickets[0].ticket) is None


def test_drift_is_reported_as_a_warning(tmp_path):
    """Drift no longer threatens correctness, but it is worth knowing and otherwise invisible."""
    path = tmp_path / "dump.jsonl"
    drifted = _record(_cart("RES0000001"), short_description="Wording that no longer matches")
    _write_raw(path, _valid_header(record_count=1), [drifted])

    loaded = load_dump(path)

    assert len(loaded.type_key_drift) == 1
    drift = loaded.type_key_drift[0]
    assert drift.number == "RES0000001"
    assert drift.stored == "compute_allocation_request"
    assert drift.derived is None


def test_no_drift_reported_when_the_keys_agree(tmp_path):
    path = tmp_path / "dump.jsonl"
    _write(path, [_cart("RES0000001"), _onboarding("RES0000002")])

    assert load_dump(path).type_key_drift == []
