"""Read and write rcpond ticket dump files (jsonl).

A dump file is one JSON object per line. The first line is a header describing the dump;
every subsequent line is one ticket record, ``{"type_key": ..., "ticket": {...}}``.

Public API
----------
- ``SCHEMA_VERSION``: the format version this module reads and writes.
- ``write_dump(path, tickets, ...)``: write full tickets, sorted by ticket number.
- ``load_dump(path)``: read one back.
- ``DumpFile``, ``DumpHeader``, ``DumpedTicket``, ``TypeKeyDrift``: the returned shapes.

Return types
------------
``write_dump`` returns the number of ticket records written. ``load_dump`` returns a
``DumpFile`` holding the parsed header, the tickets paired with their stored ``type_key``,
and any type-key drift noticed on the way.

Configuration
-------------
None. The provenance values recorded in the header are passed in by the caller.

Scope
-----
This module owns anything that knows the dump file's *shape*: header fields, the version
policy, rehydration, validation. It deliberately does not own anything that merely *uses*
dumped tickets — analytics aggregation, CLI flag parsing, or the default output filename,
which is ``dump-tickets``' user interface rather than part of the format.

It must not import pandas. ``pandas`` is in the ``html`` optional extra, and
``dump-tickets`` is a core command that cannot be made to depend on an optional one.

See planning/ticket-dump.md.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from rcpond.servicenow import _TICKET_TYPES, Ticket, ticket_type_key

## --------------------------------------------------------------------------------
## Interface to this module

SCHEMA_VERSION = 1
"""The dump format version this module reads and writes.

A single integer, bumped only on a breaking change — a field removed, renamed, or given a
different meaning. Adding a field is not breaking: unknown header fields are ignored and
unknown record fields are dropped on load, so adding a catalogue variable to a ticket type
does not invalidate dumps already written.

