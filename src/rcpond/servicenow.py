"""A limited interface to ServiceNow.

Provides a class, `ServiceNow`, which wraps the ServiceNow
API. The only methods are:

- `ServiceNow.get_tickets()`: Get a list of tickets. By default only unassigned tickets are returned, but all tickets can be selected;
- `ServiceNow.get_ticket()`: Get a single ticket by its ticket number (e.g. ``"RES0001234"``);
- `ServiceNow.get_full_ticket()`: Get full details of a ticket;
- `assign_to()` Assigns a ticket to the named user;
- `get_work_notes()` List the work notes for a specific ticket; and
- `post_note()` (Not implemented) Post a “work note” to a ticket.

Tickets are returned as instances of a `Ticket` dataclass which
contains a few, high-level details. The subclass `FullTicket` contains
,in addition, the fields submitted by the requestor on the request form.

The URL of the ServiceNow API is hardcoded, but you will need to
supply a user authentication token.

This version filters out all tickets that are not requests for HPC or
Azure resource.

Example use
-----------

>>> the_sn = ServiceNow("ab...def")
>>> the_sn.get_tickets()

"""

from __future__ import annotations

import base64
import dataclasses
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar

import requests

from rcpond import __version__ as rcpond_version
from rcpond.config import Config


@dataclass
class Ticket:
    """A ticket; contains only high-level details about the ticket."""

    sys_id: str
    """The internal ServiceNow identifier for the ticket."""
    number: str
    """The ticket number as recognised by agents."""
    opened_at: str
    """A timestamp, formatted as `DD/MM/YYYY HH:MM:SS` """
    requested_for: str
    u_category: str
    u_sub_category: str
    short_description: str
    state: str
    """Human-readable ticket state, e.g. 'New', 'In Progress', 'On Hold', 'Resolved', 'Closed'."""
    assigned_to: str
    """Display name of the assigned agent, or empty string if unassigned."""
    work_notes: str
    """Raw display_value string for work notes, as returned by the ServiceNow API."""
    comments: str
    """Raw display_value string for additional comments, as returned by the ServiceNow API."""

    _REFRESHABLE_FIELDS: ClassVar[frozenset[str]] = frozenset({"state", "assigned_to", "work_notes", "comments"})

    def assign_to_me(self, service_now: ServiceNow) -> None:
        """Assign this ticket to the currently authenticated OAuth user.

        Parameters
        ----------
        service_now : ServiceNow
            The ServiceNow client. Must be configured with OAuth credentials.

        Raises
        ------
        NotImplementedError
            If the ServiceNow client is using static token authentication.
        """
        service_now.assign_to_me(self)

    def get_combined_notes(self) -> list[NoteEntry]:
        """Return work notes and comments merged and sorted chronologically (oldest first).

        Returns
        -------
        list[NoteEntry]
            All entries from ``work_notes`` and ``comments``, sorted by timestamp.
            The most recent entry is ``result[-1]``; the list is empty when both
            fields are blank.
        """
        entries = _parse_comment_display_values(self.work_notes) + _parse_comment_display_values(self.comments)
        return sorted(entries, key=lambda e: e.datetime_stamp)

    def is_rcpond_processed(self) -> bool:
        """Returns `True` if RCPond (any version) has ever posted a Comment or Work Note on this ticket. `False` otherwise."""
        return any(_RCPOND_NOTE_RE.match(e.content) for e in self.get_combined_notes())

    def is_rcpond_most_recent_process(self) -> bool:
        """Returns `True` if the current version of RCPond posted the most recent Comment or Work Note on this ticket. `False` otherwise."""
        notes = self.get_combined_notes()
        return bool(notes) and notes[-1].content.startswith(_note_prefix())

    def refresh(self, service_now: ServiceNow) -> None:
        """Refresh mutable fields by re-querying the ServiceNow API.

        Parameters
        ----------
        service_now : ServiceNow
            The ServiceNow client used to fetch updated values.
        """
        values = service_now._fetch_fields(self.sys_id, set(self._REFRESHABLE_FIELDS))
        for field, value in values.items():
            setattr(self, field, value)


@dataclass(frozen=True)
class NoteEntry:
    """A single parsed work note or comment from a ServiceNow ticket."""

    datetime_stamp: datetime
    """Parsed timestamp of the note."""
    user: str
    """Display name of the author."""
    note_type: str
    """Note category as returned by ServiceNow, e.g. ``"Work notes"`` or ``"Comments"``."""
    content: str
    """Body text of the note, with the header line stripped."""


