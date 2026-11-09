"""Tests for `command.dump_tickets` — the orchestration around the dump file format.

The format itself is covered by tests/test_ticket_dumps.py. What matters here is the
ordering of the steps: the clobber check runs before the query, the sort runs before the
`--limit` slice, and a single failed fetch abandons the whole run.

Fully offline: ServiceNow is patched at its import site in `command`.

See planning/ticket-dump.md Step 1.
"""

import dataclasses
import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from rcpond import command
from rcpond.servicenow import (
    ComputeAllocationRequestTicket,
    Ticket,
    TicketState,
    all_registered_types_query,
)

_BASE_FIELDS = {f.name for f in dataclasses.fields(Ticket)}
_CART_DESC = ComputeAllocationRequestTicket.MATCH_CRITERIA["short_description"]


def _base(number: str) -> Ticket:
    return Ticket(
        sys_id=f"sys-{number}",
        number=number,
        opened_at="01/01/2026 09:00:00",
        requested_for="Ada Example",
        u_category="",
        u_sub_category="",
        short_description=_CART_DESC,
        state="New",
        assigned_to="",
        work_notes="",
        comments="",
    )


def _full(base: Ticket) -> ComputeAllocationRequestTicket:
    extra = {
        f.name: f"{f.name}-value"
        for f in dataclasses.fields(ComputeAllocationRequestTicket)
        if f.name not in _BASE_FIELDS
    }
    return ComputeAllocationRequestTicket.from_Ticket(base, **extra)


def _config() -> MagicMock:
    config = MagicMock()
    config.servicenow_url = "https://api.example.invalid/table"
    config.servicenow_web_url = "https://example.service-now.com"
    return config


def _service_now(tickets: list[Ticket], *, fail_on: str | None = None) -> MagicMock:
    """A ServiceNow stand-in returning ``tickets``, optionally failing one full fetch."""
    sn = MagicMock()
    sn.get_tickets.return_value = list(tickets)

    def _get_full(tkt: Ticket):
        if fail_on is not None and tkt.number == fail_on:
            ## Deliberately does not mention the ticket number: the command has to add
            ## that itself, or the assertion below would be satisfied by this text alone.
            msg = "the underlying transport exploded"
            raise ConnectionError(msg)
        return _full(tkt)

    sn.get_full_ticket.side_effect = _get_full
    return sn


def _run(tmp_path, tickets, *, limit=None, fail_on=None, out_file=None):
    """Invoke dump_tickets with ServiceNow patched; returns (path, mock_sn)."""
    sn = _service_now(tickets, fail_on=fail_on)
    path = out_file if out_file is not None else tmp_path / "dump.jsonl"
    with patch("rcpond.command.ServiceNow", return_value=sn):
        written = command.dump_tickets(out_file=path, limit=limit, config=_config())
    return written, sn


def _records(path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()[1:]]


def _header(path) -> dict:
    return json.loads(path.read_text().splitlines()[0])


## ── What gets fetched ───────────────────────────────────────────────────────


def test_fetches_every_registered_type_in_every_state(tmp_path):
    """The configured query is one type's, so without the explicit query the dump would
    silently hold only that type. Closed tickets are the bulk of the history."""
    _run(tmp_path, [_base("RES0000001")])[1].get_tickets.assert_called_once_with(
        state=TicketState.all_including_closed,
        query=all_registered_types_query(),
    )


def test_writes_full_tickets_not_base_tickets(tmp_path):
    """A base-ticket dump would be useless to evaluate, which needs the catalogue variables."""
    path = tmp_path / "dump.jsonl"
    _run(tmp_path, [_base("RES0000001")], out_file=path)

    assert _records(path)[0]["ticket"]["which_service"] == "which_service-value"


def test_returns_the_path_written(tmp_path):
    path = tmp_path / "dump.jsonl"
    written, _ = _run(tmp_path, [_base("RES0000001")], out_file=path)

    assert written == path
    assert path.exists()


## ── Sorting happens before the limit slice ──────────────────────────────────


def test_limit_takes_the_lowest_numbered_tickets_whatever_order_servicenow_returns(tmp_path):
    """Sorting before the slice is what makes --limit reproducible.

    Slicing ServiceNow's order first would sample a different set each run, since that
    order is not guaranteed stable.
    """
    path = tmp_path / "dump.jsonl"
    unsorted = [_base("RES0000005"), _base("RES0000001"), _base("RES0000003")]
    _run(tmp_path, unsorted, limit=2, out_file=path)

    assert [r["ticket"]["number"] for r in _records(path)] == ["RES0000001", "RES0000003"]


def test_limit_is_reproducible_across_different_servicenow_orderings(tmp_path):
    """The property the sort exists for, asserted directly rather than implied."""
    tickets = [_base("RES0000005"), _base("RES0000001"), _base("RES0000003")]

    first = tmp_path / "a.jsonl"
    second = tmp_path / "b.jsonl"
    _run(tmp_path, tickets, limit=2, out_file=first)
    _run(tmp_path, list(reversed(tickets)), limit=2, out_file=second)

    assert [r["ticket"]["number"] for r in _records(first)] == [r["ticket"]["number"] for r in _records(second)]


def test_limit_only_fetches_full_details_for_the_kept_tickets(tmp_path):
    """The fan-out is the expensive part; --limit exists to shorten it."""
    _, sn = _run(tmp_path, [_base("RES0000005"), _base("RES0000001"), _base("RES0000003")], limit=2)

    fetched = [call.args[0].number for call in sn.get_full_ticket.call_args_list]
    assert fetched == ["RES0000001", "RES0000003"]