There is no migration layer and no promise to read any other version. When this is bumped,
the CHANGELOG records which rcpond version wrote which ``schema_version``, and that is what
a user consults to find a version able to read an older dump.
"""


@dataclass(frozen=True)
class DumpHeader:
    """The first line of a dump file: what this dump is, and where it came from."""

    schema_version: int
    """Format version; see ``SCHEMA_VERSION``."""
    created_at: str
    """When the dump was taken. ISO 8601 in UTC, e.g. ``2026-11-07T14:53:21+00:00``."""
    servicenow_url: str
    """API base URL the tickets were fetched from."""
    servicenow_web_url: str
    """Web UI base URL of the same instance."""
    query: str
    """The ServiceNow query actually sent."""
    registry_ticket_types: list[str]
    """Registered ticket type keys at the time of the dump."""
    record_count: int
    """Number of ticket lines following the header."""
    limit: int | None
    """The ``--limit`` value if one was applied, else ``None``."""


@dataclass(frozen=True)
class DumpedTicket:
    """One ticket record: the ticket, and the type key stored alongside it."""

    type_key: str
    """The registry key this ticket was classified as *at dump time*. Authoritative."""
    ticket: Ticket
    """The rehydrated ticket: an instance of the registered subclass for ``type_key``."""


@dataclass(frozen=True)
class TypeKeyDrift:
    """A record whose stored ``type_key`` disagrees with what the registry derives today."""

    number: str
    """Ticket number."""
    stored: str
    """The key recorded in the dump. This is the one used."""
    derived: str | None
    """What ``ticket_type_key()`` says now; ``None`` when it matches no registered type."""


@dataclass(frozen=True)
class DumpFile:
    """A loaded dump file."""

    header: DumpHeader
    """The parsed header."""
    tickets: list[DumpedTicket]
    """Ticket records, in the order they appear in the file."""
    type_key_drift: list[TypeKeyDrift]
    """Records whose stored key no longer matches the registry. Informational only."""


def write_dump(
    path: Path,
    tickets: list[Ticket],
    *,
    servicenow_url: str,
    servicenow_web_url: str,
    query: str,
    limit: int | None = None,
    created_at: datetime | None = None,
) -> int:
    """Write ``tickets`` to ``path`` as a dump file.

    Records are sorted by ticket number, so two dumps of one instance diff as the tickets
    that changed rather than as everything having moved. The file is written in a single
    pass: ``record_count`` lives in the header, which is line 1, so the count has to be
    known before anything is written.

    Parameters
    ----------
    path : Path
        File to write. An existing file is overwritten — the clobber check belongs to the
        caller, which makes it before fetching anything.
    tickets : list[Ticket]
        Full tickets: instances of registered subclasses. Every one must match a
        registered type.
    servicenow_url : str
        API base URL, recorded in the header.
    servicenow_web_url : str
        Web UI base URL, recorded in the header.
    query : str
        The ServiceNow query that produced these tickets, recorded in the header.
    limit : int | None
        The ``--limit`` the caller applied, if any. Recorded so a deliberately partial
        dump is distinguishable from a complete one.
    created_at : datetime | None
        Dump timestamp, defaulting to now. Converted to UTC.

    Returns
    -------
    int
        The number of ticket records written.

    Raises
    ------
    ValueError
        If any ticket matches no registered type, and so has no ``type_key`` to record.
    """
    stamped = (created_at or datetime.now(UTC)).astimezone(UTC)

    records = []
    for ticket in sorted(tickets, key=lambda t: t.number):
        type_key = ticket_type_key(ticket)
        if type_key is None:
            msg = (
                f"Cannot dump ticket {ticket.number}: it matches no registered ticket type "
                f"(short_description={ticket.short_description!r}). "
                f"Known types: {', '.join(sorted(_TICKET_TYPES))}"
            )
            raise ValueError(msg)
        records.append({"type_key": type_key, "ticket": dataclasses.asdict(ticket)})

    header = {
        "schema_version": SCHEMA_VERSION,
        "created_at": stamped.isoformat(),
        "servicenow_url": servicenow_url,
        "servicenow_web_url": servicenow_web_url,
        "query": query,
        "registry_ticket_types": sorted(_TICKET_TYPES),
        "record_count": len(records),
        "limit": limit,
    }

    with Path(path).open("w") as f:
        for obj in (header, *records):
            f.write(json.dumps(obj) + "\n")

    return len(records)


def load_dump(path: Path) -> DumpFile:
    """Read a dump file written by ``write_dump``.

    The header is validated before any record is read, so an unreadable dump fails at once
    rather than part way through.

    The stored ``type_key`` is authoritative: it records what the ticket was classified as
    at dump time, and is used as-is rather than re-derived. Re-deriving would mean a single
    ``MATCH_CRITERIA`` change silently emptied every dump already written.

    Parameters
    ----------
    path : Path
        The dump file to read.

    Returns
    -------
    DumpFile

    Raises
    ------
    ValueError
        If the file is empty, has no header, carries a different ``schema_version``, names
        a ticket type this rcpond does not have, or its ``record_count`` disagrees with the
        records that follow.
    """
    lines = [line for line in Path(path).read_text().splitlines() if line.strip()]
    if not lines:
        msg = f"{path} is empty. An rcpond dump begins with a header line."
        raise ValueError(msg)

    header = _parse_header(lines[0], path)
    _check_registry(header, path)

    records = [json.loads(line) for line in lines[1:]]
    if header.record_count != len(records):
        msg = (
            f"{path} is incomplete: the header gives record_count={header.record_count}, but the "
            f"file holds {len(records)} record(s). The dump was probably truncated, or its write "
            f"was interrupted."
        )
        raise ValueError(msg)

    tickets: list[DumpedTicket] = []
    drift: list[TypeKeyDrift] = []
    for record in records:
        dumped = _rehydrate(record, path)
        tickets.append(dumped)
        ## Recorded, not acted on: the stored key wins. A disagreement means MATCH_CRITERIA
        ## has changed since the dump, which is worth reporting and otherwise invisible.
        derived = ticket_type_key(dumped.ticket)
        if derived != dumped.type_key:
            drift.append(TypeKeyDrift(number=dumped.ticket.number, stored=dumped.type_key, derived=derived))

    return DumpFile(header=header, tickets=tickets, type_key_drift=drift)


## --------------------------------------------------------------------------------
## Internals


def _parse_header(line: str, path: Path) -> DumpHeader:
    """Parse and version-check the first line.

    Parameters
    ----------
    line : str
        The file's first line.
    path : Path
        Only for error messages.

    Returns
    -------
    DumpHeader

    Raises
    ------
    ValueError
        If the line is not a JSON object, carries no ``schema_version``, or carries one
        this module does not read.
    """
    try:
        raw = json.loads(line)
    except json.JSONDecodeError as exc:
        msg = f"{path} does not begin with a JSON header line: {exc}"
        raise ValueError(msg) from exc

    if not isinstance(raw, dict) or "schema_version" not in raw:
        msg = (
            f"{path} is not an rcpond dump: its first line carries no 'schema_version'. "
            f"A dump begins with a header object — files written by "
            f"scripts/time_full_ticket_dump.py have no header and are not dumps."
        )
        raise ValueError(msg)

    version = raw["schema_version"]
    if version != SCHEMA_VERSION:
        written_by = "a later" if isinstance(version, int) and version > SCHEMA_VERSION else "an earlier"
        msg = (
            f"{path} has schema_version {version}; this rcpond reads schema_version "
            f"{SCHEMA_VERSION}. The dump was written by {written_by} version of rcpond, and there "
            f"is no support for reading other schema versions. See CHANGELOG.md for the rcpond "
            f"version that writes schema_version {version}."
        )
        raise ValueError(msg)

    ## Unknown keys are dropped rather than rejected: that is what lets a field be added to
    ## the header without bumping schema_version.
    known = {f.name for f in dataclasses.fields(DumpHeader)}
    return DumpHeader(**{k: v for k, v in raw.items() if k in known})


def _check_registry(header: DumpHeader, path: Path) -> None:
    """Fail if the dump names ticket types this rcpond does not have.

    Only this direction is an error. Types in the registry that the header lacks mean the
    dump simply predates them being registered — the common case as the registry grows, and
    harmless, since the dump never claimed to hold them.

    Parameters
    ----------
    header : DumpHeader
        The parsed header.
    path : Path
        Only for error messages.

    Raises
    ------
    ValueError
        If the header lists a ticket type key absent from the registry.
    """
    unknown = sorted(set(header.registry_ticket_types) - set(_TICKET_TYPES))
    if unknown:
        msg = (
            f"{path} was written by an rcpond that knows ticket type(s) this one does not: "
            f"{', '.join(unknown)}. It may hold records that cannot be read here. "
            f"Known types: {', '.join(sorted(_TICKET_TYPES))}"
        )
        raise ValueError(msg)


def _rehydrate(record: dict, path: Path) -> DumpedTicket:
    """Build the registered subclass named by the record's ``type_key``.

    The payload is filtered and filled rather than splatted into the constructor: a
    dataclass rejects unknown keyword arguments *and* requires every field without a
    default, so a dump written either side of a field being added would otherwise raise a
    bare ``TypeError``. Neither case bumps ``schema_version``, so neither is caught by the
    version check.

    Parameters
    ----------
    record : dict
        One parsed ticket line.
    path : Path
        Only for error messages.

    Returns
    -------
    DumpedTicket

    Raises
    ------
    ValueError
        If ``type_key`` names no registered type, leaving no class to rehydrate into.
    """
    type_key = record.get("type_key")
    if type_key not in _TICKET_TYPES:
        msg = (
            f"{path} holds a record of unknown ticket type {type_key!r}. "
            f"Known types: {', '.join(sorted(_TICKET_TYPES))}"
        )
        raise ValueError(msg)

    ticket_class = _TICKET_TYPES[type_key]
    payload = record.get("ticket", {})
    ## Every ticket field is a str, so "" is the natural stand-in for one the dump lacks.
    values = {f.name: payload.get(f.name, "") for f in dataclasses.fields(ticket_class)}
    return DumpedTicket(type_key=type_key, ticket=ticket_class(**values))