@dataclass
class FullTicket(Ticket):
    """A ticket; includes full details from the original submission."""

    project_title: str
    research_area_programme: str
    if_other_please_specify: str
    pi_supervisor_name: str
    pi_supervisor_email: str
    which_service: str
    subscription_type: str
    which_finance_code: str
    pmu_contact_email: str
    credits_requested: str
    which_facility: str
    if_other_please_specify_facility: str
    cpu_hours_required: str
    gpu_hours_required: str
    new_or_existing_allocation: str
    azure_subscription_id_or_hpc_group_project_id: str
    start_date: str
    end_date: str
    data_sensitivity: str
    platform_justification: str
    research_justification: str
    computational_requirements: str
    users_who_require_access_names_and_emails: str
    cost_compute_time_breakdown: str

    @classmethod
    def from_Ticket(cls, t: Ticket, **extras):
        """Create a new FullTicket starting from a Ticket and passing
        only the additional fields.
        """
        base = dataclasses.asdict(t)
        base.update(extras)
        return cls(**base)


## --------------------------------------------------------------------------------
## Utilities


def _note_prefix(version: str = rcpond_version) -> str:
    return f"[code]<b>RCPond v{version} generated response:</b>[/code]\n----\n"


## Matches the RCPond prefix for any version.
_RCPOND_NOTE_RE = re.compile(r"^\[code\]<b>RCPond v\S+ generated response:</b>\[/code\]")


## Extract, from the record returned from ServiceNow, the fields
## defined in Ticket. A value in the record is either a string,
## or a dictionary with keys "value", "display_value", and (sometimes)
## "link". We usually want "display_value".
def _extract_display_value(fld: dict | str) -> str:
    if isinstance(fld, dict):
        return fld.get("display_value", "")
    else:
        return fld


## tkt: The JSON from the API call (as a dictionary)
def _extract_ticket_fields(tkt: dict[str, dict | str], fields: set[str]) -> dict:
    return {field: _extract_display_value(tkt.get(field, "")) for field in fields}


def _parse_comment_display_values(input: str) -> list[NoteEntry]:
    """Parse a ServiceNow ``display_value`` string for work_notes or comments.

    Parameters
    ----------
    input : str
        The raw display_value string from ServiceNow, containing zero or more
        blocks separated by blank lines. Each block starts with a header line
        of the form ``"DD/MM/YYYY HH:MM:SS - User Name (Note type)"`` followed
        by one or more content lines.

    Returns
    -------
    list[NoteEntry]
        One entry per parsed block, in the order they appear in ``input``.
    """
    _HEADER = re.compile(r"^(\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}) - (.+?) \(([^)]+)\)$")
    result: list[NoteEntry] = []
    current_key: tuple[datetime, str, str] | None = None
    content_lines: list[str] = []

    def _flush() -> None:
        if current_key is not None:
            content = "\n".join(content_lines).rstrip("\n")
            result.append(NoteEntry(*current_key, content))

    for line in input.splitlines():
        m = _HEADER.match(line)
        if m:
            _flush()
            current_key = (datetime.strptime(m.group(1), "%d/%m/%Y %H:%M:%S"), m.group(2), m.group(3))
            content_lines = []
        elif current_key is not None:
            content_lines.append(line)

    _flush()
    return result


## --------------------------------------------------------------------------------
## Interface to this module