def test_limit_is_recorded_in_the_header(tmp_path):
    path = tmp_path / "dump.jsonl"
    _run(tmp_path, [_base("RES0000001"), _base("RES0000002")], limit=1, out_file=path)

    assert _header(path)["limit"] == 1


def test_no_limit_dumps_everything_and_records_null(tmp_path):
    path = tmp_path / "dump.jsonl"
    _run(tmp_path, [_base("RES0000002"), _base("RES0000001")], out_file=path)

    assert _header(path)["limit"] is None
    assert len(_records(path)) == 2


## ── A failed fetch aborts the whole dump ────────────────────────────────────


def test_a_failed_full_fetch_aborts_and_writes_no_file(tmp_path):
    """A skipped ticket would make record_count under-count, leaving a silently partial
    dump indistinguishable from a complete one."""
    path = tmp_path / "dump.jsonl"
    tickets = [_base("RES0000001"), _base("RES0000002"), _base("RES0000003")]

    with pytest.raises(RuntimeError):
        _run(tmp_path, tickets, fail_on="RES0000002", out_file=path)

    assert not path.exists()


def test_the_abort_error_names_the_ticket_and_the_underlying_failure(tmp_path):
    """So a re-run is an informed choice rather than a guess.

    Both halves are asserted on `str(exc)`, which is what the CLI prints. Annotating the
    original exception with `add_note` would not satisfy this: notes are absent from
    `str()`, so the ticket number would be lost in exactly the output that needs it.
    """
    tickets = [_base("RES0000001"), _base("RES0000002")]

    with pytest.raises(RuntimeError) as excinfo:
        _run(tmp_path, tickets, fail_on="RES0000002")

    message = str(excinfo.value)
    assert "RES0000002" in message
    assert "the underlying transport exploded" in message
    ## The original exception stays reachable for anyone wanting the traceback.
    assert isinstance(excinfo.value.__cause__, ConnectionError)


## ── The clobber and directory checks precede the query ──────────────────────


def test_refuses_to_overwrite_an_existing_file(tmp_path):
    path = tmp_path / "dump.jsonl"
    path.write_text("do not clobber me\n")

    with pytest.raises(ValueError, match="exists"):
        _run(tmp_path, [_base("RES0000001")], out_file=path)

    assert path.read_text() == "do not clobber me\n"


def test_the_clobber_check_runs_before_any_ticket_is_fetched(tmp_path):
    """Checked up front because the fan-out takes ~70sec: discovering the path is
    unusable afterwards would waste the whole run."""
    path = tmp_path / "dump.jsonl"
    path.write_text("existing\n")
    sn = _service_now([_base("RES0000001")])

    with patch("rcpond.command.ServiceNow", return_value=sn), pytest.raises(ValueError, match="exists"):
        command.dump_tickets(out_file=path, config=_config())

    sn.get_tickets.assert_not_called()


def test_a_missing_output_directory_fails_before_any_ticket_is_fetched(tmp_path):
    path = tmp_path / "no_such_dir" / "dump.jsonl"
    sn = _service_now([_base("RES0000001")])

    with patch("rcpond.command.ServiceNow", return_value=sn), pytest.raises(ValueError, match="director"):
        command.dump_tickets(out_file=path, config=_config())

    sn.get_tickets.assert_not_called()


## ── Progress output ─────────────────────────────────────────────────────────


def test_reports_progress_while_fetching(tmp_path, capsys):
    """A ~70sec command that prints nothing looks hung."""
    _run(tmp_path, [_base(f"RES{n:07d}") for n in range(1, 12)])

    assert "11/11" in capsys.readouterr().out


def test_progress_updates_overwrite_one_another(tmp_path, capsys):
    """Each update rewrites one line; without this a long run scrolls hundreds of lines.

    Eleven tickets give two updates — one at ten, one at the end — so the carriage returns
    are countable. `rich.print` strips `\\r`, which is why progress is written straight to
    stdout; asserting only that the final count appears would not have caught that.
    """
    _run(tmp_path, [_base(f"RES{n:07d}") for n in range(1, 12)])

    out = capsys.readouterr().out

    assert out.count("\r") == 2
    ## One newline, written once the fan-out is done, so the next output starts cleanly.
    assert out.count("\n") == 1
    assert out.endswith("\n")


## ── The default output filename ─────────────────────────────────────────────


def test_default_filename_uses_the_web_domain_and_a_local_timestamp():
    """The domain identifies the instance; the timestamp makes collisions near-impossible.

    Colons are deliberately absent — unlike the header's `created_at`, this has to be a
    valid filename everywhere.
    """
    name = command.default_dump_filename(
        "https://alanturingdev.service-now.com",
        now=datetime(2026, 11, 7, 14, 53, 21),  # - local time, as the filename rule says
    )

    assert name == "alanturingdev.service-now.com_20261107T145321.jsonl"


def test_default_filename_is_used_when_no_output_file_is_given(tmp_path, monkeypatch):
    """The default lands in the CWD."""
    monkeypatch.chdir(tmp_path)
    sn = _service_now([_base("RES0000001")])

    with patch("rcpond.command.ServiceNow", return_value=sn):
        written = command.dump_tickets(config=_config())

    assert written.parent == tmp_path
    assert written.name.startswith("example.service-now.com_")
    assert written.suffix == ".jsonl"
    assert written.exists()