class ServiceNow:
    """Simple wrapper around limited parts of the ServiceNow API."""

    # ServiceNow configuration
    # _base_url = "https://turing-api.azure-api.net/dev-research/api/now/table"
    _TABLE = "x_tati_resmgt_research"

    def __init__(self, config: Config):
        self._base_api_url = config.servicenow_url
        self._web_base_url: str = config.servicenow_web_url
        self._id_token: str | None = None
        self._is_oauth = False
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json", "Accept": "application/json"})
        if config.servicenow_client_id and config.servicenow_client_secret:
            from rcpond.auth import get_bearer_token, get_id_token

            self.session.headers["Authorization"] = f"Bearer {get_bearer_token(config)}"
            self._id_token = get_id_token()
            self._is_oauth = True
        else:
            self.session.headers["Ocp-Apim-Subscription-Key"] = config.servicenow_token or ""

    def get_tickets(self, long_list: bool = False) -> list[Ticket]:
        """Get tickets that are applications for HPC/Azure credits.

        Parameters
        ----------
        long_list : bool
            If ``False`` (default), return a curated shortlist relevant to the
            current user or bot. If ``True``, return all non-closed/resolved tickets.

        Returns
        -------
        list[Ticket]
            For interactive (OAuth) users — shortlist: unassigned or assigned to the
            current user; longlist: all non-closed/resolved tickets.
            For bot (token) users — shortlist: unassigned tickets where RCPond has not
            posted the most recent note; longlist: all non-closed/resolved tickets where
            RCPond has not posted the most recent note.
        """
        _BASE_QUERY = "short_description=Request access to HPC and cloud computing facilities"
        _CLOSED_STATES = frozenset({"Closed", "Resolved", "Cancelled"})

        ticket_fields = {field.name for field in dataclasses.fields(Ticket)}
        resp = self.session.get(
            f"{self._base_api_url}/{self._TABLE}", params={"sysparm_query": _BASE_QUERY, "sysparm_display_value": "all"}
        )
        resp.raise_for_status()

        tickets = [Ticket(**_extract_ticket_fields(tkt, ticket_fields)) for tkt in resp.json()["result"]]
        ## Always exclude closed/resolved tickets; remaining filters depend on auth mode and long_list
        tickets = [t for t in tickets if t.state not in _CLOSED_STATES]

        if long_list:
            ## Bot longlist: exclude tickets RCPond already handled (OAuth sees everything)
            if not self._is_oauth:
                tickets = [t for t in tickets if not t.is_rcpond_processed()]
        else:
            if self._is_oauth:
                my_name = self._current_user_display_name()
                ## Interactive shortlist: only tickets assigned to me or unassigned
                tickets = [t for t in tickets if t.assigned_to in ("", my_name)]
            else:
                ## Bot shortlist: unassigned tickets RCPond has not already handled
                tickets = [t for t in tickets if t.assigned_to == "" and not t.is_rcpond_processed()]

        return tickets

    def get_ticket(self, ticket_number: str) -> Ticket:
        """Returns the unique ticket matching ``ticket_number``, or raise ValueError if either no match,
        or multiple matches are found.

        The specified ticket may be assigned or unassigned

        Parameters
        ----------
        ticket_number : str
            The ticket number to look up (e.g. ``"RES0001234"``).

        Raises
        ------
        ValueError
            If no ticket matches, or if more than one matches (should not happen
            in practice — ServiceNow enforces uniqueness, but guarded defensively).
        """
        matched = [t for t in self.get_tickets(long_list=True) if t.number == ticket_number]
        if len(matched) == 0:
            err_msg = f"Ticket '{ticket_number}' not found."
            raise ValueError(err_msg)
        if len(matched) > 1:
            ## ServiceNow should prevent duplicate ticket numbers, but guard defensively.
            detail = "\n\n".join(str(t) for t in matched)
            err_msg = f"Multiple tickets match '{ticket_number}':\n{detail}"
            raise ValueError(err_msg)
        return matched[0]

    def web_url(self, tkt: Ticket) -> str:
        """Return the ServiceNow Web UI URL for ``tkt``.

        Parameters
        ----------
        tkt : Ticket
            The ticket to generate a URL for.
        """
        return f"{self._web_base_url.rstrip('/')}/{self._TABLE}.do?sys_id={tkt.sys_id}"

    def get_full_ticket(self, tkt: Ticket) -> FullTicket:
        """Get full ticket details."""

        ## Get details from ServiceNow as JSON
        extra_fields = {field.name for field in dataclasses.fields(FullTicket)} - {
            field.name for field in dataclasses.fields(Ticket)
        }

        ## All extra fields are ServiceNow catalogue variables and must be requested
        ## with the "variables." prefix — they are not top-level record fields.
        requested_fields = {f"variables.{f}" for f in extra_fields}

        resp = self.session.get(
            f"{self._base_api_url}/{self._TABLE}/{tkt.sys_id}",
            params={"sysparm_fields": ",".join(requested_fields), "sysparm_display_value": "all"},
        )

        resp.raise_for_status()

        ## Parse the returned JSON, stripping the "variables." prefix so the keys
        ## match FullTicket field names.
        result = {
            (k[len("variables.") :] if k.startswith("variables.") else k): v for k, v in resp.json()["result"].items()
        }

        return FullTicket.from_Ticket(tkt, **_extract_ticket_fields(result, extra_fields))

    def _fetch_fields(self, sys_id: str, fields: set[str]) -> dict[str, str]:
        """Fetch display values for the specified fields from a single record.

        Parameters
        ----------
        sys_id : str
            The ``sys_id`` of the record to fetch.
        fields : set[str]
            Top-level field names to request.

        Returns
        -------
        dict[str, str]
            Mapping of field name to its display-value string.
        """
        resp = self.session.get(
            f"{self._base_api_url}/{self._TABLE}/{sys_id}",
            params={"sysparm_display_value": "true", "sysparm_fields": ",".join(fields)},
        )
        resp.raise_for_status()
        return _extract_ticket_fields(resp.json()["result"], fields)

    def get_work_notes(self, tkt: Ticket) -> list[NoteEntry]:
        result = self._fetch_fields(tkt.sys_id, {"work_notes"})
        return _parse_comment_display_values(result["work_notes"])

    def get_assignee(self, tkt: Ticket) -> dict[str, str]:
        """
        A convenience method to retrieve the current `assigned_to` field for a Ticket.

        returns:
            A dict with two keys `display_value` and `value`
        """
        resp = self.session.get(
            f"{self._base_api_url}/{self._TABLE}/{tkt.sys_id}",
            params={
                "sysparm_display_value": "all",
                "sysparm_exclude_reference_link": "true",
                "sysparm_fields": "assigned_to",
                "sysparm_query_no_domain": "false",
            },
        )
        resp.raise_for_status()
        return resp.json()["result"]["assigned_to"]

    def post_note(self, tkt: Ticket, note: str) -> None:
        """Post a work note to a ticket.

        Params:
            tkt: The ticket
            note: The note to post
        """
        prefix = _note_prefix()

        ## This will append the `note` param to `work_notes` field
        resp = self.session.patch(
            f"{self._base_api_url}/{self._TABLE}/{tkt.sys_id}",
            json={"work_notes": prefix + note},
        )
        resp.raise_for_status()

    def _fetch_current_user_claims(self) -> dict:
        """Return identity claims for the current OAuth user.

        Tries in order:
        1. Decode the cached ``_id_token`` JWT (no extra network round-trip).
        2. Query the ``sys_user`` table with ``sys_id=javascript:gs.getUserID()``, which
           ServiceNow evaluates server-side so it returns exactly the authenticated user's
           record regardless of their sys_id.

        Returns a dict with at least ``sub`` (sys_id) and ``name`` keys on success.

        Raises
        ------
        RuntimeError
            If user identity cannot be determined.
        """
        if self._id_token:
            try:
                payload_b64 = self._id_token.split(".")[1]
                ## base64url requires padding to a multiple of 4
                return json.loads(base64.urlsafe_b64decode(payload_b64 + "=="))
            except Exception:
                pass  ## Malformed id_token; fall through to sys_user lookup

        try:
            resp = self.session.get(
                f"{self._web_base_url}/api/now/table/sys_user",
                params={
                    "sysparm_query": "sys_id=javascript:gs.getUserID()",
                    "sysparm_fields": "sys_id,name,user_name",
                    "sysparm_display_value": "true",
                },
            )
        except Exception as exc:
            raise RuntimeError(
                "Network error fetching user identity from ServiceNow. "
                "Check your connection and re-authenticate with 'rcpond login'."
            ) from exc

        if not resp.ok:
            raise RuntimeError(
                f"ServiceNow returned HTTP {resp.status_code} when fetching user identity. "
                "Re-authenticate with 'rcpond login'."
            )

        result = resp.json().get("result", [])
        if not result:
            raise RuntimeError(
                "ServiceNow returned no user record for the authenticated session. "
                "Re-authenticate with 'rcpond login'."
            )

        record = result[0]
        return {"sub": record["sys_id"], "name": record["name"], "user_name": record.get("user_name", "")}

    def _current_user_sys_id(self) -> str:
        """Return the current user's sys_id from OIDC claims (``sub`` claim).

        Raises
        ------
        RuntimeError
            If claims are unavailable or contain no ``sub`` field.
        """
        claims = self._fetch_current_user_claims()
        if sub := claims.get("sub"):
            return sub
        raise RuntimeError("User identity claims contain no 'sub' (sys_id). " "Re-authenticate with 'rcpond login'.")

    def _current_user_display_name(self) -> str:
        """Return the display name of the currently authenticated OAuth user.

        Tries OIDC claims (``name`` field) first; falls back to a ``sys_user`` table
        lookup using the ``sub`` claim.

        Returns
        -------
        str
            The user's display name.

        Raises
        ------
        RuntimeError
            If identity cannot be established.
        """
        claims = self._fetch_current_user_claims()
        if name := claims.get("name"):
            return name
        ## id_token present but lacks 'name' claim — look up by sub
        if sub := claims.get("sub"):
            resp = self.session.get(
                f"{self._web_base_url}/api/now/table/sys_user/{sub}",
                params={"sysparm_fields": "name", "sysparm_display_value": "true"},
            )
            resp.raise_for_status()
            return resp.json()["result"]["name"]
        raise RuntimeError(
            "User identity claims contain neither 'name' nor 'sub'. " "Re-authenticate with 'rcpond login'."
        )

    def assign_to_me(self, ticket: Ticket) -> dict[str, str]:
        """Assign ``ticket`` to the currently authenticated OAuth user.

        Parameters
        ----------
        ticket : Ticket
            The ticket to assign.

        Returns
        -------
        dict[str, str]
            The updated assignee dict (``display_value`` and ``value``).

        Raises
        ------
        NotImplementedError
            If the client is using static token authentication, which does not
            carry a per-user identity. OAuth credentials (``servicenow_client_id``
            + ``servicenow_client_secret``) are required to use this feature.
        """
        if not self._is_oauth:
            msg = (
                "assign_to_me() requires OAuth authentication.\n"
                "Static token auth does not carry a per-user identity.\n"
                "Set servicenow_client_id and servicenow_client_secret in your config to enable this feature."
            )
            raise NotImplementedError(msg)
        return self.assign_to(ticket, self._current_user_sys_id())

    def _attempt_assign_to(self, ticket: Ticket, assignee: str) -> None:
        resp = self.session.patch(
            f"{self._base_api_url}/{self._TABLE}/{ticket.sys_id}",
            json={"assigned_to": assignee},
        )
        resp.raise_for_status()

    def assign_to(self, ticket: Ticket, assignee: str) -> dict[str, str]:
        """Assign the current user to a ticket.

        **Post-hoc validation is performed that this assignee exists in the ServiceNow instance. If an invalid value for `assignee` is provided. The method will assign the ticket to the invalid user, detect that it is invalid, and then revert the assignment to the original assignee. This interaction will show in the Activity log for the ticket in the ServiceNow WebUI**

        Example:
        >>> sn.assign_to(my_tkt, "sam@example.com")

        To unassign a ticket, set assignee == "":
        >>> sn.assign_to(my_tkt, "")

        Params:
            ticket: The ticket to be assigned
            assignee: The email address or sys_id (as a str) of the user to assign the ticket to.

        Returns:
            A dict with two keys `display_value` and `value`
        """
        _original_assignee = self.get_assignee(ticket)

        # Attempt assignment
        self._attempt_assign_to(ticket, assignee)

        # Verify success
        new_assignee = self.get_assignee(ticket)

        # The required result is to unassign the ticket (eg assignee is "" or None)
        if not assignee:
            if new_assignee["display_value"] != "" or new_assignee["value"] != "":
                err_msg = f"Expected ticket '{ticket.number}' to be unassigned but got: {new_assignee}"
                raise RuntimeError(err_msg)
            ticket.assigned_to = ""
            return new_assignee

        ## If the assign_to value was not recognised by ServiceNow, then the
        ## display_value will be empty
        if not new_assignee["display_value"]:
            # Reset the assignee to the original value
            # Trust that this works correctly
            self._attempt_assign_to(ticket, _original_assignee["value"])
            err_msg = (
                f"Unable to assign ticket '{ticket.number}' to the user '{assignee}'"
                " The user was not recognised by ServiceNow."
                f" The ticket has been re-assigned back to the original assignee '{_original_assignee['display_value']}/{_original_assignee['value']}'"
            )
            raise ValueError(err_msg)

        ticket.assigned_to = new_assignee["display_value"]
        return new_assignee
